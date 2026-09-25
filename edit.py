#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""edit <文件...> —— 在当前 IDE 窗口打开文件

用法：
  edit <文件...>               在当前 IDE 窗口打开文件
  edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
  edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
  eval "$(edit --init bash)"   同上（bash / sh / dash）

  EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
  edit --list                  列出存活的 IDE 窗口（socket / pid / remote-cli）

  注意 fish 下不能写 eval (edit --init fish)：fish 的 eval 会把多行输出
  用空格拼成一条命令，必须用 | source 才能逐行执行。
  另外 --init 要在集成终端里生成（那里才有 hook 和 remote-cli）。

  两端机制不同：桌面版（macOS 的 code / buddycn / trae-cn）不需要任何 hook，
  CLI 自己会复用当前窗口；server 端（<安装目录>/bin/remote-cli/*）必须有
  VSCODE_IPC_HOOK_CLI，否则 CLI 直接拒绝执行，那种场景才需要 --init。

  行号只在位置参数上识别：以 - 开头的是选项，-- 之后按字面量原样交给 CLI。
  真实存在的文件优先（文件名里可以带冒号）；VS Code 系下存在的路径参数会转成
  绝对路径（remote-cli 是代理，相对路径未必按当前 shell 的 cwd 解释），
  vim 系保持相对路径。其余 CLI（ed 等）不认识行号，file:行号 原样透传。
  列号只有 VS Code 系用得上，vim 系先忽略。

原理：在集成终端里 IDE 已经替你准备好两样东西
  * VSCODE_IPC_HOOK_CLI  指向本会话的窗口 socket
                          （/run/user/<uid>/vscode-ipc-<uuid>.sock）
  * PATH 里              <安装目录>/bin/remote-cli，里面放着
                          code / buddycn / trae-cn 这些官方命令行
把这两样原样交给 remote-cli，等于用该 IDE 自己的命令打开文件；
因为 VS Code / CodeBuddy / Trae 是同一套 remote server，
所以这里不需要知道当前到底是哪一个，也不需要五个不同的命令名。
"""

from __future__ import print_function, unicode_literals

import argparse
import os
import re
import shlex
import shutil
import sys

EDIT_CLI = 'EDIT_CLI'

IPC_HOOK = 'VSCODE_IPC_HOOK_CLI'

CODE_LIKE = ('code', 'buddycn', 'trae-cn', 'cursor',)
VIM_LIKE = ('vim', 'nvim', 'vi',)

# 命令行工具分类
#
# VS Code 系，使用 -g/--goto 跳转
# vim 系, 使用 +行号 跳转
CLI_KIND = {}
CLI_KIND_CODE = 'code'
CLI_KIND_VIM  = 'vim'

for i in CODE_LIKE:
    CLI_KIND[i]   = CLI_KIND_CODE
CLI_KIND['buddy'] = CLI_KIND_CODE
CLI_KIND['trae'] = CLI_KIND_CODE

for i in VIM_LIKE:
    CLI_KIND[i] = CLI_KIND_VIM
# nano 和 emacs 都用 vim 的 +行号 跳转
CLI_KIND['nano'] = CLI_KIND_VIM
CLI_KIND['emacs'] = CLI_KIND_VIM

GOTO_RE = re.compile(r'^(.+?):(\d+)(?::(\d+))?$')

SOCK_PREFIX = 'vscode-ipc-'


def get_ipc_hook():
    """取 VSCODE_IPC_HOOK_CLI 环境变量
    """

    return os.environ.get(IPC_HOOK)


def choose_cli_exe(remote_cli_dir):
    """在 <安装目录>/bin/remote-cli 里挑一个 CLI

    同一个目录里通常只有一个产品的 CLI（code / buddycn / trae-cn…），
    取排序后的第一个可执行文件，排序只为结果稳定。
    返回完整路径；目录不存在或没有可执行文件时返回 None。
    """

    try:
        names = sorted(os.listdir(remote_cli_dir))
    except OSError:
        return None

    for name in names:
        path = os.path.join(remote_cli_dir, name)

        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None

def find_remote_cli():
    """从 PATH 里找 server 端的 remote-cli：<安装目录>/bin/remote-cli/<产品>

    它和 find_path_cli 分工不同：
    * 这里按"目录名是 remote-cli"认，不看产品名 —— 能覆盖还没进 CODE_LIKE 的新产品
    * find_path_cli 按已知产品名认（code / buddycn / …），两者互补

    两个前置判断：
    * 没有 VSCODE_IPC_HOOK_CLI 就不必找了 —— remote-cli 是 server 侧的代理，
      缺 hook 时它自己会报 "Command is only available in WSL or inside a
      Visual Studio Code terminal."，不如把机会让给 $VISUAL/$EDITOR/vim
    * 只看目录结构，不管装在哪（家目录 / 系统目录 / 容器里都认）
    """

    hook = get_ipc_hook()
    if not hook:
        return None

    path = os.environ.get('PATH')
    if not path:
        return None

    for d in path.split(os.pathsep):
        if not d:
            continue

        # remote-cli 的上两级是 <安装目录>/bin/<版本>，那里必定有 node
        # （包装脚本就是 exec "$ROOT/node" "$CLI_SCRIPT"）。用这个结构判断，
        # 比 'server' in d 这类命名约定可靠，也顺带排除掉同名的无关目录。
        if not os.access(os.path.join(d, os.pardir, os.pardir, 'node'), os.X_OK):
            continue

        d = d.rstrip(os.sep)

        # 目录名 remote-cli 是唯一与产品无关的线索，剩下的交给 choose_cli_exe
        b = os.path.basename(d)
        if b != 'remote-cli':
            continue

        cli = choose_cli_exe(d)
        if cli:
            return cli

def find_path_cli():
    for i in CODE_LIKE:
        cli = shutil.which(i)
        if cli:
            return cli

def find_env_cli():
    for i in ('VISUAL', 'EDITOR',):
        v = os.environ.get(i)
        if not v:
            continue

        try:
            name = shlex.split(v)[0]
        except ValueError:
            continue

        cli = shutil.which(name)
        if cli:
            return cli

def find_fallback_cli():
    for i in VIM_LIKE:
        cli = shutil.which(i)
        if cli:
            return cli

def find_user_cli():
    """EDIT_CLI 显式指定，优先级最高，命令名或路径都行

    多个 IDE 同时装着时（macOS 常见：code / buddycn / trae-cn 都在 PATH 里），
    靠 CODE_LIKE 的顺序挑不出来，这时用它点名。

    设了却解析不到就直接报错退出：显式配置不该被静默忽略。
    """

    v = os.environ.get(EDIT_CLI)
    if not v:
        return None

    cli = shutil.which(v)     # 带 / 的按路径找，否则搜 PATH
    if not cli:
        sys.exit('edit: {}={} 找不到可执行文件'.format(EDIT_CLI, v))

    return cli

def find_cli():
    """取 命令行编辑工具

    1. EDIT_CLI 显式指定的。

    2. 终端里 PATH 通常就含 <安装目录>/bin/remote-cli，而且排在很前面，
    如果这个目录下有可执行文件，就用它。

    3. 如果 PATH 里没有，就看看 CODE_LIKE 中的哪个命令行在 PATH 里，
    如果能找到，就用它。

    4. 如果 PATH 里没有，就看看 VISUAL 和 EDITOR 环境变量，
    如果有，就用它。

    5. 什么都没有，就按 VIM_LIKE 的顺序兜底（nvim / vim / vi）
    """

    finders = (
        find_user_cli,
        find_remote_cli,
        find_path_cli,
        find_env_cli,
        find_fallback_cli,
    )

    for choice in finders:
        cli = choice()
        if cli:
            return cli

def cli_kind(cli):
    """判断 cli 属于哪一类，决定 file:行号 用哪种写法

    find_cli() 返回的是绝对路径，所以比 basename，不能比 cli 本身。
    -g 只对 VS Code 系成立；对 vim 系还是有害的（vim -g 是启动 GUI）。
    不在 CLI_KIND 表里的返回 None，按"不认行号"处理：参数原样透传。
    """

    name = os.path.basename(cli)

    return CLI_KIND.get(name)

def parse_goto(arg):
    """'foo.py:12:3' -> ('foo.py', '12', '3')；不像 file:行号 就返回 None
    """

    if os.path.exists(arg):
        return None         # 真实文件优先，文件名里可以带冒号

    m = GOTO_RE.match(arg)
    if not m:
        return None

    if os.path.isdir(m.group(1)):
        return None         # 目录配行号没有意义

    return m.group(1), m.group(2), m.group(3)

def goto_target(goto):
    """(文件, 行号, 列号) 拼回 --goto 的取值

    存在的文件转成绝对路径：remote-cli 是把请求转给 server 的代理，
    相对路径未必按当前 shell 的 cwd 解释。
    """

    file, line, col = goto

    if os.path.exists(file):
        file = os.path.abspath(file)

    if not col:
        return ':'.join((file, line))

    return ':'.join((file, line, col))

def has_goto(args):
    for i in args:
        if i in ('-g', '--goto') or i.startswith('--goto='):
            return True

    return False

def abspath_args(args, kind):
    """存在的路径参数转成绝对路径（只对 code 系）

    remote-cli 是把请求转给 server 的代理，相对路径未必按当前 shell 的 cwd 解释。
    vim/vi 这些本地编辑器按 cwd 解释就够了，保持相对路径更贴近手敲。
    只转存在的：不存在的没法与选项取值（如 --locale zh-cn）区分开。
    """

    if kind != CLI_KIND_CODE:
        return list(args)

    return [os.path.abspath(a) if os.path.exists(a) else a for a in args]

def goto_args(goto, kind):
    """(文件, 行号, 列号) 转成该 CLI 认识的形式

    code：--goto 文件:行号[:列]
    vim ：+行号 放在文件之前。VIM_LIST 里这几个都认 +N；列号各家语法不同
          （vim 是 +call cursor(行,列)、nano 是 +行,列、emacs 是 +行:列），
          先只跳行号。
    """

    file, line, col = goto

    if kind == CLI_KIND_CODE:
        return ['--goto', goto_target(goto)]

    return ['+' + line, file]

def apply_goto(args, kind):
    """把 file:行号 参数改写成对应 CLI 认识的形式

    只有 code 与 vim 两类认识行号，其余（ed 等）原样透传。
    code 是就地成对插 --goto：它是带值的选项，必须紧邻目标，
    否则会把紧跟其后的选项当成自己的值（code --goto -r foo.py:12 是错的）。
    """

    if not kind or has_goto(args):
        return list(args)

    out = []

    for i, a in enumerate(args):
        if a == '--':
            out.extend(args[i:])    # -- 之后是字面量，原样交给 CLI
            break

        if a.startswith('-'):
            out.append(a)           # 选项原样透传
            continue

        goto = parse_goto(a)

        if goto:
            out.extend(goto_args(goto, kind))
        else:
            out.append(a)

    return out

def print_init_script(shell):
    hook = get_ipc_hook()
    if not hook:
        sys.exit('edit --init: 当前终端没有 {}（请在 IDE 集成终端里生成）'.format(IPC_HOOK))

    cli = find_remote_cli()
    if not cli:
        sys.exit('edit --init: 当前终端没找到 {}（请在 IDE 集成终端里生成）'.format(' / '.join(CODE_LIKE)))

    path = os.path.dirname(cli)

    # 值一律 shlex.quote：输出只含单引号段，bash / dash / fish 都认
    hook = shlex.quote(hook)
    path = shlex.quote(path)

    # fish 下只能 `edit --init fish | source`
    # fish 的 eval 会把多行输出用空格拼成一条命令
    if shell == 'fish':
        print('''
set -gx {env} {hook}
if not contains {path} $PATH
    set -p PATH {path}
end
'''.format(env=IPC_HOOK, hook=hook, path=path))
    else:
        print('''
export {env}={hook}
case ":$PATH:" in
*:{path}:*) ;;
*) export PATH={path}:"$PATH" ;;
esac
'''.format(env=IPC_HOOK, hook=hook, path=path))

def find_sockets():
    """列出存活的 vscode-ipc socket 及其归属

    只对 server 端有意义：桌面版（macOS 的 code / buddycn / trae-cn）根本不产生
    这种 socket，CLI 自己会复用当前窗口，没有窗口可挑。
    返回 [{'sock','pid','install','cli'}]；没有 /proc（macOS）时返回 None。
    """

    if not os.path.isdir('/proc'):
        return None

    # /proc/net/unix 只列已 bind 的 socket，天然把残留的 .sock 文件滤掉。
    # 字段：Num(带冒号) RefCount Protocol Flags Type St Inode Path，即 Path 从第 8 个字段起。
    # 用 Path 前面的那个 inode：它和 socket 文件的 st_ino 不是一个数。
    #
    # 只切 7 刀，让 Path 原样留在最后一个字段里：路径里可能带空格（XDG_RUNTIME_DIR
    # 或 TMPDIR 指向带空格的目录时），用 line.split() 后取 p[-1] / p[7] 都会被截断——
    # 好在 Path 是最后一列，切够 7 刀就不会误伤。
    ino2sock = {}
    try:
        with open('/proc/net/unix') as f:
            next(f)
            for line in f:
                # rstrip 只去行尾换行：split 带 maxsplit 时会把 \n 留在最后一个字段里
                fields = line.rstrip('\n').split(None, 7)
                if len(fields) < 8:
                    continue  # 未 bind 的 socket 没有 Path
                if SOCK_PREFIX not in fields[7]:
                    continue
                ino2sock[int(fields[6])] = fields[7]
    except OSError:
        return None

    found = {}

    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue

        try:
            fds = os.listdir('/proc/%s/fd' % pid)
        except OSError:
            continue                    # 别人的进程读不到，跳过

        for fd in fds:
            try:
                link = os.readlink('/proc/%s/fd/%s' % (pid, fd))
            except OSError:
                continue

            if not link.startswith('socket:['):
                continue

            sock = ino2sock.get(int(link[8:-1]))
            if not sock:
                continue

            exe = os.path.realpath('/proc/%s/exe' % pid)
            if not os.path.exists(exe):
                continue  # 进程刚退出，exe 已悬空

            install = os.path.dirname(exe)  # <安装目录>/node -> <安装目录>
            cli = choose_cli_exe(os.path.join(install, 'bin', 'remote-cli'))

            if sock in found and (found[sock]['cli'] or not cli):
                continue  # 同一个 socket 被继承时留有用的那个

            found[sock] = {
                'sock': sock,
                'pid': pid,
                'install': install,
                'cli': cli or '',
            }

    return [found[i] for i in sorted(found)]

def print_sockets():
    socks = find_sockets()

    if socks is None:
        sys.exit('edit --list: 这里没有窗口可挑（桌面版 CLI 自己会复用当前窗口，'
                 '直接 edit <文件> 即可）')

    if not socks:
        sys.exit('edit --list: 没有存活的 IDE 窗口')

    hook = get_ipc_hook()

    # 打印完整 socket 路径：挑完窗口直接就能 export 给 VSCODE_IPC_HOOK_CLI
    print('  #   %-67s %-8s %-9s %s' % ('socket', 'pid', 'cli', 'install'))

    for n, s in enumerate(socks, 1):
        mark = '*' if s['sock'] == hook else ' '
        install = s['install']

        # shlex.quote：路径含空格时整行还能直接粘回 shell；正常路径不加引号
        print('%s %2d  %-67s %-8s %-9s %s' %
              (mark, n, shlex.quote(s['sock']), s['pid'],
               os.path.basename(s['cli']) or '?', install))

def build_args():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)

    parser.add_argument('--init', choices=['fish', 'bash'])
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--dry-run', action='store_true')

    flags, args = parser.parse_known_args()

    return flags, args

def main():
    flags, args = build_args()
    if flags.init:
        if args:
            sys.exit('edit --init 不接受文件参数')
        print_init_script(flags.init)
        return

    if flags.list:
        if args:
            sys.exit('edit --list 不接受文件参数')
        print_sockets()
        return

    cli = find_cli()
    if not cli:
        sys.exit('找不到 cli（%s）' % ' / '.join(CODE_LIKE + VIM_LIKE))

    kind = cli_kind(cli)
    argv = [cli,] + apply_goto(abspath_args(args, kind), kind)

    if flags.dry_run:
        # 拼成可以直接复制执行的一行（bash/fish 都认）
        print(shlex.join(argv))
        return

    os.execv(cli, argv)

if __name__ == '__main__':
    # shell 的惯例：进程被信号 N 干掉，$? 报 128+N。
    # 130=INT(2) 131=QUIT(3)、137=KILL(9)、141=PIPE(13)、143=TERM(15)。
    try:
        status = main()
        # 在 try 内落盘，否则小输出（<8KB）的 EPIPE 发生在退出阶段
        sys.stdout.flush()
        sys.exit(status)
    except BrokenPipeError:
        # print 写管道是缓冲的，EPIPE 多在解释器退出 flush 时才爆，
        # 那时已出了 try 块。把 stdout 指向 devnull 让那次 flush 变空操作。
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(141)
    except KeyboardInterrupt:
        sys.exit(130)
