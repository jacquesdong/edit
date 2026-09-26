#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""edit <文件...> —— 在当前 IDE 窗口打开文件

用法：
  edit <文件...>               在当前 IDE 窗口打开文件
  edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
  edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
  eval "$(edit --init bash)"   同上（bash / sh / dash）

  EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
  edit --list                  列出存活的 IDE 窗口（只读、不读 stdin，会问各窗口 workspace）
  edit --usage                 打印这份用法说明（--help 是透传给 IDE CLI 的）

  edit --init fish --interactive   列出窗口并挑一个，输出它的初始化片段
                                   （普通终端里没有 hook 时用这个）

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

打开文件其实可以不走 CLI：窗口 socket 上就是个 HTTP + JSON 接口
（{"type":"open",…} / {"type":"status"}，remote-cli 自己也是这么发的），
所以有 socket 时直接发；桌面版没有这种 socket，才落回 remote-cli。
"""

from __future__ import print_function, unicode_literals

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import sys
import urllib.parse

from concurrent.futures import ThreadPoolExecutor

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


def current_socket():
    """当前终端所连窗口的 socket（不在 IDE 终端里时 None）

    只在这里读 VSCODE_IPC_HOOK_CLI：调用方要的是"当前窗口"这个概念，而不是
    "某个环境变量"。find_remote_cli 拿它当门控，print_sockets / ask_socket 拿它
    标 * 和当回车默认，main --init 拿它当默认值。
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

    if not current_socket():
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
            return [cli,]

def find_path_cli():
    for i in CODE_LIKE:
        cli = shutil.which(i)
        if cli:
            return [cli,]

def find_env_cli():
    for i in ('VISUAL', 'EDITOR',):
        v = os.environ.get(i)
        if not v:
            continue

        cli = split_cmd(v)
        if cli:
            return cli

def find_fallback_cli():
    for i in VIM_LIKE:
        cli = shutil.which(i)
        if cli:
            return [cli,]

def find_user_cli():
    """EDIT_CLI 显式指定，优先级最高，命令名或路径都行，可带参数

    多个 IDE 同时装着时（macOS 常见：code / buddycn / trae-cn 都在 PATH 里），
    靠 CODE_LIKE 的顺序挑不出来，这时用它点名，例如 EDIT_CLI='code -n'。

    设了却解析不到就直接报错退出：显式配置不该被静默忽略。
    """

    v = os.environ.get(EDIT_CLI)
    if not v:
        return None

    cli = split_cmd(v)        # 带 / 的按路径找，否则搜 PATH
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
    如果有，就用它（可带参数，如 EDITOR='vim -u NONE'）。

    5. 什么都没有，就按 VIM_LIKE 的顺序兜底（nvim / vim / vi）

    返回 argv 列表 [cli, 附加参数...]，找不到返回 None：调用方直接把它拼在
    用户参数前面交给 os.execv（os.execv 不查 PATH，所以第一个元素是绝对路径）。
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

def split_cmd(v):
    """'vim -u NONE' -> ['/usr/bin/vim', '-u', 'NONE']；解析不到返回 None

    第一个词经 which 解析成绝对路径（os.execv 不查 PATH），其余原样保留，
    所以 $EDITOR / $VISUAL / $EDIT_CLI 都能带参数；引号交给 shlex.split，
    路径含空格也没问题。自己配置里的参数不做 abspath，原样交给对方。

    >>> split_cmd('true') == [shutil.which('true')]
    True
    >>> split_cmd('true -a "b c"') == [shutil.which('true'), '-a', 'b c']
    True
    >>> split_cmd('no-such-cmd-xyz -a') is None
    True
    >>> split_cmd('   ') is None
    True
    >>> split_cmd('true "unclosed') is None
    True
    """

    try:
        parts = shlex.split(v)
    except ValueError:
        return None

    if not parts:
        return None

    cli = shutil.which(parts[0])
    if not cli:
        return None

    return [cli,] + parts[1:]

def cli_kind(cli):
    """判断 cli 属于哪一类，决定 file:行号 用哪种写法

    参数是 cli 的绝对路径（find_cli()[0]），所以比 basename，不能比整条命令行。
    -g 只对 VS Code 系成立；对 vim 系还是有害的（vim -g 是启动 GUI）。
    不在 CLI_KIND 表里的返回 None，按"不认行号"处理：参数原样透传。

    >>> cli_kind('/opt/ide/bin/remote-cli/buddycn')
    'code'
    >>> cli_kind('/usr/bin/buddy')
    'code'
    >>> cli_kind('/usr/bin/vim')
    'vim'
    >>> cli_kind('/usr/bin/ed') is None
    True
    """

    name = os.path.basename(cli)

    return CLI_KIND.get(name)

def parse_goto(arg):
    """'foo.py:12:3' -> ('foo.py', '12', '3')；不像 file:行号 就返回 None

    真实存在的文件优先（文件名里可以带冒号）；目录配行号没有意义。

    >>> parse_goto('no-such-file.py:12')
    ('no-such-file.py', '12', None)
    >>> parse_goto('no-such-file.py:12:3')
    ('no-such-file.py', '12', '3')
    >>> parse_goto('no-such-file.py:abc') is None
    True
    >>> parse_goto('no-such-file.py:') is None
    True
    >>> parse_goto('/:12') is None              # 目录不算
    True
    >>> import tempfile
    >>> f = os.path.join(tempfile.gettempdir(), 'edit-doctest:12')
    >>> open(f, 'w').close()
    >>> parse_goto(f) is None                   # 真实文件优先于 file:行号
    True
    >>> os.remove(f)
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

    （例子用 realpath 而非 __file__：经 ~/.local/bin/edit 软链调用时
    __file__ 就是软链路径，abspath 不会解开它）

    >>> goto_target(('no-such-file.py', '12', None))
    'no-such-file.py:12'
    >>> goto_target(('no-such-file.py', '12', '3'))
    'no-such-file.py:12:3'
    >>> p = os.path.relpath(os.path.realpath(__file__))     # 相对路径，且真实存在
    >>> goto_target((p, '12', None)) == os.path.realpath(__file__) + ':12'
    True
    """

    file, line, col = goto

    if os.path.exists(file):
        file = os.path.abspath(file)

    if not col:
        return ':'.join((file, line))

    return ':'.join((file, line, col))

def has_goto(args):
    """命令行里是否已经带了跳转选项（带了就不再改写）

    >>> has_goto(['-g', 'no-such-file.py:12'])
    True
    >>> has_goto(['--goto', 'no-such-file.py:12'])
    True
    >>> has_goto(['--goto=no-such-file.py:12'])
    True
    >>> has_goto(['no-such-file.py:12'])
    False
    """

    for i in args:
        if i in ('-g', '--goto') or i.startswith('--goto='):
            return True

    return False

def abspath_args(args, kind):
    """存在的路径参数转成绝对路径（只对 code 系）

    remote-cli 是把请求转给 server 的代理，相对路径未必按当前 shell 的 cwd 解释。
    vim/vi 这些本地编辑器按 cwd 解释就够了，保持相对路径更贴近手敲。
    只转存在的：不存在的没法与选项取值（如 --locale zh-cn）区分开。

    >>> abspath_args(['no-such-file.py'], CLI_KIND_CODE)        # 不存在的原样
    ['no-such-file.py']
    >>> abspath_args(['--locale', 'zh-cn'], CLI_KIND_CODE)      # 选项取值不动
    ['--locale', 'zh-cn']
    >>> abspath_args([__file__], CLI_KIND_CODE) == [os.path.abspath(__file__)]
    True
    >>> abspath_args([__file__], CLI_KIND_VIM) == [__file__]    # vim 系保持相对
    True
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

    >>> goto_args(('no-such-file.py', '12', None), CLI_KIND_CODE)
    ['--goto', 'no-such-file.py:12']
    >>> goto_args(('no-such-file.py', '12', None), CLI_KIND_VIM)
    ['+12', 'no-such-file.py']
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

    >>> apply_goto(['no-such-file.py:12'], CLI_KIND_CODE)
    ['--goto', 'no-such-file.py:12']
    >>> apply_goto(['-r', 'no-such-file.py:12'], CLI_KIND_CODE)   # 就地成对
    ['-r', '--goto', 'no-such-file.py:12']
    >>> apply_goto(['-g', 'no-such-file.py:12'], CLI_KIND_CODE)   # 已有 -g 不重复加
    ['-g', 'no-such-file.py:12']
    >>> apply_goto(['--', 'no-such-file.py:12'], CLI_KIND_CODE)   # -- 之后按字面量
    ['--', 'no-such-file.py:12']
    >>> apply_goto(['no-such-file.py:12'], CLI_KIND_VIM)          # vim 用 +行号
    ['+12', 'no-such-file.py']
    >>> apply_goto(['no-such-file.py:12'], None)                  # 不认行号则原样
    ['no-such-file.py:12']
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

def print_init_script(shell, hook=None, cli_dir=None):
    """输出可直接导入当前 shell 的片段

    hook   要写进 VSCODE_IPC_HOOK_CLI 的 socket 路径
    cli_dir  要 prepend 进 PATH 的 remote-cli 目录

    缺值（或 cli_dir 不是目录）时什么都不打印，由调用方负责报错：
    main 的 --init 分支从当前终端取，--interactive 分支从选中的窗口取。
    """

    if not hook:
        return

    if not cli_dir:
        return

    if not os.path.isdir(cli_dir):
        return

    path = cli_dir

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

            # 同一个 socket 可能被多个进程 / fd 认领，而 install / cli / pid 都取自
            # "认领它的那个进程"，所以优先留能推出 <安装目录>/bin/remote-cli 的那条
            old = found.get(sock)

            if old is not None:
                if old['cli']:
                    continue        # 已有能推出 CLI 的记录，不动

                if not cli:
                    continue        # 两条都推不出，也留旧的（免得 pid 随遍历顺序变）

            # 首次见到，或旧的推不出而新的推得出 -> 记下新的
            found[sock] = {
                'sock': sock,
                'pid': pid,
                'install': install,
                'cli': cli or '',
            }

    return [found[i] for i in sorted(found)]

def http_body(raw):
    """HTTP 回复 -> 正文；只处理 chunked（socket 上的回复都是这种）

    >>> http_body(b'HTTP/1.1 200 OK\\r\\n\\r\\n5\\r\\nhello\\r\\n0\\r\\n\\r\\n')
    'hello'
    >>> http_body(b'HTTP/1.1 200 OK\\r\\n\\r\\n')                # 空正文
    ''
    >>> http_body(b'HTTP/1.1 200 OK\\r\\n\\r\\nnot-chunked')     # 不带分块就整段返回
    'not-chunked'
    """

    _, _, rest = raw.partition(b'\r\n\r\n')

    if not re.match(rb'^[0-9a-fA-F]+\r\n', rest):
        return rest.decode('utf-8', 'replace')

    out = []

    while True:
        line, _, rest = rest.partition(b'\r\n')

        try:
            size = int(line.split(b';')[0], 16)     # 允许 chunk 扩展
        except ValueError:
            break

        if size == 0:
            break

        out.append(rest[:size])
        rest = rest[size + len(b'\r\n'):]           # 跳过数据后面的 CRLF

    return b''.join(out).decode('utf-8', 'replace')

def file_uri(path, line=None, col=None):
    """路径 -> file URI；行号/列号按 VS Code 的写法拼在末尾（冒号不转义）

    编码与 remote-cli 发的完全一致（空格 -> %20，非 ASCII -> UTF-8 percent）。
    别用 pathlib 的 as_uri()：它会把 :3 的冒号也编成 %3A。

    >>> file_uri('/tmp/a b.txt')
    'file:///tmp/a%20b.txt'
    >>> file_uri('/tmp/探 试.txt')
    'file:///tmp/%E6%8E%A2%20%E8%AF%95.txt'
    >>> file_uri('/tmp/a.txt', '3')
    'file:///tmp/a.txt:3'
    >>> file_uri('/tmp/a.txt', '3', '5')
    'file:///tmp/a.txt:3:5'
    """

    uri = 'file://' + urllib.parse.quote(os.path.abspath(path))

    if line:
        uri += ':' + line

        if col:
            uri += ':' + col

    return uri

def parse_status(text):
    """从 status 文本里抠出 (authority, workspace)

    窗口自己的 argv 长这样：'--remote <authority> <workspace>'。本地窗口没有
    --remote，那就两者都是 None（也就没法靠它认窗口）。

    >>> parse_status('Process Argv:     --remote codebuddy-remote-ssh+xa /home/dongjq/config')
    ('codebuddy-remote-ssh+xa', '/home/dongjq/config')
    >>> parse_status('Process Argv:     --remote codebuddy-remote-ssh+xa')    # 没开文件夹
    ('codebuddy-remote-ssh+xa', None)
    >>> parse_status('Process Argv:     /usr/share/code/edit')
    (None, None)
    """

    m = re.search(r'^Process Argv:\s*(.*)$', text, re.M)
    if not m:
        return None, None

    m = re.search(r'--remote\s+(\S+)\s*(.*)$', m.group(1))
    if not m:
        return None, None

    return m.group(1), m.group(2).strip() or None

def socket_request(sock, msg, timeout=1.5):
    """往窗口 socket 发一次请求，返回原始 HTTP 回复；失败返回 None

    协议就是 remote-cli 自己那套：POST / + JSON，回复是 chunked。连不上 / 超时
    一律返回 None 且不抛异常。

    >>> socket_request('/no-such.sock', {'type': 'status'}, timeout=0.1) is None
    True
    """

    body = json.dumps(msg).encode()
    req = (b'POST / HTTP/1.1\r\nHost: localhost\r\n'
           b'content-type: application/json\r\naccept: application/json\r\n'
           b'content-length: %d\r\nconnection: close\r\n\r\n' % len(body)) + body

    chunks = []
    total = 0

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(sock)

            conn.sendall(req)

            while total < (1 << 20):        # status 回复 2~3KB，1MB 足够
                data = conn.recv(65536)
                if not data:
                    break
                chunks.append(data)
                total += len(data)
    except OSError:
        return None

    return b''.join(chunks)

def http_code(raw):
    """HTTP 回复的状态码；解不出来返回 0

    >>> http_code(b'HTTP/1.1 200 OK\\r\\n\\r\\n')
    200
    >>> http_code(b'garbage')
    0
    """

    parts = raw.split(b'\r\n', 1)[0].split()

    if len(parts) > 1 and parts[1].isdigit():
        return int(parts[1])

    return 0

def socket_status(sock, timeout=1.5):
    """直连窗口 socket 问一次只读 status，返回 (authority, workspace)

    任何失败（连不上 / 超时 / 解析不了）都返回 (None, None) 且不抛异常 ——
    它在并发探测的线程里跑。
    """

    raw = socket_request(sock, {'type': 'status'}, timeout)
    if not raw:
        return None, None

    try:
        text = json.loads(http_body(raw))
    except ValueError:
        return None, None

    if not isinstance(text, str):
        return None, None

    return parse_status(text)

# 能和 open 报文一一对应的选项；其余选项（--wait / -g / 未知的）都交回 CLI
OPEN_FLAGS = {
    '-r': 'forceReuseWindow', '--reuse-window': 'forceReuseWindow',
    '-n': 'forceNewWindow', '--new-window': 'forceNewWindow',
    '-a': 'addMode', '--add': 'addMode',
    '-d': 'diffMode', '--diff': 'diffMode',
}

def open_request(args):
    """把命令行参数翻译成 socket 直连要发的 open 报文；翻不了返回 None

    翻不了就交回 CLI：--wait / --merge / -g / 未知选项 / -- / 没给参数。
    目录进 folderURIs，文件进 fileURIs，:行号[:列] 交给 parse_goto 认。

    >>> open_request(['/no-such-dir/x.py'])['fileURIs']
    ['file:///no-such-dir/x.py']
    >>> open_request(['/no-such-dir/x.py:3'])['gotoLineMode']
    True
    >>> open_request(['/no-such-dir/x.py:3:5'])['fileURIs']
    ['file:///no-such-dir/x.py:3:5']
    >>> open_request(['-r', '/no-such-dir/x.py'])['forceReuseWindow']
    True
    >>> open_request(['/'])['folderURIs']           # 目录单独放
    ['file:///']
    >>> open_request(['--wait', '/no-such-dir/x.py']) is None
    True
    >>> open_request(['-g', '/no-such-dir/x.py:3']) is None
    True
    >>> open_request([]) is None
    True
    """

    msg = {
        'type': 'open',
        'fileURIs': [],
        'folderURIs': [],
        'diffMode': False,
        'mergeMode': False,
        'addMode': False,
        'gotoLineMode': False,
        'forceReuseWindow': False,
        'forceNewWindow': False,
    }

    for a in args:
        if a == '--':
            return None             # 之后的参数按字面量，交回 CLI

        if a.startswith('-'):
            field = OPEN_FLAGS.get(a)
            if not field:
                return None         # 不认识的选项（--wait / -g / …）交回 CLI

            msg[field] = True
            continue

        goto = parse_goto(a)

        if goto:
            msg['fileURIs'].append(file_uri(*goto))
            msg['gotoLineMode'] = True
        elif os.path.isdir(a):
            msg['folderURIs'].append(file_uri(a))
        else:
            msg['fileURIs'].append(file_uri(a))

    if not msg['fileURIs'] and not msg['folderURIs']:
        return None                 # 没东西可开：保持 CLI 原来的行为

    return msg

def socket_open(sock, msg, timeout=3.0):
    """把 open 报文发给窗口，返回 (ok, 详情)

    判据和 CLI 一致：只认 HTTP 200（CLI 就是 JSON.parse 之后看 statusCode）。
    详情是回复正文，失败时正好拿来当错误信息。
    """

    raw = socket_request(sock, msg, timeout)
    if not raw:
        return False, '连不上或超时'

    code = http_code(raw)
    detail = http_body(raw).strip()

    return code == 200, detail or ('HTTP %s' % code)

def probe_workspaces(socks, timeout=1.5):
    """并发问每个候选窗口要一次 status，把 authority / workspace 填进候选

    一次 status 约 0.26s，串行 5 个窗口就得等 1.3s，所以用线程池；线程数封顶
    8，别一下子砸一堆请求过去。socket_status 自己吞异常，某个窗口卡住最多等到
    timeout，失败就留下 (None, None)，显示成 ?。
    """

    if not socks:
        return

    with ThreadPoolExecutor(max_workers=min(8, len(socks))) as pool:
        futures = [pool.submit(socket_status, s['sock'], timeout) for s in socks]

        for s, fut in zip(socks, futures):
            s['authority'], s['workspace'] = fut.result()

def format_sockets(socks, hook):
    """把候选渲染成表格行：--list 打印它，--init --interactive 也用它

    打印完整 socket 路径：挑完窗口直接就能 export 给 VSCODE_IPC_HOOK_CLI。
    和 hook 相同的那个用 * 标出来；workspace 是问窗口要来的，问不到就是 ?。

    >>> s = [{'sock': '/r/vscode-ipc-a.sock', 'pid': '1',
    ...       'cli': '/i/bin/remote-cli/buddycn', 'workspace': '/w/proj'}]
    >>> format_sockets(s, '/r/vscode-ipc-a.sock')[1].split()[0]
    '*'
    >>> format_sockets(s, None)[1].split()[0]
    '1'
    >>> format_sockets(s, None)[1].split()[-2:]
    ['buddycn', '/w/proj']
    >>> b = [{'sock': '/r/a b.sock', 'pid': '1', 'cli': ''}]
    >>> " '/r/a b.sock'" in format_sockets(b, None)[1]
    True
    >>> format_sockets(b, None)[1].split()[-2:]     # cli / workspace 都读不到
    ['?', '?']
    """

    lines = ['  #   %-67s %-8s %-9s %s' % ('socket', 'pid', 'cli', 'workspace')]

    for n, s in enumerate(socks, 1):
        mark = '*' if s['sock'] == hook else ' '

        # shlex.quote：路径含空格时整行还能直接粘回 shell；正常路径不加引号
        lines.append('%s %2d  %-67s %-8s %-9s %s' %
                     (mark, n, shlex.quote(s['sock']), s['pid'],
                      os.path.basename(s['cli']) or '?', s.get('workspace') or '?'))

    return lines

def load_sockets(tag):
    """取候选并问出各自的 workspace；不适用 / 一个都没有时按 tag 报错退出

    tag 形如 'edit --list'、'edit --init --interactive'，只用来拼错误信息。
    返回的候选里带 authority / workspace（探测失败就是 None）。
    """

    socks = find_sockets()

    if socks is None:
        sys.exit('%s: 这里没有窗口可挑（桌面版 CLI 自己会复用当前窗口，'
                 '直接 edit <文件> 即可）' % tag)

    if not socks:
        sys.exit('%s: 没有存活的 IDE 窗口' % tag)

    probe_workspaces(socks)

    return socks

def print_sockets():
    socks = load_sockets('edit --list')

    print('\n'.join(format_sockets(socks, current_socket())))

def pick_socket(socks, answer, hook=None):
    """把用户输入解释成候选项；认不出返回 None

    '2' -> socks[1]；空行 -> hook 指向的那个（当前窗口）；
    其余（'q'、非数字、越界）-> None

    >>> socks = [{'sock': '/a.sock'}, {'sock': '/b.sock'}]
    >>> pick_socket(socks, '2')
    {'sock': '/b.sock'}
    >>> pick_socket(socks, '2 ')
    {'sock': '/b.sock'}
    >>> pick_socket(socks, '', '/a.sock')
    {'sock': '/a.sock'}
    >>> pick_socket(socks, '') is None
    True
    >>> pick_socket(socks, '0') is None
    True
    >>> pick_socket(socks, '3') is None
    True
    >>> pick_socket(socks, 'q') is None
    True
    """

    answer = answer.strip()

    if not answer:
        for s in socks:
            if s['sock'] == hook:
                return s
        return None

    if not answer.isdigit():
        return None

    n = int(answer)

    if not 1 <= n <= len(socks):
        return None

    return socks[n - 1]

def ask_socket(socks):
    """列出候选并让用户挑一个，返回候选项

    候选和提示都写 stderr：stdout 要留给最终的初始化片段，这样
    `edit --init fish --interactive | source` 才不会被提示语打断。
    有 hook 时（= 当前终端连着某个窗口）回车表示那个窗口；没有 hook 就没有
    当前窗口，只能输编号。q / EOF / 认不出的输入都算取消。
    """

    current = current_socket()

    sys.stderr.write('\n'.join(format_sockets(socks, current)) + '\n')
    if current:
        sys.stderr.write('选择窗口编号 [1-%d]（回车 = 当前窗口，q = 取消）: ' % len(socks))
    else:
        sys.stderr.write('选择窗口编号 [1-%d]（q = 取消）: ' % len(socks))
    sys.stderr.flush()

    try:
        # input 不带 prompt：它的 prompt 写 stdout，会把片段流弄脏
        answer = input()
    except EOFError:
        sys.exit('edit --init --interactive: 没读到编号（stdin 已结束）')

    chosen = pick_socket(socks, answer, current)
    if not chosen:
        sys.exit('edit --init --interactive: 没有选中窗口')

    return chosen

def print_usage():
    """打印本文件开头的用法说明

    --help 是透传给 IDE CLI 的（add_help=False），本程序自己的开关只能从这里查。
    """

    print(__doc__)

def build_args():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)

    parser.add_argument('--init', choices=['fish', 'bash'])
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--usage', action='store_true')

    flags, args = parser.parse_known_args()

    return flags, args

def main():
    flags, args = build_args()
    if flags.usage:
        if args:
            sys.exit('edit --usage 不接受文件参数')
        print_usage()
        return

    if flags.interactive and not flags.init:
        sys.exit('edit --interactive: 现在只和 --init 一起用')

    if flags.init:
        if args:
            sys.exit('edit --init 不接受文件参数')

        if flags.list:
            sys.exit('edit --init 和 edit --list 冲突（挑窗口请用 --interactive）')

        if flags.interactive:
            # 列出候选（stderr）挑一个，用它的 hook 和 CLI 目录输出片段
            s = ask_socket(load_sockets('edit --init --interactive'))
            # cli 读不到时（别人的进程，权限不够）退回按安装目录推
            cli_dir = os.path.dirname(s['cli']) or os.path.join(s['install'], 'bin', 'remote-cli')

            if not os.path.isdir(cli_dir):
                # print_init_script 取不到值就静默不输出，所以这里先判一次
                sys.exit('edit --init --interactive: {} 不是目录（换个窗口试试）'.format(cli_dir))

            print_init_script(flags.init, s['sock'], cli_dir)
        else:
            hook = current_socket()
            if not hook:
                sys.exit('edit --init: 当前终端没有 {}（请在 IDE 集成终端里生成，'
                         '或用 edit --init <shell> --interactive 挑一个窗口）'.format(IPC_HOOK))

            cli = find_remote_cli()
            if not cli:
                sys.exit('edit --init: 当前终端没找到 {}（请在 IDE 集成终端里生成，'
                         '或用 edit --init <shell> --interactive 挑一个窗口）'.format(' / '.join(CODE_LIKE)))

            print_init_script(flags.init, hook, os.path.dirname(cli[0]))

        return

    if flags.list:
        if args:
            sys.exit('edit --list 不接受文件参数')
        print_sockets()
        return

    if flags.self_test:
        if args:
            sys.exit('edit --self-test 不接受文件参数')

        import doctest            # 只在自检分支 import，不给正常路径加依赖

        result = doctest.testmod()
        print('edit --self-test: %d passed, %d failed' %
              (result.attempted, result.failed))

        return 1 if result.failed else 0

    # server 端直接和窗口 socket 说话：不用找 CLI，也不用起 node。
    # 翻不了（--wait / -g / 未知选项）或发失败，就交给下面的 CLI 路径
    sock = current_socket()
    msg = open_request(args) if sock else None

    if msg:
        if flags.dry_run:
            print('socket %s %s' % (sock, json.dumps(msg, ensure_ascii=False)))
            return

        ok, detail = socket_open(sock, msg)

        if ok:
            return

        sys.stderr.write('edit: socket 打不开（%s），改用 CLI\n' % detail)

    cli = find_cli()
    if not cli:
        sys.exit('找不到 cli（%s）' % ' / '.join(CODE_LIKE + VIM_LIKE))

    # cli 是 argv 列表：[可执行文件, 自己配置里的参数...]（如 EDITOR='vim -u NONE'）
    kind = cli_kind(cli[0])
    argv = cli + apply_goto(abspath_args(args, kind), kind)

    if flags.dry_run:
        # 拼成可以直接复制执行的一行（bash/fish 都认）
        print(shlex.join(argv))
        return

    os.execv(cli[0], argv)

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
