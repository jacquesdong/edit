#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""edit <文件...> —— 在当前 IDE 窗口打开文件

用法：
  edit <文件...>               在当前 IDE 窗口打开文件
  edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
  edit --wait <文件>           等文件在编辑器里被关掉才返回（当 $EDITOR / core.editor 用）
  edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
  eval "$(edit --init bash)"   同上（bash / sh / dash）

  EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
  edit --list                  列出存活的 IDE 窗口（只读、不读 stdin，会问各窗口 workspace）
  edit --usage                 打印这份用法说明（--help 是透传给 IDE CLI 的）

  edit --init fish --interactive   列出窗口并挑一个，输出它的初始化片段
                                   （普通终端里没有 hook 时用这个）
  edit --interactive <文件...>     列出窗口并挑一个，在挑中的那个里打开文件
                                   （普通终端里没有 hook、又想指定窗口时用这个）
                                   （装了 fzf 就用它挑；EDIT_FZF=0 关掉，改输编号）

  注意 fish 下不能写 eval (edit --init fish)：fish 的 eval 会把多行输出
  用空格拼成一条命令，必须用 | source 才能逐行执行。
  另外 --init 要在集成终端里生成（那里才有 hook 和 remote-cli）。

  两端机制不同：桌面版（macOS 的 code / buddycn / trae-cn）不需要任何 hook，
  CLI 自己会复用当前窗口；server 端（<安装目录>/bin/remote-cli/*）必须有
  VSCODE_IPC_HOOK_CLI，否则 CLI 直接拒绝执行，那种场景才需要 --init。

  行号只认位置参数的 文件:行号 写法：-g / --goto 被直接忽略（edit 对带行号的参数本来
  就跳转，所以 -g f:3 与 f:3 完全等价），它们也不消费后面的参数（-g -r f:3 里 -r 仍
  是选项）。内联写法 --goto=X / -g=X 不特判 —— 上游自己也不认（实测取值会被丢掉或
  塞错字段），所以跟别的"不认识的选项"一样原样交给 CLI。此外以 - 开头的是选项，
  -- 之后按字面量原样交给 CLI；其中 -m / --merge 带 4 个取值（path1 path2 base
  result），取值不够就交回 CLI 报错。
  真实存在的文件优先（文件名里可以带冒号）；VS Code 系下存在的路径参数会转成
  绝对路径（remote-cli 是代理，相对路径未必按当前 shell 的 cwd 解释），
  vim 系保持相对路径。其余 CLI（ed 等）不认识行号，只传文件。
  列号：VS Code 系 --goto 文件:行:列，emacs 系 +N:M，nano +N,M（都是 1 起），
  vim 不支持（只用 +N）。
  --wait / -w 同理只在 VS Code 系有意义：交回 vim 系 CLI 时会被摘掉（vim 没有
  这个选项，-w 还是"把键入的命令写进文件"的意思；而终端 vim 本来就等到退出）。
  -r / -n / -a 也一样摘掉（vim -r 是恢复交换文件、nano -n 是只写不读、emacs -r 是
  反色显示…）；-d 只有 vim 是同义（diff 模式）所以保留；-m 合并没有等价物，丢开关
  但四个路径照开。这几项在 EMIT 里各占一项，逐项注释就是实测出来的含义对照。
  另外 -a / -d / --wait 空着（既没文件也没目录）是误用：直接提示退出、不交给 CLI；
  裸调用与只给 -r / -n 不拦 —— 那是 code 系"开窗口 / 复用窗口 / 新窗口"的既定用法。
  行号只在交回别的 CLI 时才需要翻译：code 系 --goto 文件:行:列（一个目标一份），
  vim 系 +行号。所以绝不能把 -g 原样透传过去：vim -g 是启动 GUI 会 E25
  报错、emacs -g 是 --geometry 会吃掉后面的文件名、nano -g 是 --showcursor。

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

--wait 也是直连：先 mkstemp 一个空 marker，把它的路径放在报文的
waitMarkerFilePath 里，窗口在文件被关掉时删掉它，我们等它消失 —— 和
remote-cli 一模一样（它也是 createWaitMarkerFile + 每秒 existsSync 轮询），
所以 git commit 之类的场景同样等得住，而且不起 node。
"""

from __future__ import annotations       # 注解不求值：别名放哪都行，运行期也不构造它们

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal, TypeAlias, TypedDict

# 显式点名用哪个 CLI 打开文件（命令名或路径，可带参数），挑 CLI 时优先级最高；
EDIT_CLI = 'EDIT_CLI'

# 挑窗口时不想用 fzf 就设成 0 / off / never（脚本、测试）
EDIT_FZF = 'EDIT_FZF'

IPC_HOOK = 'VSCODE_IPC_HOOK_CLI'

CODE_LIKE = ('code', 'buddycn', 'trae-cn', 'cursor',)
VIM_LIKE = ('vim', 'nvim', 'vi',)

# 命令行工具分类
#
# VS Code 系，写它自己的命令行时用 --goto 跳转
# vim 系, 使用 +行号 跳转
# nano / emacs 系同样用 +行号，单开一类是因为列号写法不同（见 EMIT）
CLI_KIND = {}
CLI_KIND_CODE  = 'code'
CLI_KIND_VIM   = 'vim'
CLI_KIND_NANO  = 'nano'
CLI_KIND_EMACS = 'emacs'

for i in CODE_LIKE:
    CLI_KIND[i]   = CLI_KIND_CODE
CLI_KIND['buddy'] = CLI_KIND_CODE
CLI_KIND['trae'] = CLI_KIND_CODE

for i in VIM_LIKE:
    CLI_KIND[i] = CLI_KIND_VIM

CLI_KIND['nano'] = CLI_KIND_NANO

for i in ('emacs', 'emacsclient'):       # 当 $EDITOR 用的是后者
    CLI_KIND[i] = CLI_KIND_EMACS

# file:行[:列]：只有末尾的数字才算行列号，非贪婪的 (.+?) 把冒号让给文件名，
# 所以文件名里带冒号也解析得动（parse_goto 靠它，split_goto 是它的一步）
GOTO_RE = re.compile(r'^(.+?):(\d+)(?::(\d+))?$')

# server 端窗口 socket 的文件名前缀（/run/user/<uid>/vscode-ipc-<uuid>.sock），
# find_sockets 拿它从 /proc/net/unix 里筛出 IDE 窗口的 socket
SOCK_PREFIX = 'vscode-ipc-'

# /proc 的根：find_sockets 全程只从这里读，测试可以把它指到假目录
PROC = '/proc'


def current_socket():
    """当前终端所连窗口的 socket（不在 IDE 终端里时 None）

    只在这里读 VSCODE_IPC_HOOK_CLI：调用方要的是"当前窗口"这个概念，而不是
    "某个环境变量"。find_remote_cli 拿它当门控，print_sockets / ask_socket 拿它
    标 * 和当回车默认，main --init 拿它当默认值。
    """

    return os.environ.get(IPC_HOOK)

def redirect_socket(sock):
    """把"当前窗口"重定向到 sock：之后 current_socket() 就返回它

    和 current_socket() 成对，读写都收在这两个函数里。改的是环境变量而不是往
    下传参，是因为回退到 CLI 时 os.execv 会把环境整个交给它 —— 挑中的窗口对
    直连和 CLI 两条路都生效。目前只有 main 的 --interactive 用。

    >>> saved = current_socket()
    >>> redirect_socket('/x.sock') or current_socket()
    '/x.sock'
    >>> _ = redirect_socket(saved) if saved else os.environ.pop(IPC_HOOK, None)
    >>> current_socket() == saved
    True
    """

    os.environ[IPC_HOOK] = sock


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

def have_remote_cli(d):
    """目录是不是 <安装目录>/bin/remote-cli

    remote-cli 的上两级是 <安装目录>/bin/<版本>，那里必定有 node（包装脚本会
    exec 它）。find_remote_cli 用这个结构找 CLI；cli_kind 也靠它判断未知产品名：
    这里的 CLI 即使还没进 CODE_LIKE，也是 VS Code 系协议。
    """

    d = d.rstrip(os.sep)

    return (os.path.basename(d) == 'remote-cli' and
            os.access(os.path.join(d, os.pardir, os.pardir, 'node'), os.X_OK))

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

        if not have_remote_cli(d):
            continue

        # 目录名 remote-cli 是唯一与产品无关的线索，剩下的交给 choose_cli_exe
        cli = choose_cli_exe(d.rstrip(os.sep))
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

    先比 basename；名字不在表里、但路径符合 server 端 remote-cli 结构时，也按
    VS Code 系处理（新产品名不必进白名单）。判错就是翻错写法：给 vim 递 --goto
    （`vim --goto` 直接不认）、给 VS Code 递 +行号，`--wait` 也会留错（见 EMIT）。
    其余 CLI 返回 None，按"不认行号"处理。

    >>> cli_kind('/opt/ide/bin/remote-cli/buddycn')
    'code'
    >>> cli_kind('/usr/bin/buddy')
    'code'
    >>> cli_kind('/usr/bin/vim')
    'vim'
    >>> cli_kind('/usr/bin/nano')                   # 同样用 +行号，但单开一类
    'nano'
    >>> cli_kind('/usr/local/bin/emacs')
    'emacs'
    >>> cli_kind('/usr/local/bin/emacsclient')      # 和 emacs 同一类
    'emacs'
    >>> cli_kind('/usr/bin/ed') is None
    True
    """

    kind = CLI_KIND.get(os.path.basename(cli))
    if kind:
        return kind

    if have_remote_cli(os.path.dirname(cli)):
        return CLI_KIND_CODE

    return None

def split_goto(arg: str) -> GotoTarget | None:
    """'foo.py:12:3' -> ('foo.py', '12', '3')；不像 file:行号 就返回 None

    和 parse_goto 的差别：不做"真实文件优先"的判断。parse_goto 靠它把行号/列号
    拆出来 —— 只有 parse_goto 这一个调用点，所以"文件名带冒号"的取舍收在那里。

    >>> split_goto('no-such-file.py:12')
    ('no-such-file.py', '12', None)
    >>> split_goto('no-such-file.py:12:3')
    ('no-such-file.py', '12', '3')
    >>> split_goto('no-such-file.py:abc') is None
    True
    >>> split_goto('no-such-file.py:') is None
    True
    >>> split_goto('/:12') is None                  # 目录不算
    True
    """

    m = GOTO_RE.match(arg)
    if not m:
        return None

    if os.path.isdir(m.group(1)):
        return None         # 目录配行号没有意义

    return m.group(1), m.group(2), m.group(3)

def parse_goto(arg: str) -> GotoTarget | None:
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

    return split_goto(arg)

def goto_target(goto: GotoTarget) -> str:
    """(文件, 行号, 列号) 拼回 文件:行:列

    只给 code 系用：作 `--goto` 的取值（每个目标一份，实测 CLI 的 `-g` 可重复）。

    存在的文件转成绝对路径：remote-cli 是把请求转给 server 的代理，
    相对路径未必按当前 shell 的 cwd 解释。

    这一步不能指望 `to_argv` 末尾那次统一的 abspath：那步是逐个 out 元素判
    `os.path.exists`，而这里已经把路径拼进了 `f:3` 这样一个字符串 —— `exists` 必然
    为假，够不着（它只对 `file` / `folder` 那种裸路径有效）。所以要在这儿自己转。

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

    if not os.path.isdir(PROC):
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
        with open(os.path.join(PROC, 'net', 'unix')) as f:
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

    found: dict[str, dict[str, str]] = {}

    for pid in os.listdir(PROC):
        if not pid.isdigit():
            continue

        try:
            fds = os.listdir(os.path.join(PROC, pid, 'fd'))
        except OSError:
            continue                    # 别人的进程读不到，跳过

        for fd in fds:
            try:
                link = os.readlink(os.path.join(PROC, pid, 'fd', fd))
            except OSError:
                continue

            if not link.startswith('socket:['):
                continue

            sock = ino2sock.get(int(link[8:-1]))
            if not sock:
                continue

            exe = os.path.realpath(os.path.join(PROC, pid, 'exe'))
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

# token 的形状 —— 一个生产者（normalize / arg_token）、两个消费者（to_msg / to_argv）：
#   opt    认得的选项 + 它的取值（开关选项是 []）
#   goto   文件:行号[:列]（列可能没有）
#   file / folder   普通路径（是不是目录在 normalize 里就定了）
#   other  认不出来的：不认识的选项、取值不够的选项、-- 之后的字面量
#
# 保留元组形态（而不是 NamedTuple）：repr 紧凑、doctest 与调试输出都不用改；而字段名
# 由 match 的 value pattern 给（`case ('opt', flag, field, values)`），够用了。
OptionField: TypeAlias = Literal[
    'forceReuseWindow',
    'forceNewWindow',
    'addMode',
    'diffMode',
    'mergeMode',
    'wait',
]

OptToken: TypeAlias = tuple[Literal['opt'], str, OptionField, list[str]]
GotoToken: TypeAlias = tuple[Literal['goto'], str, str, str | None]
GotoTarget: TypeAlias = tuple[str, str, str | None]     # 跳转目标本身（不带 'goto' 标签）：
                                                       # goto_target / emit['goto'] 吃这个
FileToken: TypeAlias = tuple[Literal['file'], str]
FolderToken: TypeAlias = tuple[Literal['folder'], str]
OtherToken: TypeAlias = tuple[Literal['other'], str]

Token: TypeAlias = OptToken | GotoToken | FileToken | FolderToken | OtherToken
ArgToken: TypeAlias = GotoToken | FileToken | FolderToken    # arg_token 只产这三种


# 认识的参数：flag -> (field, arity)
# flag:  命令行选项
# field: 报文字段
# arity: 取值个数（0 = 开关，不带值）
#
# -g / --goto 不在这里：它们只是"下一个参数是跳转目标"的提示，而 edit 对任何
# 文件:行号 参数本来就跳转，所以直接忽略（见 normalize）。内联写法 --goto=X / -g=X
# 也不特判：上游自己都不认那种写法，所以跟别的"不认识的选项"一样原样交给 CLI。
OPTIONS: dict[str, tuple[OptionField, int]] = {
    '-r': ('forceReuseWindow', 0), '--reuse-window': ('forceReuseWindow', 0),
    '-n': ('forceNewWindow', 0), '--new-window': ('forceNewWindow', 0),
    '-a': ('addMode', 0), '--add': ('addMode', 0),
    '-d': ('diffMode', 0), '--diff': ('diffMode', 0),
    '-m': ('mergeMode', 4), '--merge': ('mergeMode', 4),
    '--wait': ('wait', 0), '-w': ('wait', 0),
}

# 这几个选项要"有东西可开"才有意义（-a 要把目录加进工作区、-d 要 diff 两个文件、
# --wait 至少要等一个文件）。空着交给 CLI 只会发个空报文、或让 vim 系开个空编辑器，
# 所以 main 里直接提示退出。裸调用与 -r / -n 不在此列 —— 那些对 code 系有定义
# （开窗口 / 复用窗口 / 新窗口）
#
# 别把它改成 OPTIONS 的 arity：arity 是"这个选项自己吃几个取值"，而 -d / -a 的文件
# 是位置参数 —— CLI 自己的声明里 diff 就是 type:"boolean"，args:["file","file"] 只是
# help 占位符（实测 `a b -d`、`-d a -r b` 它都认）。写成 arity 2 会把这两类打回 CLI，
# 而且"取值不够"的既定行为是交回 CLI、不是报错，报错还得在这儿单独判
NEEDS_TARGET: tuple[OptionField, ...] = ('addMode', 'diffMode', 'wait')


def arg_token(a: str) -> ArgToken:
    """一个普通参数 -> token：位置参数那套判断（跳转目标 / 目录 / 文件）

    行号只认这种写法，所以 parse_goto 是"是否跳转"的唯一裁判。

    >>> arg_token('no-such-file.py:12')
    ('goto', 'no-such-file.py', '12', None)
    >>> arg_token('no-such-file.py')
    ('file', 'no-such-file.py')
    >>> arg_token('/tmp')
    ('folder', '/tmp')
    """

    goto = parse_goto(a)

    if goto:
        return ('goto',) + goto

    if os.path.isdir(a):
        return ('folder', a)

    return ('file', a)


def normalize(args: list[str]) -> list[Token]:
    """命令行 -> token 列表：只扫一次，后面两个翻译后端都吃它

    产出的 token 形状见上面的 `Token` 别名（元组，只有那 5 种）。

    -g / --goto 只是"下一个参数是跳转目标"的提示，而 edit 对任何带行号的参数本来就置
    gotoLineMode，所以它们被忽略、也不消费参数 —— 后面那个参数自己按位置参数处理
    （所以 `-g -r f:3` 里 -r 仍然是选项，不是"-g 的取值"）。

    内联写法（--goto=X / -g=X）不特判：上游自己也不认这种写法（实测 `buddycn
    --goto=f:3` 把取值当布尔丢了、`-g=f:3` 把取值塞进 gotoLineMode 字段，两者都没有
    文件），所以它们跟别的"不认识的选项"一样整成 ('other', 原文) 交给 CLI。

    认不出来的一律整成 ('other', 原文) 而不是丢掉：socket 后端见它就交回 CLI，
    CLI 后端原样吐回去 —— 顺序和原文一字不改，因为回退时交给 CLI 的就是它。

    >>> normalize(['-r', 'a.txt'])
    [('opt', '-r', 'forceReuseWindow', []), ('file', 'a.txt')]
    >>> normalize(['--wait'])
    [('opt', '--wait', 'wait', [])]
    >>> normalize(['a.txt:3'])
    [('goto', 'a.txt', '3', None)]
    >>> normalize(['/tmp'])
    [('folder', '/tmp')]
    >>> normalize(['-g', 'a.txt:3:4'])       # -g 被忽略，取值按位置参数走
    [('goto', 'a.txt', '3', '4')]
    >>> normalize(['-g'])                    # 没取值：选项被忽略
    []
    >>> normalize(['-g', '-r', 'a.txt:3'])   # -g 不消费参数，-r 仍是选项
    [('opt', '-r', 'forceReuseWindow', []), ('goto', 'a.txt', '3', None)]
    >>> normalize(['--goto=-r'])             # 内联写法当不认识的选项
    [('other', '--goto=-r')]
    >>> normalize(['-m', 'a', '-r', 'b'])    # 取值不够 / 取值又是个选项
    [('other', '-m'), ('file', 'a'), ('opt', '-r', 'forceReuseWindow', []), ('file', 'b')]
    >>> normalize(['--', 'a.txt:3'])         # -- 之后按字面量
    [('other', '--'), ('other', 'a.txt:3')]
    """

    out: list[Token] = []
    literal = False
    i = 0

    while i < len(args):
        a = args[i]
        i += 1

        if literal:
            out.append(('other', a))
            continue

        if a == '--':
            literal = True
            out.append(('other', a))
            continue

        if a in ('-g', '--goto'):
            continue                    # 提示而已：不产出 token，也不消费参数

        if a.startswith('-'):
            spec = OPTIONS.get(a)

            if not spec:
                out.append(('other', a))
                continue

            field, arity = spec
            values = args[i:i + arity]

            if len(values) < arity or any(v.startswith('-') for v in values):
                out.append(('other', a))     # 取值不够 / 取值又是个选项
                continue

            i += arity
            out.append(('opt', a, field, values))
            continue

        out.append(arg_token(a))

    return out


def has_wait(tokens: list[Token]) -> bool:
    """token 里有没有 --wait / -w（-- 之后的不算：normalize 已把它整成 other）

    >>> has_wait(normalize(['--wait', 'a.txt']))
    True
    >>> has_wait(normalize(['-w', 'a.txt']))
    True
    >>> has_wait(normalize(['a.txt']))
    False
    >>> has_wait(normalize(['--', '--wait']))
    False
    """

    return any(t[0] == 'opt' and t[2] == 'wait' for t in tokens)

# CLI 等 marker 的轮询间隔（server-cli.js 就是 1 秒一问）
WAIT_MARKER_INTERVAL = 1.0


def make_marker():
    """给 --wait 造一个空 marker，返回路径；造不出来返回 None

    和 CLI 一个做法（server-cli.js 的 createWaitMarkerFile）：mkstemp 一个空
    文件，路径随报文交给窗口，窗口在编辑器里那个文件被关掉时删掉它。
    """

    try:
        fd, path = tempfile.mkstemp(prefix='edit-wait-')
    except OSError:
        return None

    os.close(fd)

    return path


def remove_marker(path):
    """删 marker；没有、或删不掉都算了（它只是个哨兵）"""

    if not path:
        return

    try:
        os.unlink(path)
    except OSError:
        pass


def wait_marker(path, interval=WAIT_MARKER_INTERVAL):
    """等窗口把 marker 删掉 —— 也就是等那个文件在编辑器里被关掉

    CLI 就是这么等的（server-cli.js：while (existsSync(marker)) sleep(1s)），
    轮询间隔照抄。被 Ctrl-C 打断时先把 marker 删掉再抛出：窗口那边还开着文件，
    留着它既没用也白占 /tmp。

    >>> wait_marker('/no-such-marker')      # 已经没了：立刻返回
    """

    try:
        while os.path.exists(path):
            time.sleep(interval)
    except KeyboardInterrupt:
        remove_marker(path)
        raise

def open_request(args, marker=None):
    """把命令行参数翻译成 socket 直连要发的 open 报文；翻不了返回 None

    翻不了就交回 CLI：未知选项 / -- / 取值不够 / 没给参数。
    目录进 folderURIs，文件进 fileURIs，:行号[:列] 交给 parse_goto 认。

    （-a / -d / --wait 空着的情况走不到这里：main 见到 NEEDS_TARGET 里那几项没有
    目标就直接提示退出了。）

    -g / --goto 被忽略（见 normalize）：行号只认位置参数写法，所以 `-g f:3` 与 `f:3`
    发出的是同一份报文。内联写法 --goto=X / -g=X 不算"忽略"、也不特判：它们跟别的
    不认识的选项一样整成 ('other', 原文)，于是这里返回 None（交回 CLI）。

    -m / --merge 认 4 个取值（path1 path2 base result）：原样进 fileURIs 并置
    mergeMode。少一个、或某个取值又是个选项，都交回 CLI。

    --wait / -w 要带 marker（make_marker() 造的那个空文件路径）：带上就直连等
    窗口删它，没带就交回 CLI——CLI 自己会造一个。和 CLI 一样，--wait 必须至少
    带一个文件，只给目录它不认。

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
    >>> open_request(['--wait', '/no-such-dir/x.py'], '/m')['waitMarkerFilePath']
    '/m'
    >>> open_request(['-w', '/no-such-dir/x.py'], '/m')['waitMarkerFilePath']
    '/m'
    >>> open_request(['--wait', '/no-such-dir/x.py']) is None     # 没 marker
    True
    >>> open_request(['--wait', '/']) is None       # --wait 只给目录，CLI 也不认
    True
    >>> open_request(['-g', '/no-such-dir/x.py:3'])['fileURIs']    # -g 忽略，值照位置参数走
    ['file:///no-such-dir/x.py:3']
    >>> open_request(['--goto', '/no-such-dir/x.py:3'])['gotoLineMode']
    True
    >>> open_request(['--goto=/no-such-dir/x.py:3:5']) is None   # 内联写法不特判
    True
    >>> open_request(['-r', '-g', '/no-such-dir/x.py:3'])['forceReuseWindow']
    True
    >>> open_request(['-g', '/no-such-dir/x.py'])['gotoLineMode']   # 没行号：普通文件
    False
    >>> open_request(['-g', '/'])['folderURIs']                     # 目录照样分开
    ['file:///']
    >>> open_request(['--goto=']) is None                           # 空值：忽略
    True
    >>> open_request(['-m', '/a', '/b', '/base', '/result'])['mergeMode']
    True
    >>> open_request(['--merge', '/a', '/b', '/base', '/result'])['fileURIs']
    ['file:///a', 'file:///b', 'file:///base', 'file:///result']
    >>> open_request(['-r', '-m', '/a', '/b', '/base', '/result'])['forceReuseWindow']
    True
    >>> open_request(['-m', '/a', '/b', '/base']) is None        # 少一个
    True
    >>> open_request(['-m', '/a', '-r', '/base', '/result']) is None  # 取值又是个选项
    True
    >>> open_request(['-g']) is None                        # 选项被忽略，没东西可开
    True
    >>> open_request(['-g', '-r']) is None                  # 只剩 -r：还是没东西可开
    True
    >>> open_request([]) is None
    True
    """

    return to_msg(normalize(args), marker)


def nothing_to_open(tokens):
    """一个"要打开的东西"都没有：没有文件 / 目录 / 跳转目标，也没有 -m 那类带取值的选项

    认不出来的 token（('other', …)）算"有东西"—— 它们会原样交给 CLI 去理解，没法断定
    用户没给目标（`--` 之后的字面量就在里面）。main 拿它配 NEEDS_TARGET 用。

    >>> nothing_to_open(normalize(['-d']))
    True
    >>> nothing_to_open(normalize([]))
    True
    >>> nothing_to_open(normalize(['-d', 'a.txt']))
    False
    >>> nothing_to_open(normalize(['-m', 'a', 'b', 'base', 'res']))   # 取值就是路径
    False
    >>> nothing_to_open(normalize(['--', 'a.txt']))                   # 认不出的算有东西
    False
    """

    for t in tokens:
        if t[0] == 'other' or t[0] in ('file', 'folder', 'goto'):
            return False

        if t[0] == 'opt' and t[3]:          # 带取值的选项（-m 的 path1..result）
            return False

    return True


# open 报文的形状（字段名是上游 CLI 的；报文示例见 NOTES 开头那段）。
# waitMarkerFilePath 只在带 --wait 且造出 marker 时才出现 —— 用 total=False 继承表达
# "选填"（typing.NotRequired 是 3.11+，不引 typing_extensions）
class _OpenMsgBase(TypedDict):
    type: Literal['open']
    fileURIs: list[str]
    folderURIs: list[str]
    diffMode: bool
    mergeMode: bool
    addMode: bool
    gotoLineMode: bool
    forceReuseWindow: bool
    forceNewWindow: bool


class OpenMsg(_OpenMsgBase, total=False):
    waitMarkerFilePath: str


def to_msg(tokens: list[Token], marker: str | None = None) -> OpenMsg | None:
    """token -> open 报文（socket 后端）

    见到 ('other', …) 就返回 None —— 交回 CLI：认不出来的我们不猜，让 CLI 自己
    去解释。--wait 没造出 marker 同理（CLI 自己会造一个）。

    >>> to_msg(normalize(['/no-such-dir/a.txt:3']))['fileURIs']
    ['file:///no-such-dir/a.txt:3']
    >>> to_msg(normalize(['-m', 'a', 'b', 'base', 'result']))['mergeMode']
    True
    >>> to_msg(normalize(['--wait', 'a.txt']), '/m')['waitMarkerFilePath']
    '/m'
    >>> to_msg(normalize(['--wait', 'a.txt'])) is None        # 没 marker
    True
    >>> to_msg(normalize(['/']))['folderURIs']
    ['file:///']
    >>> to_msg(normalize(['--', 'a.txt'])) is None            # 认不出来
    True
    >>> to_msg([]) is None                                  # 没东西可开
    True
    """

    msg: OpenMsg = {
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

    for t in tokens:
        match t:
            case ('other', _):
                return None                 # 认不出来：交回 CLI

            case ('file', path):
                msg['fileURIs'].append(file_uri(path))

            case ('folder', path):
                msg['folderURIs'].append(file_uri(path))

            case ('goto', file, line, col):
                msg['fileURIs'].append(file_uri(file, line, col))
                msg['gotoLineMode'] = True

            case ('opt', _flag, field, values):
                if field == 'wait':
                    if not marker:
                        return None         # 没造 marker：交回 CLI（它自己造）

                    msg['waitMarkerFilePath'] = marker
                    continue

                msg[field] = True           # field 已窄化成剩下那 5 个开关

                for v in values:
                    msg['fileURIs'].append(file_uri(v))

            case _:
                raise AssertionError(t)     # Token 是穷尽的：漏一种形状就在这儿炸出来

    if marker and not msg['fileURIs']:
        return None                         # CLI 要求 --wait 至少带一个文件

    if not msg['fileURIs'] and not msg['folderURIs']:
        return None                         # 没东西可开：保持 CLI 原来的行为

    return msg


def goto_inline(flag: str) -> Callable[[GotoTarget], list[str]]:
    """inline 形状：跳转目标与路径是同一个串（`--goto f:3:5`）

    >>> goto_inline('--goto')(('a.txt', '12', '3'))
    ['--goto', 'a.txt:12:3']
    """

    return lambda goto: [flag, goto_target(goto)]


def goto_plus(sep: str | None) -> Callable[[GotoTarget], list[str]]:
    """plus 形状：`+行号[sep列号]` 放在文件名前（vim / nano / emacs）

    `sep` 是列号的分隔符 —— vim 不支持列（`sep=None`，只用 `+行号`），nano 是 `,`，
    emacs 系是 `:`。列号两家都是 1 起（emacs 29.4 实测 `+3:5` 的光标落在 0 起第 4
    列；nano 的 man 写"默认是 line 1, column 1"），和我们自己的 `文件:行号:列` 一致，
    拼接不用 ±1；没给列号就只有 `+行号`。

    >>> goto_plus(None)(('a.txt', '12', '3'))        # vim：列号用不上，丢掉
    ['+12', 'a.txt']
    >>> goto_plus(',')(('a.txt', '12', '3'))         # nano
    ['+12,3', 'a.txt']
    >>> goto_plus(':')(('a.txt', '12', '3'))         # emacs 系
    ['+12:3', 'a.txt']
    >>> goto_plus(':')(('a.txt', '12', None))        # 没给列
    ['+12', 'a.txt']
    """

    return lambda goto: ['+' + goto[1] + (sep + goto[2] if sep and goto[2] else ''),
                         goto[0]]


def goto_file(goto: GotoTarget) -> list[str]:
    """认不出是哪一类：只传文件，行号丢掉

    不知道对面认不认 `文件:行号`，把 `f:3` 当文件名递过去可能什么都打不开，所以只
    留文件。注意它**不是** inline 形状（`goto_inline` 会把行号一起带上）。

    >>> goto_file(('a.txt', '12', '3'))
    ['a.txt']
    """

    return [goto[0]]


class EmitRow(TypedDict):
    """EMIT 表的一行：goto 是"跳转目标 -> 片段"，其余项是"这个开关认不认"

    TypedDict 而不是普通 dict：不然 mypy 只知道值是 object，连 emit['goto'] 可不可
    调用都判不了（`--check-untyped-defs` 实测报 "object not callable"）。
    """

    goto: Callable[[GotoTarget], list[str]]
    wait: bool
    forceReuseWindow: bool
    forceNewWindow: bool
    addMode: bool
    diffMode: bool
    mergeMode: bool
    abspath: bool


# 每个 kind 怎么把 token 翻译成命令行 —— "针对不同程序翻译"就这一张表：
#   goto   : 吃一个跳转目标 (文件, 行号, 列号) -> 片段列表（一个目标一次，多目标就
#            多份 —— 实测 CLI 的 -g 可以重复，报文是累加的）。三种形状各是一个函数：
#            goto_inline（目标与路径同一个串）/ goto_plus（+N 放文件名前）/
#            goto_file（认不出：只留文件）
#   那 6 个开关（键就是 token 的 field 名：wait / forceReuseWindow /
#   forceNewWindow / addMode / diffMode / mergeMode）
#          : 这类 CLI 认不认这个 VS Code 系开关。认就原样递过去，不认就摘掉
#            （mergeMode 例外：摘开关、留它的取值）。**一项对一个选项，不共用** ——
#            这几个短选项在别的 CLI 里各有别解，每项的注释就是实测记录。
#            键名与 token 的 field 同名是刻意的：to_argv 里 emit[field] 直接查表
#   abspath: 存在的路径转不转绝对（remote-cli 是代理，相对路径未必按 cwd 解释）
EMIT: dict[str, EmitRow] = {
    CLI_KIND_CODE: {
        'goto': goto_inline('--goto'),
        'wait': True,
        'forceReuseWindow': True,
        'forceNewWindow': True,
        'addMode': True,
        'diffMode': True,
        'mergeMode': True,
        'abspath': True,
    },
    CLI_KIND_VIM: {
        'goto': goto_plus(None),        # vim -g 是启动 GUI（E25 退出 2），绝不能透传
        'wait': False,                  # -w 是把键入的命令写进 scriptout
        'forceReuseWindow': False,      # -r 是列/恢复交换文件
        'forceNewWindow': False,        # -n 是不用交换文件
        'addMode': False,               # -a 是未知选项：Unknown option argument
        'diffMode': True,               # -d 正是 diff 模式（vimdiff），等价，保留
        'mergeMode': False,             # -m 是禁止写文件
        'abspath': False,
    },
    CLI_KIND_NANO: {
        'goto': goto_plus(','),         # nano -g 是 --showcursor
        'wait': False,                  # 没有 --wait
        'forceReuseWindow': False,      # -r <数字>：把文件名当填充宽度
        'forceNewWindow': False,        # -n 是 --noread：只写不读
        'addMode': False,               # -a 是 --atblanks
        'diffMode': False,              # -d 是 --rebinddelete
        'mergeMode': False,             # -m 是 --mouse
        'abspath': False,
    },
    CLI_KIND_EMACS: {
        'goto': goto_plus(':'),         # emacs -g 是 --geometry，会吃掉文件名
        'wait': False,                  # emacsclient 的 -w 是 --timeout=SECONDS
        'forceReuseWindow': False,      # emacs -r 是 -rv 反色；emacsclient -r 是 --reuse-frame
        'forceNewWindow': False,        # emacs 报未知选项；emacsclient -n 是 --no-wait
        'addMode': False,               # 报未知选项（emacsclient 的 -a 还要参数）
        'diffMode': False,              # -d 是 --display，会吃掉文件名
        'mergeMode': False,             # 报未知选项（emacsclient 也不认）
        'abspath': False,
    },
}


def to_argv(tokens: list[Token], kind: str | None) -> list[str]:
    """token -> 交给 CLI 的参数（CLI 后端，按 kind 查 EMIT）

    >>> to_argv(normalize(['a.txt:12']), CLI_KIND_CODE)      # 插 --goto
    ['--goto', 'a.txt:12']
    >>> to_argv(normalize(['a.txt:12', 'b.txt:9']), CLI_KIND_CODE)  # 一个目标一份
    ['--goto', 'a.txt:12', '--goto', 'b.txt:9']
    >>> to_argv(normalize(['a.txt:12']), CLI_KIND_VIM)       # +行号 放文件前
    ['+12', 'a.txt']
    >>> to_argv(normalize(['a.txt:12']), None)               # 认不出：只传文件
    ['a.txt']
    >>> to_argv(normalize(['-r', 'a.txt:12']), CLI_KIND_CODE)  # 就地成对插
    ['-r', '--goto', 'a.txt:12']
    >>> to_argv(normalize(['-g', 'a.txt:12']), CLI_KIND_CODE)  # -g 被忽略，仍插 --goto
    ['--goto', 'a.txt:12']
    >>> to_argv(normalize(['-g', 'a.txt:12']), CLI_KIND_VIM)   # vim 不认 -g：翻成 +行号
    ['+12', 'a.txt']
    >>> to_argv(normalize(['--goto=a.txt:12']), CLI_KIND_VIM)  # 内联写法：原样给 CLI
    ['--goto=a.txt:12']
    >>> to_argv(normalize(['-g', 'a.txt']), CLI_KIND_VIM)      # 取值没行号：只剩文件
    ['a.txt']
    >>> to_argv(normalize(['a.txt:3', '-g', 'b.txt:9']), CLI_KIND_VIM)  # 两个都翻
    ['+3', 'a.txt', '+9', 'b.txt']
    >>> to_argv(normalize(['--wait', 'a.txt']), CLI_KIND_CODE)
    ['--wait', 'a.txt']
    >>> to_argv(normalize(['--wait', 'a.txt']), CLI_KIND_VIM)  # vim 没有 --wait
    ['a.txt']
    >>> to_argv(normalize(['-m', 'a', 'b', 'base', 'result']), CLI_KIND_CODE)
    ['-m', 'a', 'b', 'base', 'result']
    >>> to_argv(normalize(['-m', 'a', 'b', 'base', 'result']), CLI_KIND_VIM)  # 丢开关，留路径
    ['a', 'b', 'base', 'result']
    >>> to_argv(normalize(['-d', 'a', 'b']), CLI_KIND_VIM)    # vim -d 正是 diff 模式
    ['-d', 'a', 'b']
    >>> to_argv(normalize(['-d', 'a', 'b']), CLI_KIND_NANO)   # nano -d 是 --rebinddelete
    ['a', 'b']
    >>> to_argv(normalize(['-r', 'a']), CLI_KIND_VIM)         # vim -r 是恢复交换文件
    ['a']
    >>> to_argv(normalize(['--', 'a.txt:12']), CLI_KIND_CODE)  # -- 之后原样
    ['--', 'a.txt:12']
    """

    unknown: EmitRow = {
        'goto': goto_file,              # 认不出是哪一类：只传文件，行号丢掉
        'wait': False,
        'forceReuseWindow': False,
        'forceNewWindow': False,
        'addMode': False,
        'diffMode': False,
        'mergeMode': False,
        'abspath': False,
    }

    emit = unknown if kind is None else EMIT.get(kind, unknown)
    out: list[str] = []

    for t in tokens:
        match t:
            case ('other', orig):
                out.append(orig)            # 认不出来的原样透传

            case ('file' | 'folder', path):
                out.append(path)

            case ('goto', file, line, col):
                out.extend(emit['goto']((file, line, col)))

            case ('opt', flag, field, values):
                # 这几个开关是 VS Code 系独有的"打开方式"，别的 CLI 拿到各有别解
                # （逐项见 EMIT 里那几行注释）：不认就摘掉。EMIT 的键与 field 同名，
                # 所以这里直接查表 —— 加一个开关只需要往 EMIT 那几行里加一项。
                if not emit[field]:
                    if field == 'mergeMode':
                        out.extend(values)  # 合并没有等价物：丢开关，四个路径照开
                    continue

                out.append(flag)
                out.extend(values)

            case _:
                raise AssertionError(t)     # Token 是穷尽的：漏一种形状就在这儿炸出来

    if emit['abspath']:
        out = [os.path.abspath(a) if os.path.exists(a) else a for a in out]

    return out


def cli_argv(args: list[str], kind: str | None) -> list[str]:
    """命令行 -> 交给 CLI 的参数（normalize + to_argv，测试走这个缝）"""

    return to_argv(normalize(args), kind)


def socket_open(sock, msg, timeout=3.0):
    """把 open 报文发给窗口，返回 (ok, 详情)

    判据和 CLI 一致：只认 HTTP 200（CLI 就是 JSON.parse 之后看 statusCode）。
    详情是回复正文，失败时正好拿来当错误信息。
    """

    raw = socket_request(sock, msg, timeout)
    if not raw:
        return False, '连不上或超时'

    code = http_code(raw)
    body = http_body(raw).strip()

    return code == 200, body or ('HTTP %s' % code)

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

    tag 形如 'edit --list'、'edit --interactive'，只用来拼错误信息。
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

def socket_number(line):
    """fzf 选中的那一行 -> 编号字符串（喂给 pick_socket）；认不出返回 ''

    format_sockets 的行首是 '*' 或编号，所以取第一个数字就行；
    认不出时返回 ''，好让调用方去走编号输入那条路（'' 在 pick_socket 里
    是"回车 = 当前窗口"，不能当"没选中"用）。

    >>> socket_number('  2  /run/a.sock buddycn /w/proj')
    '2'
    >>> socket_number('* 2  /run/a.sock buddycn /w/proj')
    '2'
    >>> socket_number('  #   socket pid cli workspace')     # 表头行
    ''
    >>> socket_number('')
    ''
    """

    for tok in line.split():
        if tok == '*':
            continue

        return tok if tok.isdigit() else ''

    return ''


def use_fzf():
    """挑窗口时该不该用 fzf：没被关掉、有 fzf、且 stdin 是 tty

    stdin 不是 tty 就不用（printf '3\\n' | edit --interactive 是脚本用法，
    而且 fzf 要独占终端）；EDIT_FZF=0 / off / never 显式关掉。
    不写 doctest：它看的是当前终端和 PATH。
    """

    if os.environ.get(EDIT_FZF, '') in ('0', 'off', 'never'):
        return False

    return sys.stdin.isatty() and bool(shutil.which('fzf'))


def fzf_pick(socks):
    """用 fzf 挑一个窗口：返回候选项；没选中 / 认不出 / 拉不起来就返回 None

    候选行喂给 fzf 的 stdin，它的 UI 走自己的 stderr（继承终端）—— 我们的
    stdout 要留给 --init 的初始化片段，不能让选择器写进来；选中项从 fzf 的
    stdout 读。没选中（Esc / Ctrl-C）和拉不起来都返回 None，由 ask_socket
    落到编号输入那条路。
    """

    lines = format_sockets(socks, current_socket())

    try:
        # --header-lines=1：表头那行固定住，不参与过滤
        proc = subprocess.run(['fzf', '--prompt=窗口> ', '--height=40%',
                               '--layout=reverse', '--header-lines=1'],
                              input='\n'.join(lines) + '\n',
                              stdout=subprocess.PIPE, text=True)
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode != 0:
        return None

    n = socket_number(proc.stdout)
    if not n:
        return None

    return pick_socket(socks, n)


def ask_socket(socks):
    """列出候选并让用户挑一个，返回候选项

    候选和提示都写 stderr：stdout 要留给最终的初始化片段，这样
    `edit --init fish --interactive | source` 才不会被提示语打断。
    有 hook 时（= 当前终端连着某个窗口）回车表示那个窗口；没有 hook 就没有
    当前窗口，只能输编号。q / EOF / 认不出的输入都算取消。

    --init 之外也能挑（edit --interactive <文件>）：挑完由 main 把 socket
    写回环境，之后打开文件就走那个窗口。

    有 fzf 时先用它（use_fzf()）：它的 UI 走 stderr，不碰留给片段的 stdout。
    它没选中就落回下面这套编号输入 —— 所以两种挑法的行为是一致的。
    """

    current = current_socket()

    if use_fzf():
        picked = fzf_pick(socks)
        if picked:
            return picked

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
        sys.exit('edit --interactive: 没读到编号（stdin 已结束）')

    chosen = pick_socket(socks, answer, current)
    if not chosen:
        sys.exit('edit --interactive: 没有选中窗口')

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

    # 命令行只扫一次：socket 后端吃 to_msg，CLI 后端吃 to_argv（纯函数，先扫出来）
    tokens = normalize(args)

    # -a / -d / --wait 要"有东西可开"才有意义（要目录 / 要两个文件 / 至少要一个文件）：
    # 空着交给 CLI 只会发个空报文，或让 vim 系开个空编辑器。裸调用与 -r / -n 不拦 ——
    # 那些对 code 系是有定义的（开窗口 / 复用窗口 / 新窗口）。放在挑窗口之前，免得
    # --interactive 让用户白挑一次
    if nothing_to_open(tokens) and any(
            t[0] == 'opt' and t[2] in NEEDS_TARGET for t in tokens):
        sys.exit('edit: %s 后面没有文件或目录' % ' / '.join(
            t[1] for t in tokens if t[0] == 'opt' and t[2] in NEEDS_TARGET))

    # --interactive：先挑窗口。挑完把 socket 写回环境，后面所有 current_socket()
    # 就都指向它 —— 直连、--init 的默认值、以及回退时 CLI 继承的环境，全都跟着走，
    # 那四个调用点一行都不用改
    chosen = None

    if flags.interactive:
        if not flags.init and not args:
            sys.exit('edit --interactive: 要带文件（挑完窗口就打开它）；'
                     '只要初始化片段请用 edit --init <shell> --interactive')

        if not flags.init and flags.list:
            sys.exit('edit --interactive 和 edit --list 冲突'
                     '（挑窗口时它自己会把窗口列出来）')

        chosen = ask_socket(load_sockets('edit --interactive'))
        redirect_socket(chosen['sock'])

    if flags.init:
        if args:
            sys.exit('edit --init 不接受文件参数')

        if flags.list:
            sys.exit('edit --init 和 edit --list 冲突（挑窗口请用 --interactive）')

        if chosen:
            # 列出候选（stderr）挑一个，用它的 hook 和 CLI 目录输出片段
            # cli 读不到时（别人的进程，权限不够）退回按安装目录推
            cli_dir = (os.path.dirname(chosen['cli']) or
                       os.path.join(chosen['install'], 'bin', 'remote-cli'))

            if not os.path.isdir(cli_dir):
                # print_init_script 取不到值就静默不输出，所以这里先判一次
                sys.exit('edit --init --interactive: {} 不是目录（换个窗口试试）'.format(cli_dir))

            print_init_script(flags.init, chosen['sock'], cli_dir)
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
    # 翻不了（认不出 / 取值不够）或发失败，就交给下面的 CLI 路径
    sock = current_socket()

    # --wait 要先造 marker（窗口关文件时删它），造不出来就交回 CLI
    marker = make_marker() if sock and has_wait(tokens) else None
    msg = to_msg(tokens, marker) if sock else None

    if msg:
        if flags.dry_run:
            print('socket %s %s' % (sock, json.dumps(msg, ensure_ascii=False)))
            remove_marker(marker)       # 没真发出去，别把临时文件留在 /tmp
            return

        ok, detail = socket_open(sock, msg)

        if ok:
            if marker:
                wait_marker(marker)     # 等窗口删 marker（= 等文件被关掉）
            return

        sys.stderr.write('edit: socket 打不开（%s），改用 CLI\n' % detail)

    # 走到这儿是要交回 CLI 了：它自己会造 marker，我们这个得收回去
    remove_marker(marker)

    cli = find_cli()
    if not cli:
        sys.exit('找不到 cli（%s）' % ' / '.join(CODE_LIKE + VIM_LIKE))

    # cli 是 argv 列表：[可执行文件, 自己配置里的参数...]（如 EDITOR='vim -u NONE'）
    kind = cli_kind(cli[0])
    argv = cli + to_argv(tokens, kind)     # 按 kind 翻译（EMIT 表）

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
