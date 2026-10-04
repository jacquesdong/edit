#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""edit <文件...> —— 在当前 IDE 窗口打开文件

用法：
  edit <文件...>               在当前 IDE 窗口打开文件
  edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
  edit --wait <文件>           等文件在编辑器里被关掉才返回（当 $EDITOR / core.editor 用）
  edit <链接...>               参数像链接（带 :// 或 mailto: / tel:）就交给浏览器打开，
                               不走编辑器；file:// 除外，当本地文件路径处理（vim 同款）
                               —— shell 里记得给带 & 的链接加引号
  edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
  eval "$(edit --init bash)"   同上（bash / sh / dash）

  EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
  edit --list                  列出存活的 IDE 窗口（最新的排最前；只读、不读 stdin，
                               会问各窗口 workspace）
  edit --first <文件>          没有 hook 时也开在窗口里：取 --list 的第一个（也就是最新的
                               那个），不提问、不读 stdin（要自己挑用 --interactive）
  edit --prune                 清掉死掉的 vscode-ipc socket（没人 bind 的那些；
                               只删 $XDG_RUNTIME_DIR / $TMPDIR / hook 所在目录里的，
                               挨个打印它的创建时间和路径；--dry-run 只看不删）
  edit --usage                 打印这份用法说明（--help 是透传给 IDE CLI 的）
  特殊用法：EDIT_DEBUG=realpath 时，--debug 日志里 [文件:行 #函数] 的"文件"部分显示为
  绝对真实路径（解析符号链接），默认只显示文件名（如 edit.py:123）。EDIT_DEBUG 同时还是
  debug 的开关（空 / 0 / false / off / no / n / never 都算关），realpath 之外的任何值
  都回落到文件名。
  edit --debug                 把吞掉的失败原因（socket 连不上 / 超时 / 被拒…）
                               打到 stderr；EDIT_DEBUG=1 等价，空 / 0 / false / f /
                               off / no / n / never 都算关（EDIT_FZF 同一套）
  edit --color[=always|never]  给输出上色（窗口表的表头和当前窗口那颗 *、--debug
                               日志的时间戳与 <D>/<E>）；不传=auto：只在这条流是终端
                               时才上色，TERM=dumb 或设了 NO_COLOR 就不上色。
                               --list 看 stdout、提示与日志看 stderr，各判各的；
                               省略取值=always（强制，如 edit --list --color=always
                               | less -R）。EDIT_COLOR 认同样的三个值（edit 被当
                               $EDITOR 调起时用）；auto 下还认 FORCE_COLOR（非空且
                               不是 0/false 就强制上色）。注意裸 --color 后面不能
                               直接跟文件：argparse 会把文件名当它的取值，那种写法
                               要写成 edit --color=always <文件>

  edit --init fish --interactive   列出窗口并挑一个，输出它的初始化片段
                                   （普通终端里没有 hook 时用这个）
  edit --interactive <文件...>     列出窗口并挑一个，在挑中的那个里打开文件
                                   （普通终端里没有 hook、又想指定窗口时用这个）
                                   （装了 fzf 就用它挑；EDIT_FZF=0 关掉，改输编号 ——
                                   关的值同 --debug：空 / 0 / false / off / no / n / never）

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
  result），不足 4 个由 normalize 抛 NormalizeError 报错。
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

链接走的是另一种报文：{"type":"openExternal","uris":[…]}（remote-cli 的
--openExternal 就是它，IDE 的 browser.sh 也是这么开网页的）。链接不是文件 ——
塞进 fileURIs 会变成 file:///当前目录/https:/… 这种东西，所以它自带一条路：
参数里像链接的（normalize 认 is_uri）原样当 uris 发出去，不认行号、不转绝对路径、
也不按 CLI 种类翻译；file:// 除外，decode 成路径后照常当本地文件（所以
`edit file://$PWD/README.md` 开的就是那个文件，:行号也照旧认）。直连不上时退回
两级：code 系 CLI 加 --openExternal（和直连是同一件事，只是要起一次 node），别的
CLI 就退 $BROWSER（fish 的 help 认的那个变量，可带参数）或 xdg-open —— BROWSER
写的是自己时跳过，免得没有窗口可直连时一圈圈 exec 回来。
"""

from __future__ import annotations       # 注解不求值：别名放哪都行，运行期也不构造它们

import argparse
import errno
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal, NamedTuple, NoReturn, TypeAlias, TypedDict

import logging

# 被吞掉的失败原因统一走它：logging 默认写 stderr，且不配 handler 时 debug 会被
# 丢掉，所以默认静默照旧，只有 --debug / EDIT_DEBUG=1（见 env_flag）才打得出来。
#
# 埋点约定 '<动作> <对象>: %r'（%r 自带 errno 和 strerror），且只记"低频、终端性"的
# 失败：/proc 扫描、lstat 竞态那种几百次的高频预期失败别逐条记，否则一开就刷屏。
#
# 带 exc_info 的只有 socket_request 一处：那个 try 覆盖 connect / sendall / recv 多个
# 调用点，栈的行号能定位到是哪一步；单调用点的栈只有自己一帧，加了纯粹是噪音。
logger = logging.getLogger(__name__)

# 日志格式：LOG_FORMAT_DEBUG 就是常规格式再挂一段 [文件:行号 函数] —— 排查那几条被
# 吞掉的失败时，最需要知道的正是"谁吞的"（file:line 也正好是终端里能点的形状）
TIME_FORMAT = '%(asctime)s.%(msecs)03d'
LOG_FORMAT = '{t} %(levelMark)s %(message)s'.format(t=TIME_FORMAT)
LOG_FORMAT_DEBUG = LOG_FORMAT + ' [%(filePath)s:%(lineno)d #%(funcName)s]'

# 着色版（--color 生效时才用）：时间戳与位置压暗、级别按"越严重越亮"上色、正文不着色。
# levelMark 由下面的 LevelMark 注入（连尖括号一起上色），所以两个版本都写 %(levelMark)s。
#
# 配色移植自 fixcomm-py c3ebf44（那边对齐 logback 的 LOG_CONSOLE_PATTERN），几条判据：
# - 时间戳/位置用 256 色灰 38;5;244：不用 faint（SGR 2）—— 它的实际灰度由终端主题决定，
#   有的主题下几乎看不见、有的又和正文一样亮
# - 级别阶梯 D 38;5;24 → I 38;5;65 → W 33 → E 31：不用 2;34 / 2;32，因为不少主题会
#   忽略 dim，退化成饱和 ANSI 色反而更亮；做成阶梯后级别一眼可分，正文仍是最亮的一档
# - 窗口表里当前窗口那颗 * 用亮黄：一行里唯一要跳出来的东西
# - funcName 用暗青 DIM_CYAN：与位置(GRAY)区分；logback 那边一行只有 logger.method 一处青，
#   edit 这里仅 debug 段有 funcName，沿用 client.py 同款色相。logger 名 %(name)s 不显示——
#   edit 是单模块脚本，logger 恒为 __main__/edit，染色纯噪音（同 client.py 移植时即有意省略）
GRAY      = '\x1b[38;5;244m'
DIM_BLUE  = '\x1b[38;5;24m'
DIM_GREEN = '\x1b[38;5;65m'
YELLOW    = '\x1b[33m'
RED       = '\x1b[31m'
DIM_CYAN  = '\x1b[2;36m'   # funcName 用暗青，与位置(GRAY)区分、与 client.py 一致
RESET     = '\x1b[0m'

LOG_FORMAT_COLOR = '{g}{t}{r} %(levelMark)s %(message)s'.format(t=TIME_FORMAT, g=GRAY, r=RESET)
LOG_FORMAT_COLOR_DEBUG = (
    LOG_FORMAT_COLOR
    + ' {g}[%(filePath)s:%(lineno)d {c}#%(funcName)s{r}{g}]{r}'.format(g=GRAY, c=DIM_CYAN, r=RESET)
)


class LevelMark(logging.Filter):
    """不做过滤，只往记录里注入 levelmark（形如 <D>），要上色时连尖括号一起上色

    尖括号在这里产出而不是写在格式串里，整块 <D> 才能一起上色、不留一对亮括号。
    不上色时也挂着它（color=False），于是两个格式串都用 %(levelMark)s，不必再分
    "有没有装这个 filter" —— 少一处能漏的分支。

    >>> r = logging.LogRecord('c', logging.WARNING, 'f', 1, 'm', None, None)
    >>> LevelMark(False).filter(r) and r.levelMark
    '<W>'
    >>> LevelMark(True).filter(r) and r.levelMark
    '\\x1b[33m<W>\\x1b[0m'
    >>> LevelMark(True).filter(r)          # 不过滤：返回 True，记录照常往下走
    True
    """

    COLORS = {
        logging.DEBUG: DIM_BLUE,
        logging.INFO: DIM_GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: '\x1b[1;31m',
    }

    def __init__(self, color: bool = False) -> None:
        super().__init__()

        self.color = color

    def filter(self, record):
        mark = '<{}>'.format(record.levelname[0])     # D / I / W / E / C

        if self.color:
            code = self.COLORS.get(record.levelno)
            if code:
                mark = code + mark + RESET

        record.levelMark = mark

        return True


class FilePath(logging.Filter):
    """不做过滤，只往记录里注入 filePath（debug 段 [文件:行 #函数] 里的"文件"部分）

    默认（choice 不是 'realpath'）用 record.filename —— 只显示文件名（如 edit.py），
    和原来的 %(filename)s 一致；choice='realpath' 时用 os.path.realpath(record.pathname)，
    显示绝对真实路径（解析符号链接）。choice 直接吃 EDIT_DEBUG 的原始值：所以
    EDIT_DEBUG=realpath 会同时打开 debug 并走真实路径，EDIT_DEBUG=1 / 空 / off 等
    都回落到文件名（realpath 之外的任何值都算文件名）。

    >>> r = logging.LogRecord('c', logging.DEBUG, '/a/b/edit.py', 5, 'm', None, None)
    >>> FilePath('realpath').filter(r) and r.filePath
    '/a/b/edit.py'
    >>> FilePath('').filter(r) and r.filePath
    'edit.py'
    >>> FilePath('1').filter(r) and r.filePath      # 误写也回落到文件名
    'edit.py'
    """
    def __init__(self, choice: str = '') -> None:
        super().__init__()

        self.resolve: Callable[[str], str] | None

        match choice:
            case 'realpath':
                self.resolve = os.path.realpath
            case _:
                self.resolve = None

    def filter(self, record):
        if self.resolve is not None:
            record.filePath = self.resolve(record.pathname)
        else:
            record.filePath = record.filename

        return True


def should_color(mode, stream):
    """--color 的三态落成"这条流上不上色"

    auto 才看环境，而且只看**这条流**：`edit --list > f` 时 stdout 不是终端，就不该
    把转义写进 f；同一时刻 stderr 可能还是终端，那边照旧上色。
    三条通用约定（与 fixcomm-py 751178a 同一套）：
      * FORCE_COLOR 非空且不是 0 / false —— 强制上色，压过下面全部；
        `0` / `false` 只表示"不强制"（等同没设），不是"强制关闭"，关闭请用 NO_COLOR
      * TERM=dumb（终端自称不支持）或压根没设 —— 不上色
      * NO_COLOR 设了且非空 —— 不上色（规范如此，空串不算）

    >>> import io
    >>> should_color('never', sys.stdout)      # 不管是不是终端
    False
    >>> should_color('always', io.StringIO())
    True

    auto 那几条要靠环境变量，doctest 里改真环境会漏出去，由 test_edit.py 的
    ColorTest 覆盖（那边能 patch.dict）。
    """

    if mode == COLOR_ALWAYS:
        return True

    if mode == COLOR_NEVER:
        return False

    force = os.environ.get('FORCE_COLOR', '')
    if force and force.lower() not in ('0', 'false'):
        return True                      # 显式强制：压过 isatty / TERM / NO_COLOR

    return (stream.isatty() and
            os.environ.get('TERM', 'dumb') != 'dumb' and
            not os.environ.get('NO_COLOR', ''))


def paint(text, code, colored):
    """给 text 套上色：不上色（或 text 为空）就原样返回

    空串别产出孤零零的一对转义 —— 那种看不见的垃圾最难排查。

    >>> paint('*', YELLOW, False)
    '*'
    >>> paint('*', YELLOW, True)
    '\\x1b[33m*\\x1b[0m'
    >>> paint('', YELLOW, True)
    ''
    """

    if not colored or not text:
        return text

    return code + text + RESET

# 显式点名用哪个 CLI 打开文件（命令名或路径，可带参数），挑 CLI 时优先级最高；
EDIT_CLI = 'EDIT_CLI'

# 挑窗口时不想用 fzf 就设成 ENV_OFF 那套（'' / 0 / false / off / no / n / never，
# 大小写不敏感）—— 和 EDIT_DEBUG 同一个判据（env_flag），不在这儿写死取值
EDIT_FZF = 'EDIT_FZF'

# 把吞掉的失败原因打到 stderr（排查用）：非空即开，哪几个算关见 ENV_OFF
EDIT_DEBUG = 'EDIT_DEBUG'

# --color 的三态取值（EDIT_COLOR 认同一套）：auto 是"只在这条流是终端时"才上色
COLOR_AUTO, COLOR_ALWAYS, COLOR_NEVER = 'auto', 'always', 'never'
COLOR_CHOICES = (COLOR_AUTO, COLOR_ALWAYS, COLOR_NEVER)

# 命令行上色开关。edit 常被当 $EDITOR 调起（git 那类），那种场景命令行不在我们手里，
# 所以也认 EDIT_COLOR —— 和 EDIT_DEBUG / EDIT_FZF 同一个理由
EDIT_COLOR = 'EDIT_COLOR'

# 没有 IDE 可托付时，链接由它自己的浏览器那一级打开（fish 的 help 就是认这个变量的）
BROWSER = 'BROWSER'

IPC_HOOK = 'VSCODE_IPC_HOOK_CLI'

# server 端窗口 socket 的文件名前缀（/run/user/<uid>/vscode-ipc-<uuid>.sock），
# find_sockets 拿它从 /proc/net/unix 里筛出 IDE 窗口的 socket
SOCK_PREFIX = 'vscode-ipc-'

# /proc 的根：find_sockets 全程只从这里读，测试可以把它指到假目录
PROC = '/proc'

# 命令行工具分类
#
# VS Code 系，写它自己的命令行时用 --goto 跳转
# vim 系, 使用 +行号 跳转
# nano / emacs 系同样用 +行号，单开一类是因为列号写法不同（见 EMIT）

CODE_LIKE = ('code', 'buddycn', 'trae-cn', 'cursor',)
VIM_LIKE  = ('vim', 'nvim', 'vi',)

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


# 链接（https://… / mailto: …）：交给系统（本地）浏览器 —— 用的是协议里第四种 type
# 的那条路（NOTES 那张表的 openExternal）。链接不是文件：塞进 open 的 fileURIs 会变成
# file:///home/…/https:/… 这种东西，所以它自带一条路 ——
# normalize 把这类参数摘成 ('external', 链接)（不认行号、不转绝对、不按 kind 翻译），
# 原样当 uris 发出去；file:// 除外，decode 成路径后照常当本地文件。
# CLI 那侧只有 code 系认 --openExternal，其余的退回 $BROWSER（fish 的约定）或 xdg-open。
#
# 报文之外的两种走法：
#   code 系 CLI: cli --openExternal <链接…>   —— IDE 自己的 browser.sh 就是这么调的
#                （它和直连是同一件事，只是要起一次 node）
#   $BROWSER   : BROWSER 可带参数，链接追加在后（fish 的 help 就是这么拼的）


# $BROWSER 没设、或设的是自己时的兜底：Linux 桌面是 xdg-open，macOS 是 open。
# Linux 上不能拿 open 兜底：Debian 系（含本机）的 /usr/bin/open 是 run-mailcap 的
# alternative，而 run-mailcap 吃的是**文件**不是链接 —— 实测 run-mailcap
# https://example.com/ 判不出 mime（application/octet-stream）再报 no such file，
# 退出 2。反过来 macOS 也没有 xdg-open（它是 Linux 桌面 xdg-utils 里的命令，除非
# brew 装过），所以两边各留自己那个
OPENERS = ('open',) if sys.platform == 'darwin' else ('xdg-open',)


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
    except OSError as e:
        logger.debug('listdir %s: %r', remote_cli_dir, e)
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


def hint_remote_cli(why: str) -> str:
    """选中的 CLI 是 remote-cli、又直连不上时，给一句能照做的提示（写 stderr）

    remote-cli 是 server 侧的代理，只认 IDE 集成终端；缺 hook（或在别处丢了 hook）时
    它必定拒绝，原话是 "Command is only available in WSL or inside a Visual Studio
    Code terminal." —— 那句话看不出该做什么，这里补上两条出路。

    窗口数顺手报一下：find_sockets() 只读 /proc，几毫秒，而且只在真要报错时算。
    """
    socks = find_sockets()

    lines = ['edit: %s；remote-cli 只认 IDE 集成终端，它会直接拒绝：' % why,
             '      Command is only available in WSL or inside a Visual Studio Code terminal.']

    if socks:
        lines.append('      这里有 %d 个候选 socket（edit --list 看它们属于哪个窗口）：'
                     % len(socks))
        lines.append('      edit --interactive <文件> 挑一个，'
                     '或 eval "$(edit --init bash)" 把 hook 装进 shell')
    else:
        lines.append('      也没找到存活的窗口：在 IDE 的集成终端里跑，'
                     '或先 eval "$(edit --init bash)" 把 hook 装进 shell')

    return '\n'.join(lines) + '\n'

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
            logger.debug('cli from %s: %s', choice.__name__, cli[0])
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
    except ValueError as e:
        logger.debug('shlex.split(%r): %r', v, e)     # 多半是引号没配对
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

# file:行[:列]：只有末尾的数字才算行列号，非贪婪的 (.+?) 把冒号让给文件名，
# 所以文件名里带冒号也解析得动（parse_goto 靠它，split_goto 是它的一步）
GOTO_RE = re.compile(r'^(.+?):(\d+)(?::(\d+))?$')


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

def unix_bind_paths() -> dict[int, str] | None:
    """读 /proc/net/unix，返回 {inode: socket 路径}（只留 vscode-ipc 那些）

    这张表就是"还有谁 bind 着"的判据：它只列已 bind 的 socket，天然把残留的 .sock
    文件滤掉 —— find_sockets 认窗口靠它，--prune 判"死没死"也靠它。
    没有 /proc（macOS）返回 None。

    字段：Num(带冒号) RefCount Protocol Flags Type St Inode Path，即 Path 从第 8 个字段起。
    用 Path 前面的那个 inode：它和 socket 文件的 st_ino 不是一个数。

    只切 7 刀，让 Path 原样留在最后一个字段里：路径里可能带空格（XDG_RUNTIME_DIR
    或 TMPDIR 指向带空格的目录时），用 line.split() 后取 p[-1] / p[7] 都会被截断 ——
    好在 Path 是最后一列，切够 7 刀就不会误伤。
    """

    if not os.path.isdir(PROC):
        return None

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
    except OSError as e:
        logger.debug('read %s/net/unix: %r', PROC, e)
        return None

    return ino2sock


def find_sockets():
    """列出存活的 vscode-ipc socket 及其归属

    只对 server 端有意义：桌面版（macOS 的 code / buddycn / trae-cn）根本不产生
    这种 socket，CLI 自己会复用当前窗口，没有窗口可挑。

    返回 [{'sock','pid','install','cli'}]，按 socket 文件的创建时间（sock_mtime）
    **倒序**：新的排最前 —— 同一窗口会同时挂着好几个 socket，最新的那个才是当前
    会话；读不到时间的（文件已被删 / 无权限）当最旧沉到最后，但一个都不丢（--list
    里它的时间列显示 ?）。

    顺序必须确定：/proc 的枚举顺序不稳，而 --list 的 # 和 --interactive 的编号都是
    靠位置认的。同一时间（同一 tick 内 bind，mtime 会完全相同）退回路径序 —— 先按
    路径排一遍再稳定地按时间排，所以结果与遍历顺序无关。

    没有 /proc（macOS）时返回 None。
    """

    ino2sock = unix_bind_paths()

    if ino2sock is None:
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

    def created(sock: dict[str, str]) -> float:
        """排序键：读不到创建时间的当最旧（-inf），倒序时正好沉到最后

        不用 `sock_mtime(...) or -inf`：mtime 可能合法地是 0.0，那是假值。
        """
        at = sock_mtime(sock['sock'])

        return float('-inf') if at is None else at

    socks = sorted(found.values(), key=lambda s: s['sock'])   # 先按路径定序（同时间兜底）
    socks.sort(key=created, reverse=True)                     # 再倒序；sort 稳定

    return socks

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

def raw_request(sock, msg, timeout):
    """发一次请求，返回回复的原始字节；失败**返回那个 OSError**（不当场处理）

    三层里最底的一层，名字说的是"未解析的字节"（和 http_code / http_body 里的 raw
    同一个词）：探活只要"成没成"（socket_request），发 open 的还要分"连不上"和
    "连上了但被拒"（socket_reply）。

    >>> isinstance(raw_request('/no-such.sock', {'type': 'status'}, timeout=0.1), OSError)
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
    except OSError as e:
        logger.debug('socket %s: request failed, %r', sock, e, exc_info=True)
        return e

    return b''.join(chunks)


def socket_request(sock, msg, timeout=1.5):
    """往窗口 socket 发一次请求，返回原始 HTTP 回复；失败返回 None

    协议就是 remote-cli 自己那套：POST / + JSON，回复是 chunked。连不上 / 超时
    一律返回 None 且不抛异常 —— 探活（`socket_status`）只要"成没成"，失败原因
    （路径没了 / 被拒 / 超时）走 logging.debug：想看就得 --debug / EDIT_DEBUG=1。
    要区分失败种类的走 `socket_reply`。

    >>> socket_request('/no-such.sock', {'type': 'status'}, timeout=0.1) is None
    True
    """

    reply = raw_request(sock, msg, timeout)

    return None if isinstance(reply, OSError) else reply

def http_code(raw):
    """HTTP 回复的状态码；解不出来返回 0

    >>> http_code(b'HTTP/1.1 200 OK\\r\\n\\r\\n')
    200
    >>> http_code(b'garbage')
    0
    """

    m = re.match(rb'HTTP/\d\.\d (\d{3})', raw)
    return int(m.group(1)) if m else 0

def socket_status(sock, timeout=1.5):
    """直连窗口 socket 问一次只读 status，返回 (authority, workspace)

    任何失败（连不上 / 超时 / 解析不了）都返回 (None, None) 且不抛异常 ——
    它在并发探测的线程里跑。失败原因走 logger.debug（--debug / EDIT_DEBUG=1 才打）：
    调用方看到的 (None, None) 分不出"窗口死了"和"窗口活着但 status 读不懂"。
    """

    raw = socket_request(sock, {'type': 'status'}, timeout)
    if not raw:
        # 连不上 / 超时已在 socket_request 里记过原因，这里专指"连上了但没回数据"
        logger.debug('status %s: empty reply', sock)
        return None, None

    try:
        text = json.loads(http_body(raw))
    except ValueError as e:
        logger.debug('status %s: JSON parse failed, %r; reply head %r', sock, e, raw[:120])
        return None, None

    if not isinstance(text, str):
        logger.debug('status %s: not a string; reply head %r', sock, raw[:120])
        return None, None

    return parse_status(text)

# token 的形状 —— 一个生产者（normalize / arg_token）、两个消费者（to_msg / to_argv）：
#   opt    认得的选项 + 它的取值（开关选项是 []）
#   goto   文件:行号[:列]（列可能没有）
#   file / folder   普通路径（是不是目录在 normalize 里就定了）
#   other  认不出来的：不认识的选项、-- 之后的字面量（取值不够的 -d / -m 由 normalize 抛异常，不进 other）
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
ExternalToken: TypeAlias = tuple[Literal['external'], str]   # 交给浏览器的链接（不是文件）
OtherToken: TypeAlias = tuple[Literal['other'], str]

Token: TypeAlias = (OptToken | GotoToken | FileToken | FolderToken
                    | ExternalToken | OtherToken)
ArgToken: TypeAlias = GotoToken | FileToken | FolderToken    # arg_token 只产这三种


def assert_never(arg: NoReturn) -> NoReturn:
    """match 的穷尽兜底：走到这儿说明 Token 联合有一种形状没写 case

    不用 `typing.assert_never`：那是 3.11+，本项目下限 3.10（pyproject 的
    requires-python）。形参标成底类型（mypy 眼里 `NoReturn` == `Never`），好处是**静态**
    就拦得住：给 Token 加一种形状而忘了补 case，mypy 会在调用处报"类型不是 Never"，
    不用等运行时炸出来。前提是别用 guard（`case ... if cond`）—— guard 让 mypy 没法把
    那个形状整个减掉，兜底会误报，判据写进 case 体内即可。
    """

    raise AssertionError('未处理的 token: %r' % (arg,))


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
    '-d': ('diffMode', 2), '--diff': ('diffMode', 2),
    '-m': ('mergeMode', 4), '--merge': ('mergeMode', 4),
    '--wait': ('wait', 0), '-w': ('wait', 0),
}

# 这几个选项要"有东西可开"才有意义（-a 要把目录加进工作区、-d 要 diff 两个文件、
# --wait 至少要等一个文件）。空着交给 CLI 只会发个空报文、或让 vim 系开个空编辑器，
# 所以 main 里直接提示退出。裸调用与 -r / -n 不在此列 —— 那些对 code 系有定义
# （开窗口 / 复用窗口 / 新窗口）
#
# -d / --diff 现在就是 arity 2（紧跟 2 个文件）、-m / --merge 是 arity 4，跟 VS Code 的
# `--diff <f1> <f2>` / `--merge <p1> <p2> <base> <result>` 对齐。取值不足或夹了选项，
# normalize 直接抛 NormalizeError（main 捕获后报错退出）—— diff / merge 数量不齐交回 CLI
# 也开不对，不如早期明确报错。代价是放弃自由顺序（如 `a b -d`）：那是 edit 比 VS Code 多给的
# 便利，现在按 VS Code 的写法收紧。-a 的文件仍是位置参数（arity 0），保持自由顺序。
NEEDS_TARGET: tuple[OptionField, ...] = ('addMode', 'wait')


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


class NormalizeError(ValueError):
    """normalize 期间的参数错误（-d 要 2 个文件 / -m 要 4 个路径，或取值夹了选项）

    main 捕获后打印并退出——数量不齐时交回 CLI 也开不对，不如早期明确报错。
    """


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
    >>> normalize(['-d', 'a.txt', 'b.txt'])                 # -d 紧跟 2 个文件（arity 2）
    [('opt', '-d', 'diffMode', ['a.txt', 'b.txt'])]
    >>> normalize(['--diff', 'a.txt', 'b.txt'])             # 长名同
    [('opt', '--diff', 'diffMode', ['a.txt', 'b.txt'])]
    >>> normalize(['a.txt', 'b.txt', '-d'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -d 需要2 个文件...
    >>> normalize(['-d'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -d 需要2 个文件...
    >>> normalize(['-d', 'a.txt'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -d 需要2 个文件...
    >>> normalize(['-d', '-r'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -d 需要2 个文件...
    >>> normalize(['-m', 'base', 'theirs', 'ours', 'result']) # 4 个路径收进 values
    [('opt', '-m', 'mergeMode', ['base', 'theirs', 'ours', 'result'])]
    >>> normalize(['--merge', 'base', 'theirs', 'ours', 'result'])  # 长名同
    [('opt', '--merge', 'mergeMode', ['base', 'theirs', 'ours', 'result'])]
    >>> normalize(['-m', 'a', 'b'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -m 需要4 个路径...
    >>> normalize(['-m', 'a', '-r', 'b'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -m 需要4 个路径...
    >>> normalize(['-a', '/tmp'])       # -a 是开关（arity 0）：后面几个都算目标，数量不限
    [('opt', '-a', 'addMode', []), ('folder', '/tmp')]
    >>> normalize(['-a', '/tmp', 'a.txt'])   # 目录与文件一起收：各落各的 URI（与上游同）
    [('opt', '-a', 'addMode', []), ('folder', '/tmp'), ('file', 'a.txt')]
    >>> normalize(['-a'])               # 空着不算 normalize 的错：main 里 NEEDS_TARGET 报
    [('opt', '-a', 'addMode', [])]
    >>> normalize(['https://example.com'])       # 链接：交给浏览器，不当文件
    [('external', 'https://example.com')]
    >>> normalize(['mailto:a@b.com', 'tel:+123'])  # 不带 // 的两种链接也认
    [('external', 'mailto:a@b.com'), ('external', 'tel:+123')]
    >>> normalize(['file:///a/b.txt'])           # file:// 当本地文件（同 vim 的 file://）
    [('file', '/a/b.txt')]
    >>> normalize(['file:///a/b.txt:12'])         # :行号照旧认（路径先解出来再交给 parse_goto）
    [('goto', '/a/b.txt', '12', None)]
    >>> normalize(['file:///a/b%20c.txt'])        # percent 编码解掉
    [('file', '/a/b c.txt')]
    >>> normalize(['--', 'https://example.com']) # -- 之后按字面量，链接也照旧
    [('other', '--'), ('other', 'https://example.com')]
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
                if field == 'diffMode':
                    want = '2 个文件'
                elif field == 'mergeMode':
                    want = '4 个路径（base / theirs / ours / result）'
                else:
                    want = '%d 个取值' % arity
                got = ('取值里夹了选项' if any(v.startswith('-') for v in values)
                       else '只收到 %d 个' % len(values))
                raise NormalizeError('%s 需要%s，%s' % (a, want, got))

            i += arity
            out.append(('opt', a, field, values))
            continue

        out.append(positional_token(a))

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

    for t in tokens:
        match t:
            case ('opt', _, 'wait', _):
                return True

            # 其余一律有意忽略：别的选项、文件、目录、链接、认不出的
            case ('opt', _, _, _):
                pass
            case ('file' | 'folder' | 'external' | 'other', _):
                pass
            case ('goto', _, _, _):
                pass

            case _:
                assert_never(t)
    return False

# CLI 等 marker 的轮询间隔（server-cli.js 就是 1 秒一问）
WAIT_MARKER_INTERVAL = 1.0


def make_marker():
    """给 --wait 造一个空 marker，返回路径；造不出来返回 None

    和 CLI 一个做法（server-cli.js 的 createWaitMarkerFile）：mkstemp 一个空
    文件，路径随报文交给窗口，窗口在编辑器里那个文件被关掉时删掉它。
    """

    try:
        fd, path = tempfile.mkstemp(prefix='edit-wait-')
    except OSError as e:
        logger.debug('mkstemp: %r', e)      # 造不出来 --wait 就静默退化成不等
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

    翻不了就交回 CLI：未知选项 / -- / 没给参数。-d 要 2 个文件、-m 要 4 个路径，
    数量不够或取值夹了选项由 normalize 直接抛 NormalizeError（不交回 CLI）。
    目录进 folderURIs，文件进 fileURIs，:行号[:列] 交给 parse_goto 认。

    （-a / -d / --wait 空着的情况走不到这里：main 见到 NEEDS_TARGET 里那几项没有
    目标就直接提示退出了。）

    -g / --goto 被忽略（见 normalize）：行号只认位置参数写法，所以 `-g f:3` 与 `f:3`
    发出的是同一份报文。内联写法 --goto=X / -g=X 不算"忽略"、也不特判：它们跟别的
    不认识的选项一样整成 ('other', 原文)，于是这里返回 None（交回 CLI）。

    -m / --merge 认 4 个取值（path1 path2 base result）：原样进 fileURIs 并置
    mergeMode。不足 4 个由 normalize 抛 NormalizeError（不交回 CLI，merge 编辑器也救不了
    不齐的路径）；取值里夹了别的选项同理报错。

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
    >>> open_request(['-m', '/a', '/b', '/base'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -m 需要4 个路径...
    >>> open_request(['-m', '/a', '-r', '/base', '/result'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    edit.NormalizeError: -m 需要4 个路径...
    >>> open_request(['-g']) is None                        # 选项被忽略，没东西可开
    True
    >>> open_request(['-g', '-r']) is None                  # 只剩 -r：还是没东西可开
    True
    >>> open_request([]) is None
    True
    """

    return to_msg(normalize(args), marker)


def has_open_target(tokens: list[Token]) -> bool:
    """有没有"能打开的东西"：文件 / 目录 / 跳转目标 / 带取值的选项 / 认不出的字面量

    认不出的（('other', …)）也算有 —— 它走的是"交回 CLI"那条路，不是"没东西可开"。
    链接（('external', …)）**不算**：它走 open_uris 那条单独的路，不进 open 报文（main
    摘走链接后用这个判"还剩东西可开吗"）。

    >>> has_open_target(normalize(['a.txt']))
    True
    >>> has_open_target(normalize(['/tmp']))
    True
    >>> has_open_target(normalize(['--wait']))       # 开关自己不算目标
    False
    >>> has_open_target(normalize(['-r']))            # 同上
    False
    >>> has_open_target(normalize(['https://example.com']))
    False
    >>> has_open_target(normalize(['a.txt:3']))            # 带行号跳转也算目标
    True
    """

    for t in tokens:
        match t:
            # 算目标的：文件 / 目录 / 认不出的参数 / 带行号跳转
            case ('file' | 'folder' | 'other', _):
                return True
            case ('goto', _, _, _):
                return True
            case ('opt', _, _, values):
                # 带取值的选项（-m 的 path1..result）算目标，空着等于光开关、不算。
                # 判据写在 case 体内而不是 guard：guard 会让 mypy 减不掉 OptToken，
                # 下面那句 assert_never 就误报
                if values:
                    return True
            case ('external', _):
                pass                            # 链接走 openExternal 自己那条路
            case _:
                assert_never(t)

    return False


def action_but_no_target(tokens):
    """NEEDS_TARGET 里的选项（--wait / -a）出现、却没有任何可开的目标（file /
    folder / goto / other / 带取值的选项）时，返回 (True, 这些选项实际敲的 flag)，否则
    (False, None)。与 wait_but_no_file 同构：都是"误用检测器"，main 里
    统一用 `misuse, detail = 检测器(tokens); if misuse:` 调。

    认不出的 token（('other', …)）算"有东西"，-- 之后的字面量也在其中；-m 那类带取值的
    选项也算有目标。空着（连 other 都没有）且没给 NEEDS_TARGET 选项，不在这里报。
    「有没有目标」那一段与 has_open_target 同一套判据，所以直接共用它。

    >>> action_but_no_target(normalize(['--wait']))              # NEEDS_TARGET 无目标
    (True, ['--wait'])
    >>> action_but_no_target(normalize(['-a']))                  # -a 同：光开关没目录
    (True, ['-a'])
    >>> action_but_no_target(normalize(['--wait', 'a.txt']))      # 有文件：OK
    (False, None)
    >>> action_but_no_target(normalize(['-d', '/tmp', '/tmp2']))  # diff 要 2 个，给 2 个目录：OK
    (False, None)
    >>> action_but_no_target(normalize(['-m', 'a', 'b', 'base', 'res']))  # 取值算目标
    (False, None)
    >>> action_but_no_target(normalize(['--', '--wait']))         # other 算有东西，且 --wait 在 other 里不算
    (False, None)
    """

    flags = []

    for t in tokens:
        match t:
            case ('opt', flag, field, _):
                # 判据写在 case 体内而不是 guard：guard 会让 mypy 减不掉 OptToken，
                # 兜底的 assert_never 就误报（has_open_target 同理）
                if field in NEEDS_TARGET:
                    flags.append(flag)
            case ('file' | 'folder' | 'external' | 'other', _):
                pass
            case ('goto', _, _, _):
                pass
            case _:
                assert_never(t)

    if flags and not has_open_target(tokens):
        return True, flags

    return False, None


def wait_but_no_file(tokens):
    """--wait 后面得是文件：--wait 等的是"文件编辑器关掉"那一刻删 marker，目录没有
    "编辑器"这一说、marker 没人删 wait_marker 会永久挂住；非文件目标（目录、认不出的
    参数）也一样不算"可等的文件"。所以只要 wait 在、又没有 file / goto，就算误用；
    空着（连 other 都没有）交给上面 nothing_to_open 报"没有文件或目录"，不在这重复。
    返回 (是否误用, 命中的 flag)：误用为 (True, flag)，没误用为 (False, None)。

    >>> wait_but_no_file(normalize(['--wait', '/tmp']))          # 只有目录 -> flag
    (True, '--wait')
    >>> wait_but_no_file(normalize(['--wait', 'a.txt']))         # 有文件：OK
    (False, None)
    >>> wait_but_no_file(normalize(['--wait', 'a.txt', '/tmp'])) # 有文件：OK
    (False, None)
    >>> wait_but_no_file(normalize(['-a', '/tmp']))               # 不是 --wait
    (False, None)
    >>> wait_but_no_file(normalize(['--wait', 'a.txt:12']))  # 带行号文件也是文件
    (False, None)
    """

    wait_flag = has_file = False
    for t in tokens:
        match t:
            case ('opt', flag, 'wait', _):
                wait_flag = flag
            case ('opt', _, _, _):
                pass
            case ('file', _) | ('goto', _, _, _):  # 带行号文件也是文件
                has_file = True
            # 有意不算文件：目录、链接、认不出的参数、别的选项
            case ('folder' | 'external' | 'other', _):
                pass
            case _:
                assert_never(t)

    return (True, wait_flag) if (wait_flag and not has_file) else (False, None)


# 服务端会把 fileURIs 里"扩展名是 .code-workspace"的那些**改判**成工作区
# （server-main.js 的 open()：sU() 判据就是 extname 严格等于 b5 = ".code-workspace"，
# 纯路径判定不看内容）。所以这类目标照样"能打开"，但打开的是工作区、不是文件编辑器。
#
# 别为了"语义正确"把它挪进 folderURIs：folderURIs 一律按文件夹处理、服务端不判，
# 于是窗口打开一个叫 x.code-workspace 的**空文件夹**，工作区里的 folders/settings 全丢。
# 放 fileURIs 让服务端改判，是唯一能表达"打开工作区"的入口。
WORKSPACE_SUFFIX = '.code-workspace'


def is_workspace_target(path):
    """这个目标会不会被服务端改判成"打开工作区"

    判据照抄上游（extname 严格等于小写 `.code-workspace`），所以大小写不同就**不当**
    工作区 —— 上游那种情况是当普通文件在文本编辑器里打开，我们跟着，别分叉。
    只看结尾，所以带行号的原样参数（`x.code-workspace:3`）不算：那时行号已经在
    `parse_goto` 里拆开，判的是拆开后那个路径。

    >>> is_workspace_target('/p/proj.code-workspace')
    True
    >>> is_workspace_target('/p/proj.code-workspace:3')
    False
    >>> is_workspace_target('/p/Proj.Code-Workspace')
    False
    >>> is_workspace_target('/p/a.txt')
    False
    """

    return path.endswith(WORKSPACE_SUFFIX)


# 这几件事都以"目标是个文件编辑器"为前提，工作区 URI 一条都不成立：行号没地方跳、
# --wait 的 marker 没人删（wait_marker 没有超时，会永久挂住）、diff/merge 少一个文件、
# -a 加不进任何工作区。所以碰到"目标是 .code-workspace"就说明白，别静默做错事。
WORKSPACE_USE = {
    'diffMode': 'diff 的文件',
    'mergeMode': 'merge 的文件',
    'addMode': '加进工作区的目录',
}


def workspace_conflict(tokens):
    """目标里有 .code-workspace，又踩了 --wait / 行号 / -d / -m / -a -> 返回要报的话

    只拦"语义会消失"的组合。光 `edit x.code-workspace`（打开工作区本身）是对的，放行；
    判据与上游一致，所以只有真会被改判的才进来。

    >>> workspace_conflict(normalize(['/p/proj.code-workspace'])) is None
    True
    >>> workspace_conflict(normalize(['--wait', '/p/a.txt'])) is None
    True
    >>> workspace_conflict(normalize(['/p/proj.code-workspace:3'])).startswith(
    ...     'edit: 工作区文件不支持 :行号')
    True
    >>> workspace_conflict(normalize(['-d', '/p/a.txt', '/p/b.txt', '/p/p.code-workspace']))
    'edit -d: /p/p.code-workspace 是工作区文件，不能当 diff 的文件（要的是普通文件 / 目录）'
    >>> workspace_conflict(normalize(['-m', 'a', 'b', '/p/base', '/p/p.code-workspace']))[:9]
    'edit -m: '
    >>> workspace_conflict(normalize(['--wait', '/p/p.code-workspace'])).startswith(
    ...     'edit --wait: /p/p.code-workspace 是工作区文件')
    True
    """

    used: list[tuple[str, str]] = []      # (选项名, 这选项要什么)，报错时逐个列出
    wait = False
    targets: list[tuple[str, str | None]] = []    # (路径, 行号)；行号 None = 不是跳转目标

    for t in tokens:
        match t:                          # 一趟收齐：目标从位置参数和 -m 那类取值两处来
            case ('goto', file, line, _col):
                targets.append((file, line))

            case ('file', path):
                targets.append((path, None))

            case ('opt', flag, 'wait', _values):
                wait = True

            case ('opt', flag, field, values):
                targets += [(v, None) for v in values]

                if what := WORKSPACE_USE.get(field):
                    used.append((flag, what))

    for path, line in targets:
        if not is_workspace_target(path):
            continue

        if line is not None:
            return ('edit: 工作区文件不支持 :行号（%s:%s）—— 窗口是把它当**工作区**打开的，'
                    '不是当文件跳行' % (path, line))

        if used:
            return ('edit %s: %s 是工作区文件，不能当 %s（要的是普通文件 / 目录）'
                    % (' / '.join(flag for flag, _ in used), path,
                       ' / '.join(what for _, what in used)))

        if wait:
            return ('edit --wait: %s 是工作区文件，等不到"被关掉"（--wait 等的是文件编辑器'
                    '被关掉）；要等关掉请换成普通文件' % path)

    return None


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
            case ('external', _):
                return None                 # 链接不走 open 报文（main 早摘走单独发
                                            # openExternal；这里返回 None 是"这份报文
                                            # 表达不了"，不是"交回 CLI"）

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
                assert_never(t)             # Token 是穷尽的：漏一种形状 mypy 当场就报

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
#            （diffMode / mergeMode 例外：摘开关时也留取值）。**一项对一个选项，不共用** ——
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
                    out.extend(values)   # 不认这个开关就摘掉，但取值（diff/merge 的文件、路径）照常当参数传
                    continue

                out.append(flag)
                out.extend(values)

            case ('external', _):
                # 链接不该到这儿：main 早把它摘走单独发 openExternal。真到了说明调用方
                # 漏摘 —— 照样炸出来，别静默把参数丢了。写开这一条是为了让下面的
                # assert_never 类型闭合（Token 有 6 种形状，这里 6 种都得露面）
                raise AssertionError('链接不该进 to_argv: %r' % (t,))

            case _:
                assert_never(t)             # 漏一种形状 mypy 当场就报，不用等运行时炸

    if emit['abspath']:
        out = [os.path.abspath(a) if os.path.exists(a) else a for a in out]

    return out


def cli_argv(args: list[str], kind: str | None) -> list[str]:
    """命令行 -> 交给 CLI 的参数（normalize + to_argv，测试走这个缝）"""

    return to_argv(normalize(args), kind)


# 失败时给用户看的那一句"为什么"。errno 只在 --debug 里看得见，HTTP 码只在回复头里，
# 所以提示必须自带信息量 —— "连不上"三个字、或者一个光秃秃的 500，谁也看不出下一步。
#
# 两类失败共用这张表，键是**带标签的元组** `('errno', 数字)` / `('http', 状态码)`：
# 标签说清查的是哪一层，于是两个分支的查法对称（`('errno', e.errno)` 对 `('http', code)`），
# 也不必把 errno 转成名字再查（`errno.errorcode` 那一步全省了）。两边都是 int，标签就是
# 唯一的消歧手段 —— 将来加第三类失败（比如"超时但已发出"）照样加一个标签就行。
# 表里没有的键走各自的兜底（`strerror` / 通用句），所以这里是"加话"，不是"白名单"。
WHY_FAILED: dict[tuple[str, int], str] = {
    # socket 层（socket_reply 里 isinstance(raw, OSError) 那一支）
    ('errno', errno.ENOENT): 'socket 路径没了（窗口刚关？）',
    ('errno', errno.ECONNREFUSED): 'socket 文件还在但没人听（窗口已退出、文件没删）',
    ('errno', errno.ETIMEDOUT): '超时（窗口卡住，或它已经收到请求、只是回包慢）',
    ('errno', errno.EACCES): '没有权限连这个 socket',
    ('errno', errno.EPIPE): '连上就断了（窗口正在退出）',
    # 业务层（非 200 那一支）：具体是什么错由服务端原话补，这句只给"下一步"
    ('http', 404): '多半是窗口版本与 edit 的报文不匹配，换个窗口或升一下试试',
    ('http', 500): '窗口处理报文时崩了，它自己的日志里有堆栈',
}


class Reply(NamedTuple):
    """一次 open / openExternal 请求的结局：成功 / 被拒 / 连不上

    分三态而不是 `(ok, detail)`：两种失败的**该做的动作不一样**，两态逼着调用方一律
    "改用 CLI"—— 而 CLI 走的是同一个 socket、同一份报文，注定再失败一次（`--wait`
    还白搭一次进程、把 marker 收回来重造）。所以两态都直接退出，把原因说清楚。

    **为什么不重试另一个窗口**：`raw_request` 失败可能是"根本没发出去"（connect 阶段
    ENOENT / ECONNREFUSED），也可能是"已经发出去了、只是回包慢"（recv 超时）——
    后者重发会在另一个窗口**再开一次**同一个文件（链接则多开一个标签页），
    那不是浪费，是有副作用的重试。要安全重试，得先能区分这两段（把 connect 与
    send/recv 分开报），那是另一个改法，先不换窗口。
    """

    ok: bool
    reason: str          # '' | 'refused' | 'unreachable'
    detail: str          # 服务端原话 / errno 说法，给人看


def socket_reply(sock, msg, timeout=3.0):
    """把 open / openExternal 发出去，回报三态结局（不抛异常）

    判据与 CLI 一致：只认 HTTP 200（`server-cli.js` 就是 JSON.parse 之后看
    statusCode）；404 / 500 / 坏 JSON 都算"被拒"。

    >>> socket_reply('/no-such.sock', {'type': 'open'}, timeout=0.1).reason
    'unreachable'
    """

    raw = raw_request(sock, msg, timeout)

    if isinstance(raw, OSError):
        # 键是 ('errno', 数字)：平台没有的 errno 查不到就落回 strerror ——
        # 这张表是"加话"，不是白名单
        known = WHY_FAILED.get(('errno', raw.errno or 0))

        return Reply(False, 'unreachable', '%s（%s）' % (
            sock, known or raw.strerror or str(raw)))

    code = http_code(raw)

    if code == 200:
        return Reply(True, '', '')

    if code == 0:
        # 连上了却没回出 HTTP 头（silent 窗口 accept 完立刻断就是这种）：不是"被拒"，
        # 是通道这一侧已经没了 —— 归到 unreachable，别让提示指向"版本不匹配"
        return Reply(False, 'unreachable',
                     '%s（连上了却没回出完整回复，窗口正在退出？）' % sock)

    # 被拒：服务端原话（"Unknown message type: open" 之类）当主体，WHY_FAILED 补"下一步"。
    # 表里没有的码给通用的一句 —— 于是**每条 refused 消息都自带下一步**，
    # reply_failure 那侧就只做框定，不用再猜这个码该怎么办
    body = http_body(raw).strip()
    detail = 'HTTP %s%s' % (code, '（%s）' % body if body else '')
    why = WHY_FAILED.get(('http', code), '换个窗口或升一下试试')

    return Reply(False, 'refused', '%s —— %s' % (detail, why))


def reply_failure(reply):
    """把两种失败说成一句能照做的提示（这两种情况 edit 退不出去，也不再试）

    "为什么"与"该往哪看"都已经在 detail 里了（socket 层是 errno 人话，refused 是服务端
    原话 + WHY_FAILED 补的那句），这里只负责点明**这个结论意味着什么类别的问题**。

    >>> reply_failure(Reply(False, 'refused', 'HTTP 500（boom）—— 崩了')).startswith(
    ...     '窗口不认这条报文（HTTP 500')
    True
    >>> reply_failure(Reply(False, 'unreachable', '/run/x.sock（路径没了）')).startswith(
    ...     '窗口 socket 连不上')
    True
    """

    if reply.reason == 'refused':
        return '窗口不认这条报文（%s）—— 不是 socket 的问题' % reply.detail

    return ('窗口 socket 连不上（%s）—— 窗口可能刚关；edit --list 看还在的窗口，'
            'edit --interactive 挑一个' % reply.detail)

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

def fmt_time(ts: float) -> str:
    """时间戳 -> 本地时间 'YYYY-MM-DD HH:MM:SS'

    两处共用这一串格式：--list 的表与 --prune 的清单（免得两处漂）。

    >>> len(fmt_time(1782300000.0))         # 具体值看时区，只看形状
    19
    """
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))


def sock_mtime(path: str) -> float | None:
    """socket 文件的创建（bind）时间；stat 不到（已被删 / 无权限）返回 None

    用 mtime 的理由见 prune_sockets：Linux 拿不到 st_birthtime，而 socket 文件 bind
    之后没人再写它。展示（sock_created）与排序（find_sockets）共用这一处 stat ——
    两边取同一个值，--list 的时间列才会和行序一致。

    >>> sock_mtime('/no-such-file.sock') is None
    True
    """
    try:
        return os.stat(path).st_mtime
    except OSError as e:
        logger.debug('stat %s: %r', path, e)
        return None


def sock_created(path: str) -> str:
    """socket 文件的创建（bind）时间；stat 不到就 '?'

    --list 里路径可能刚被删（窗口退了），那就显示 ?。

    >>> sock_created('/no-such-file.sock')
    '?'
    """
    at = sock_mtime(path)

    return '?' if at is None else fmt_time(at)


def format_sockets(socks, hook, colored=False):
    """把候选渲染成表格行：--list 打印它，--init --interactive 也用它

    打印完整 socket 路径：挑完窗口直接就能 export 给 VSCODE_IPC_HOOK_CLI。
    和 hook 相同的那个用 * 标出来；workspace 是问窗口要来的，问不到就是 ?。
    colored 时表头压暗、当前窗口那颗 * 亮黄（见 GRAY / YELLOW）。

    time 列是 socket 文件的创建（bind）时间（见 sock_created）—— 同一个窗口会同时挂着
    好几个 socket，靠它区分谁新谁旧；文件不在了就是 ?。
    这里只按传进来的顺序渲染（编号 = 位置），排序是 find_sockets 的事：按时间倒序，
    所以 # 号越小越新。

    >>> s = [{'sock': '/r/vscode-ipc-a.sock', 'pid': '1',
    ...       'cli': '/i/bin/remote-cli/buddycn', 'workspace': '/w/proj'}]
    >>> format_sockets(s, '/r/vscode-ipc-a.sock')[1].split()[0]
    '*'
    >>> format_sockets(s, None)[1].split()[0]
    '1'
    >>> format_sockets(s, None)[1].split()[1]       # 路径不存在 -> 时间列是 ?
    '?'
    >>> format_sockets(s, None)[1].split()[-2:]
    ['buddycn', '/w/proj']
    >>> b = [{'sock': '/r/a b.sock', 'pid': '1', 'cli': ''}]
    >>> " '/r/a b.sock'" in format_sockets(b, None)[1]
    True
    >>> format_sockets(b, None)[1].split()[-2:]     # cli / workspace 都读不到
    ['?', '?']
    >>> format_sockets(s, '/r/vscode-ipc-a.sock', True)[1].startswith(YELLOW + '*')
    True
    >>> format_sockets(s, None, True)[1].split()[0]        # 不是当前窗口：只有编号
    '1'
    """

    header = '  #   %-19s %-67s %-8s %-9s %s' % (
        'time', 'socket', 'pid', 'cli', 'workspace')
    lines = [paint(header, GRAY, colored)]

    for n, s in enumerate(socks, 1):
        # 只给 * 上色：转义是零宽字符，所以列对齐不受影响 —— 前提是别在 %-19s 这种
        # 补白**之前**上色（补白按字节数算，带了转义就会补短）
        mark = paint('*', YELLOW, colored) if s['sock'] == hook else ' '

        # shlex.quote：路径含空格时整行还能直接粘回 shell；正常路径不加引号
        lines.append('%s %2d  %-19s %-67s %-8s %-9s %s' %
                     (mark, n, sock_created(s['sock']), shlex.quote(s['sock']),
                      s['pid'], os.path.basename(s['cli']) or '?',
                      s.get('workspace') or '?'))

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

def pick_first():
    """--first：取候选里的第一个（等于 --interactive 敲 1，但不需要 stdin）

    给"没 hook 但就想开在窗口里"用，脚本里尤其方便。返回 socket 路径；没有候选
    （或这里根本没有 /proc）返回 None，调用方自己决定怎么报错。
    """
    socks = find_sockets()

    return socks[0]['sock'] if socks else None

def print_sockets(colored: bool = False) -> None:
    socks = load_sockets('edit --list')

    print('\n'.join(format_sockets(socks, current_socket(), colored)))


class PruneResult(NamedTuple):
    """--prune 的结果：删掉/会删的（带时间）+ 两类跳过的计数 + 删失败的路径"""

    removed: list[tuple[float, str]]    # (mtime, 路径)，按时间升序（最旧的排最前）
    alive: int                          # 还 bind 着的，没动
    not_socket: int                     # 名字像但其实是普通文件的，没动
    failed: list[str]                   # 删失败的（权限之类）


def prune_dirs() -> list[str]:
    """可能放着 vscode-ipc socket 的目录（去重、只留存在的）

    Linux 实测都在 $XDG_RUNTIME_DIR（这台机器 582 个）；$TMPDIR 是 macOS 那边的习惯
    位置；hook 所在目录兜底 —— 它一定是我们正在用的那个 socket 的家。
    """
    cands = [os.environ.get('XDG_RUNTIME_DIR'), os.environ.get('TMPDIR')]
    hook = current_socket()

    if hook:
        cands.append(os.path.dirname(hook))

    out = []

    for d in cands:
        if d and os.path.isdir(d) and d not in out:
            out.append(d)

    return out


def prune_sockets(dry_run: bool = False) -> PruneResult | None:
    """删掉没人 bind 的 vscode-ipc socket 文件；没有 /proc 时返回 None（一个也不删）

    判据（宁可不删，也别删错）：
    - 名字是 vscode-ipc-*.sock，而且确实是 socket 文件（S_ISSOCK —— 同名的普通文件不动）；
    - 路径不在 /proc/net/unix 里，即没人 bind —— 活着的一个都不动；
    - 只扫 prune_dirs() 那几个目录，不递归；
    - 读不到目录 / 删不掉（权限）就跳过，记进 failed，不中断。

    "创建时间"用 st_mtime：Linux 上拿不到 st_birthtime（实测 AttributeError），而 socket
    文件 bind 之后没人再写它 —— 实测收发一次数据，mtime / ctime 都不变，所以 mtime 就是
    bind 那一刻。
    """
    bound = unix_bind_paths()

    if bound is None:
        return None

    alive_paths = set(bound.values())
    alive = not_socket = 0
    removed: list[tuple[float, str]] = []
    failed: list[str] = []

    for d in prune_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            logger.debug('listdir %s: %r', d, e)    # 读不到就跳过这个目录
            continue

        for name in names:
            if not (name.startswith(SOCK_PREFIX) and name.endswith('.sock')):
                continue

            path = os.path.join(d, name)

            try:
                st = os.lstat(path)     # lstat：万一同名的是个软链，也别顺着走
            except OSError:
                continue

            if not stat.S_ISSOCK(st.st_mode):
                not_socket += 1
                continue

            if path in alive_paths:
                alive += 1
                continue

            if not dry_run:
                try:
                    os.unlink(path)
                except OSError:
                    failed.append(path)
                    continue

            removed.append((st.st_mtime, path))

    removed.sort()
    return PruneResult(removed, alive, not_socket, failed)


def format_prune(result: PruneResult, dry_run: bool) -> list[str]:
    """把 prune 的结果渲染成要打印的行（时间在前，最旧的排最前）

    >>> r = PruneResult([(1782300000.0, '/r/vscode-ipc-a.sock')], 3, 1, [])
    >>> format_prune(r, True)[0].endswith('  /r/vscode-ipc-a.sock')
    True
    >>> format_prune(r, True)[1:]
    ['共 1 个会删；跳过 3 个活着的、1 个不是 socket 文件', '（--dry-run：没有真删）']
    >>> format_prune(r, False)[1:]
    ['已删除 1 个；跳过 3 个活着的、1 个不是 socket 文件']
    """
    lines = ['%s  %s' % (fmt_time(m), p) for m, p in result.removed]

    if dry_run:
        lines.append('共 %d 个会删；跳过 %d 个活着的、%d 个不是 socket 文件'
                     % (len(result.removed), result.alive, result.not_socket))
        lines.append('（--dry-run：没有真删）')
    else:
        lines.append('已删除 %d 个；跳过 %d 个活着的、%d 个不是 socket 文件'
                     % (len(result.removed), result.alive, result.not_socket))

    lines.extend('! 删不掉：%s' % p for p in result.failed)

    return lines


def print_prune(dry_run: bool = False) -> None:
    result = prune_sockets(dry_run)

    if result is None:
        sys.exit('edit --prune: 没有 %s，判断不了哪个 socket 还活着 —— 一个也没删' % PROC)

    print('\n'.join(format_prune(result, dry_run)))

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
    而且 fzf 要独占终端）。EDIT_FZF 设成 ENV_OFF 那套（'' / 0 / false / off / no /
    n / never，大小写不敏感）就显式关掉 —— 和 EDIT_DEBUG 同一个判据（env_flag），
    所以 `EDIT_FZF=OFF` 这种大写也认（以前只认小写的 'off'），`EDIT_FZF=` 空串也算关。
    这个开关默认**开**（没设 = 用），所以 env_flag 传 default=True —— 和 EDIT_DEBUG
    （没设 = 关）相反，别把两个默认值写反。
    不写 doctest：它看的是当前终端和 PATH。
    """

    if not env_flag(EDIT_FZF, True):
        return False

    return sys.stdin.isatty() and bool(shutil.which('fzf'))


# fzf 被 Esc / Ctrl-C 中断时的退出码（0.67.0 用 pty 实测：Esc 与 Ctrl-C 都是 130；
# 对照：fzf 自己报错是 2，找不到 fzf 是 127 / 拉不起来是 OSError）。靠它把
# "用户明确取消"和"这条路不通"分开 —— 两者的收场相反，见下面的 FZF_CANCELLED。
FZF_CANCEL_CODE = 130

# fzf_pick 的"用户取消"返回值：按身份比较（is），与"用不了 / 认不出"的 None 分开。
# 取消 = 直接退出；用不了 = 回退编号输入（见 ask_socket）。
FZF_CANCELLED = object()

def fzf_pick(socks):
    """用 fzf 挑一个窗口：返回候选项；取消返回 FZF_CANCELLED；认不出 / 拉不起来返回 None

    候选行喂给 fzf 的 stdin，它的 UI 走自己的 stderr（继承终端）—— 我们的
    stdout 要留给 --init 的初始化片段，不能让选择器写进来；选中项从 fzf 的
    stdout 读。

    三种结局分开，别合并成一种：
      * Esc / Ctrl-C（退出码 FZF_CANCEL_CODE）是用户明确要取消 —— Esc 在哪儿都是
        "退出"，再弹一个编号提示等于让取消失效，所以返回 FZF_CANCELLED 直接退出；
      * 拉不起来（OSError）/ 别的退出码（fzf 报错等）是"这条路不通"，返回 None 由
        ask_socket 落到编号输入 —— 和没装 fzf 时行为一致；
      * 选中的行认不出编号：那是 fzf 给的行不是我们要的，不代表用户取消，也回退。
    """

    # 不上色：fzf 没加 --ansi，转义会被当普通字符显示出来（一串 ^[）
    lines = format_sockets(socks, current_socket(), False)

    try:
        # --header-lines=1：表头那行固定住，不参与过滤
        # --tiebreak=index：默认的 length 判据是"忽略前导空白"量长度的，于是带 * 的
        #   那行（当前窗口）会被当成更长、排到最后；换成 index 后同分就按输入顺序
        #   （也就是 --list 的顺序，最新在前），得分排序本身不受影响
        proc = subprocess.run(['fzf', '--prompt=窗口> ', '--height=40%',
                               '--layout=reverse', '--header-lines=1',
                               '--tiebreak=index'],
                              input='\n'.join(lines) + '\n',
                              stdout=subprocess.PIPE, text=True)
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode == FZF_CANCEL_CODE:
        return FZF_CANCELLED                # Esc / Ctrl-C：用户明确取消，不是故障

    if proc.returncode != 0:
        logger.debug('fzf exited %d, falling back to number input', proc.returncode)
        return None

    n = socket_number(proc.stdout)
    if not n:
        logger.debug('fzf output has no socket number: %r', proc.stdout)
        return None

    return pick_socket(socks, n)

# --interactive 取消时的收场语：fzf 里按 Esc 和编号输入按 q 是同一种意图（都没选中
# 窗口），共用这一句 + 同一个退出码，不写成两句不同的话。
EDIT_NO_WINDOW_PICKED = 'edit --interactive: 没有选中窗口'

def ask_socket(socks, colored: bool = False):
    """列出候选并让用户挑一个，返回候选项

    候选和提示都写 stderr：stdout 要留给最终的初始化片段，这样
    `edit --init fish --interactive | source` 才不会被提示语打断。
    有 hook 时（= 当前终端连着某个窗口）回车表示那个窗口；没有 hook 就没有
    当前窗口，只能输编号。q / EOF / 认不出的输入都算取消。

    --init 之外也能挑（edit --interactive <文件>）：挑完由 main 把 socket
    写回环境，之后打开文件就走那个窗口。

    有 fzf 时先用它（use_fzf()）：它的 UI 走 stderr，不碰留给片段的 stdout。
    在 fzf 里 Esc / Ctrl-C 就是取消 —— 和下面按 q 一样的收场，不再问一遍；
    只有"拉不起来 / 出错 / 认出的行没编号"才落回编号输入。
    """

    current = current_socket()

    if use_fzf():
        picked = fzf_pick(socks)
        if picked is FZF_CANCELLED:
            sys.exit(EDIT_NO_WINDOW_PICKED)      # Esc / Ctrl-C：Esc 到哪都是"退出"，别再问一遍
        if picked:
            return picked

    sys.stderr.write('\n'.join(format_sockets(socks, current, colored)) + '\n')
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
        sys.exit(EDIT_NO_WINDOW_PICKED)

    return chosen

# 链接的样子：scheme://…（http / https / file…），外加 mailto: / tel: 这两个不带 // 的。
# 判据只有两处用：normalize 的位置参数（像链接就交给浏览器）与 main 里的报错，所以
# 不像链接的参数照旧当文件名 —— 不改写它，也别悄悄塞进 fileURIs（那会变成
# file:///当前目录/https:/… 这种畸形路径）。
# 不认 localhost:8080/x（没有 scheme）：那种写全 https:// 就好。
URI_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*://|mailto:|tel:)')

def is_uri(s: str) -> bool:
    """像个链接吗：scheme://…（或 mailto: / tel:）

    >>> is_uri('https://fishshell.com/docs/4.9/cmds/abbr.html')
    True
    >>> is_uri('file:///tmp/a.txt')
    True
    >>> is_uri('mailto:a@b.c')
    True
    >>> is_uri('a.txt')
    False
    >>> is_uri('a.txt:3')                   # 别把 文件:行号 当链接
    False
    >>> is_uri('localhost:8080/x')          # 没有 scheme
    False
    """

    return bool(URI_RE.match(s))


def file_url_to_path(url: str) -> str:
    """file:// 链接 -> 本地路径（percent 编码解掉），跟 vim 的 file:// 一个意思

    只认本机：主机部分必须为空（file:///abs/path）或 localhost。写成 file://host/path
    的是"另一台机器上的文件"，那不是本地路径，报错说清楚——别猜成相对路径。

    >>> file_url_to_path('file:///a/b.txt')
    '/a/b.txt'
    >>> file_url_to_path('file://localhost/a/b.txt')
    '/a/b.txt'
    >>> file_url_to_path('file:///a/b%20c.txt')     # percent 编码
    '/a/b c.txt'
    >>> file_url_to_path('file:///a/b.txt?x=1')     # query 对本地文件没意义，丢掉
    '/a/b.txt'
    """

    parts = urllib.parse.urlsplit(url)

    if parts.netloc not in ('', 'localhost'):
        raise NormalizeError('file:// 带了主机名 %s，edit 只认本机路径'
                             '（要的是 file:///绝对路径）' % parts.netloc)

    return urllib.parse.unquote(parts.path)


def positional_token(a: str) -> Token:
    """位置参数 -> token：先认链接，剩下的走 arg_token（跳转 / 目录 / 文件）

    放在 normalize 后面定义、却由它调用（运行期解析，模块加载顺序无所谓），是为了让
    链接那套判据（is_uri / file_url_to_path）留在 URI_RE 那一组里，不拆到两处。

    file:// 落回本地路径后照旧交给 arg_token，所以 file:///p/a.txt:12 照样跳行 ——
    与 vim 的 file:// 一样，链接只是另一种写法，不是另一类东西。

    >>> positional_token('https://example.com')
    ('external', 'https://example.com')
    >>> positional_token('file:///a/b.txt')
    ('file', '/a/b.txt')
    >>> positional_token('a.txt:3')
    ('goto', 'a.txt', '3', None)
    """

    if is_uri(a):
        if a.startswith('file:'):
            return arg_token(file_url_to_path(a))

        return ('external', a)

    return arg_token(a)


class OpenExternalMsg(TypedDict):
    """openExternal 报文：交给系统浏览器打开，不是编辑器里的标签页"""

    type: Literal['openExternal']
    uris: list[str]


def open_external_msg(uris: list[str]) -> OpenExternalMsg:
    """链接 -> openExternal 报文（字段就是 CLI 发的那两个，见 fixtures 的 open-external）

    取值原样发，不学 CLI 那一步规范化（它把 https://example.com 写成
    https://example.com/ —— URI.parse 再 toString 补的斜杠）：server 端自己会
    parse（openExternal 里只有 scheme 是 file 的走解析，其余整串转交），补不补都一样。

    >>> open_external_msg(['https://fishshell.com/docs/'])
    {'type': 'openExternal', 'uris': ['https://fishshell.com/docs/']}
    >>> open_external_msg(['a', 'b'])['uris']
    ['a', 'b']
    """

    return {'type': 'openExternal', 'uris': list(uris)}


# BROWSER 写的是自己时就跳过：BROWSER='edit' 又正好没有窗口可直连时，
# 一路 exec 回自己会一圈接一圈停不下来（链接 edit 自己就认，所以这个自指真会绕）
EDIT_NAMES = ('edit', 'edit.py')
# IDE 自家的 browser.sh（macOS / Linux remote 的 helper 都叫这个）内部还是调
# server-cli.js -> 同一个 socket，等于把直连失败换个进程再犯一遍，没有任何收益；
# 认出就跳过，和 EDIT_NAMES 同一类问题（"别回退给自己人"）
BROWSER_NAMES = ('browser.sh',)


def find_browser() -> list[str] | None:
    """打开链接的兜底程序：$BROWSER（可带参数），再是 xdg-open / open

    BROWSER 的写法和 fish 的 help 一致：整串按 shell 词切开，链接追加在后面
    （`BROWSER='edit'` -> `edit <链接>`，而链接 edit 自己就认得出来）。

    >>> os.environ['BROWSER'] = 'true -a'
    >>> find_browser() == [shutil.which('true'), '-a']
    True
    >>> os.environ['BROWSER'] = 'edit'             # 是自己：跳过，别自己调自己
    >>> find_browser() is None or os.path.basename(find_browser()[0]) != 'edit'
    True
    >>> os.environ['BROWSER'] = '/opt/codebuddy/bin/helpers/browser.sh'  # IDE 自家的
    >>> find_browser() is None or os.path.basename(find_browser()[0]) != 'browser.sh'
    True
    >>> _ = os.environ.pop('BROWSER')
    """

    v = os.environ.get(BROWSER)
    if v:
        cmd = split_cmd(v)

        base = os.path.basename(cmd[0]) if cmd else ''
        if cmd and base not in EDIT_NAMES and base not in BROWSER_NAMES:
            return cmd

    for name in OPENERS:
        path = shutil.which(name)
        if path:
            return [path,]

    return None


def open_uris(uris: list[str], sock: str | None, why_cli: str | None,
              flags: argparse.Namespace, keep_alive: bool = False) -> None:
    """链接的执行：先直连窗口发 openExternal，不行再退 CLI / 系统浏览器

    sock 是 main 已经定下来的"当前窗口"（--interactive / --first 也走那条路）；
    why_cli 是"为什么没直连"，只在选中的是 remote-cli 时用来换一句能照做的提示。

    keep_alive：除了链接后**还有文件要开**。这时 CLI / 浏览器那一级不能
    execv（进程被换掉，main 里的文件就丢了），改成起子进程：fire-and-forget，
    不等它发完 —— 等的话会被 node 启动的那一秒拖住，文件就开晚了；代价是链接与
    文件到达窗口的先后不再保证（只影响"先开浏览器还是先开编辑器"，两个都会开）。
    纯链接（keep_alive=False）照旧 execv，退出码就是浏览器 / CLI 的。

    三条路打印/执行的东西和 main 那两条一致：--dry-run 打报文或命令行，
    真跑的也记进 --debug。
    """

    socket_failed = False   # socket消息发送失败了吗（失败就跳过 code 系 CLI）

    if sock:
        msg = open_external_msg(uris)

        req = 'socket %s %s' % (sock, json.dumps(msg, ensure_ascii=False))

        if flags.dry_run:
            print(req)
            return

        logger.debug('%s', req)
        reply = socket_reply(sock, msg)

        if reply.ok:
            return

        # 窗口这条路不通：说清原因，然后**跳过 code 系 CLI 那一级**（它是同一个 socket，
        # 必然再失败一次，只白起一次 node），直接落系统浏览器 —— 那是另一个通道，
        # 不依赖窗口，链接本来就是"交给系统浏览器"的意思
        sys.stderr.write('edit: 打开链接：%s\n' % reply_failure(reply))
        sys.stderr.write('edit: 改用系统浏览器\n')
        why_cli = reply_failure(reply)
        socket_failed = True

    cli = find_cli()
    kind = cli_kind(cli[0]) if cli else None

    argv: list[str] | None = None

    # code 系自己就有 --openExternal（和直连是同一件事，只是要起一次 node）。
    # socket 直连刚失败就别试它了（同一个 socket，必然再败一次）；另外
    # server 端 remote-cli 只认 IDE 集成终端：环境里没 hook 时它必被拒
    # （find_remote_cli 本会为此不入选，EDIT_CLI 显式点名才绕得过那道自检）
    if cli and kind == CLI_KIND_CODE and not socket_failed:
        # have_remote_cli / current_socket 的 4 种组合（→ 怎么处理）：
        #   有 / 有：IDE 终端里的 server 端 CLI    → 走 --openExternal
        #   有 / 无：搁浅——没 hook，它必被拒        → 提示一句，下面落系统浏览器
        #   无 / 有：IDE 终端里的桌面 code CLI     → 走 --openExternal
        #   无 / 无：桌面 code CLI（electron 桌面 IPC，不靠 hook）→ 走
        if have_remote_cli(os.path.dirname(cli[0])) and not current_socket():
            if why_cli and not flags.dry_run:
                sys.stderr.write(hint_remote_cli(why_cli))
            sys.stderr.write('edit: 改用系统浏览器\n')
        else:
            argv = cli + ['--openExternal'] + uris

    # 别的 CLI（vim / $EDITOR…）没有 openExternal 这个概念，上面搁浅的也一样：
    # 退回系统浏览器 —— 链接不需要按 kind 翻译，原样追加在后面就行
    if argv is None:
        browser = find_browser()
        if not browser:
            sys.exit('edit: 没有 IDE 窗口，也没有能打开链接的程序'
                     '（设 %s，或装 xdg-open）' % BROWSER)

        argv = browser + uris

    line = shlex.join(argv)

    if flags.dry_run:
        print(line)
        return

    if keep_alive:
        # main 后面还要开文件：起子进程而不是 exec，扔后台不阻塞，main 接着开文件
        logger.debug('spawn %s', line)
        subprocess.Popen(argv)

        return

    logger.debug('exec %s', line)
    os.execv(argv[0], argv)


def print_usage():
    """打印本文件开头的用法说明

    --help 是透传给 IDE CLI 的（add_help=False），本程序自己的开关只能从这里查。
    """

    print(__doc__)


# env_flag() 认的"关"：置空、假（false）、关闭（off）、否（no / n）、never（大小写由
# env_flag 统一折成小写）。取值集合 ≈ CMake `if()` 的 false 常量（0 / OFF / NO / FALSE /
# N / IGNORE / NOTFOUND / 空），少了 CMake 特有的 IGNORE / NOTFOUND，多了 'never'
# （--color=never 那派的三态用词，顺手让 EDIT_DEBUG=never 也成立）。
#
# 是**黑名单**不是白名单：不在表里的非空值都算开（EDIT_DEBUG=maybe 也开）。拼错因此
# 落到"开"（看得见）而不是"关"（静默失效）—— 调试类开关宁可误开。真需要白名单的是三态
# 那边（COLOR_CHOICES），所以下面这行留着当备忘，暂时不启用：
#   ENV_ON = ('1', 'true', 'on', 'yes', 'y', 'always')
ENV_OFF = ('', '0', 'false', 'off', 'no', 'n', 'never')

def env_flag(name, default):
    """环境变量开关：没设返回 default，设了就看在不在 ENV_OFF 里（大小写不敏感）

    argparse 的 default 只做真值判断，所以得在这儿先把 '0' / 'FALSE' 这种字符串
    折成 False，否则 EDIT_DEBUG=0 反而会打开调试。

    default 是**必填**的：两个开关的默认值相反（EDIT_DEBUG 没设=关、EDIT_FZF 没设=
    用），写在这儿比留在调用点清楚 —— 老实现对"没设"也返回 False，于是 EDIT_FZF 只能
    在调用点先判 `EDIT_FZF in os.environ` 绕一下，现在不用了。

    >>> env_flag('EDIT_NO_SUCH_VAR', False)     # 没设 = default
    False
    >>> env_flag('EDIT_NO_SUCH_VAR', True)
    True
    """

    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() not in ENV_OFF


def env_color():
    """EDIT_COLOR 的三态取值：只认 auto / always / never，其余（含空和拼错的）回落 auto

    不像 env_flag 那样"非空即开"：这里取值有三个，认不出的值（含拼错的）没有
    "显而易见"的落点，就回到默认的 auto —— 不打搅，也不猜。（三个取值与各种怪输入
    由 test_edit.py 的 EnvColorTest 覆盖：那边能 patch.dict 改环境，doctest 改
    真环境会漏出去。）
    """

    v = os.environ.get(EDIT_COLOR, '').lower()

    return v if v in COLOR_CHOICES else COLOR_AUTO


def build_args():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)

    parser.add_argument('--init', choices=['fish', 'bash'])
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--first', action='store_true')
    parser.add_argument('--prune', action='store_true')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--usage', action='store_true')
    parser.add_argument('--debug', action='store_true',
        default=env_flag(EDIT_DEBUG, False))
    parser.add_argument('--color', nargs='?', const=COLOR_ALWAYS, default=env_color(),
                        choices=COLOR_CHOICES,
                        help='给窗口表和 --debug 的日志上色：不传=auto（仅终端），'
                             '省略取值=always（强制，如 | less -R），never=关闭')

    flags, args = parser.parse_known_args()

    return flags, args


def setup_logging(debug: bool, color: str) -> tuple[bool, bool]:
    # 上色按"这条流"各判一次：窗口表走 stdout，提示与日志走 stderr（--list > f 时
    # stdout 不是终端，但 stderr 可能还是 —— 各看各的）
    color_out = should_color(color, sys.stdout)
    color_err = should_color(color, sys.stderr)

    # 默认 WARNING 而不是 INFO：埋点全是 debug，用户可见的失败走 sys.exit / 手写
    # stderr，所以这里再高一点，等于把"默认静默"变成结构保证 —— 以后谁加了
    # logger.info(...) 也不会漏到用户面前（--debug 才看得见）
    #
    # handler 自己 new 一个（basicConfig 默认那个也是 stderr）：LevelMark 得挂上去，
    # 格式串里的 %(levelMark)s 才有着落；不上色时也挂（color=False），只注入 <D>
    stream = logging.StreamHandler()
    stream.addFilter(LevelMark(color_err))
    stream.addFilter(FilePath(os.environ.get(EDIT_DEBUG, '')))
    stream.setFormatter(logging.Formatter(
        (LOG_FORMAT_COLOR_DEBUG if color_err else LOG_FORMAT_DEBUG)
        if debug else
        (LOG_FORMAT_COLOR if color_err else LOG_FORMAT),
        datefmt="%Y-%m-%d %H:%M:%S"))

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        handlers=[stream],
        force=True,
    )

    # 返回两个流的上色决策：stdout 给窗口表（print_sockets），stderr 给日志与
    # 交互提示（ask_socket）。main 里 unpack 后分别喂给对应出口。
    return color_out, color_err


def main():
    flags, args = build_args()
    if flags.usage:
        if args:
            sys.exit('edit --usage 不接受文件参数')
        print_usage()
        return

    color_out, color_err = setup_logging(flags.debug, flags.color)

    # --prune 和打开文件无关，放在最早：它不碰 tokens，也不该被后面那些检查影响
    if flags.prune:
        if args:
            sys.exit('edit --prune 不接受文件参数')

        if flags.init or flags.list or flags.interactive:
            sys.exit('edit --prune 只清死 socket，不和 --init / --list / --interactive 一起用')

        print_prune(flags.dry_run)
        return

    # 命令行只扫一次：socket 后端吃 to_msg，CLI 后端吃 to_argv（纯函数，先扫出来）
    try:
        tokens = normalize(args)
    except NormalizeError as e:
        sys.exit('edit: %s' % e)

    # -a / -d / --wait 要"有东西可开"才有意义（要目录 / 要两个文件 / 至少要一个文件）：
    # 空着交给 CLI 只会发个空报文，或让 vim 系开个空编辑器。裸调用与 -r / -n 不拦 ——
    # 那些对 code 系是有定义的（开窗口 / 复用窗口 / 新窗口）。放在挑窗口之前，免得
    # --interactive 让用户白挑一次
    misuse, target_flags = action_but_no_target(tokens)
    if misuse:
        sys.exit('edit: %s 后面没有文件或目录' % ' / '.join(target_flags))

    # --wait 等的是"文件编辑器关掉"删 marker：目录没有这一说，marker 没人删
    # wait_marker 会永久挂住。给了错类型目标就自己报错（和 NEEDS_TARGET 那套同一个位置、
    # 同一个理由：误用一律自己报，别交给 CLI 白跑或静默做错）
    misuse, flag = wait_but_no_file(tokens)
    if misuse:
        sys.exit('edit %s: 后面得是文件（--wait 等的是文件编辑器关掉，目录没有这一说）' % flag)

    # -a 不拦类型：上游 buddycn 的 --add 目录、文件都收（文件原样进 fileURIs，见 fixture
    # open-add-file），我们也照收 —— 目录进 folderURIs、文件进 fileURIs（to_msg 里那套
    # 分类）。唯一还拦的是 .code-workspace：那种目标会被服务端改判成"打开工作区"，
    # -a 加不进任何工作区，交给下面 workspace_conflict 报

    # .code-workspace 会被服务端改判成"打开工作区"（server-main.js 的 sU()）：能开，
    # 但打开的不是文件编辑器，于是行号 / --wait / -d / -m / -a 的语义全不成立 ——
    # 尤其 --wait 的 marker 没人删，wait_marker 又没有超时，会永久挂住。同一位置
    # 报错（也在挑窗口之前），别让这些组合静默做错事
    conflict = workspace_conflict(tokens)

    if conflict:
        sys.exit(conflict)

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

        chosen = ask_socket(load_sockets('edit --interactive'), color_err)
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
        print_sockets(color_out)
        return

    if flags.self_test:
        if args:
            sys.exit('edit --self-test 不接受文件参数')

        import doctest            # 只在自检分支 import，不给正常路径加依赖
        import importlib.util

        # 以 'edit' 这个名字再 import 一份来测：--self-test 是当脚本跑的
        # （__name__ == '__main__'），异常类会印成 __main__.NormalizeError，而文档里写的
        # 是 edit.NormalizeError —— doctest 逐字比模块名，凡断言异常信息的那几条就全红。
        # test_edit.py 用的也是这套 importlib 手法。
        spec = importlib.util.spec_from_file_location('edit', os.path.abspath(__file__))
        assert spec is not None and spec.loader is not None    # 本地文件，必然能拿到

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        result = doctest.testmod(module)
        print('edit --self-test: %d passed, %d failed' %
              (result.attempted, result.failed))

        return 1 if result.failed else 0

    # server 端直接和窗口 socket 说话：不用找 CLI，也不用起 node。
    # 翻不了（认不出 / 没给参数）或发失败，就交给下面的 CLI 路径
    sock = current_socket()
    why_cli = None                      # 交回 CLI 的原因（只在 remote-cli 那条路上要用）

    if not sock and flags.first:
        # --first：没 hook 时也开在窗口里 —— 取候选的第一个（等于 --interactive 敲 1，
        # 但不用 stdin，脚本里能用）。直连比交回 remote-cli 强，后者只认集成终端。
        sock = pick_first()

        if not sock:
            sys.exit('edit --first: 没有可用的窗口（桌面版 CLI 自己会复用当前窗口，'
                     '直接 edit <文件> 即可）')

    if not sock:
        # 不在 IDE 终端里本来就该走 CLI，记一条好回答"为什么这次没直连"
        why_cli = '没有 %s' % IPC_HOOK
        logger.debug('no %s, falling back to cli', IPC_HOOK)

    # 链接（https://… / mailto: …）走 openExternal，不进编辑器；file:// 已在 normalize
    # 里落成本地路径，所以摘出来的都是真链接。到这儿才发：窗口已经定下来
    # （--interactive / --first 走的还是上面那条路）
    uris = [t[1] for t in tokens if t[0] == 'external']

    if uris:
        rest: list[Token] = [t for t in tokens if t[0] != 'external']
        # 判一次就够：还有文件要开就告诉 open_uris（那一级得起子进程，不能 exec 把自己
        # 换掉），没有就收工 —— 别算两遍，免得以后两处判据各改一处
        more = has_open_target(rest)
        open_uris(uris, sock, why_cli, flags, more)
        tokens = rest

        if not more:
            return                          # 只给了链接：浏览器开完就收工

    # --wait 要先造 marker（窗口关文件时删它），造不出来就交回 CLI
    marker = make_marker() if sock and has_wait(tokens) else None
    msg = to_msg(tokens, marker) if sock else None
    failed = None                        # 直连发失败的 Reply（None = 没发/没失败）

    if sock and msg is None:
        logger.debug('cannot build socket request, falling back to cli')

    if msg:
        req = 'socket %s %s' % (sock, json.dumps(msg, ensure_ascii=False))

        if flags.dry_run:
            print(req)
            remove_marker(marker)       # 没真发出去，别把临时文件留在 /tmp
            return

        logger.debug('%s', req)         # 真发出去的那一份，和 --dry-run 打的是同一个串
        reply = socket_reply(sock, msg)

        if reply.ok:
            if marker:
                wait_marker(marker)     # 等窗口删 marker（= 等文件被关掉）
            return

        # 失败了。先把临时 marker 收掉（CLI 自己会造一个），退不退交给下面按 kind 判
        remove_marker(marker)
        failed = reply

    # 走到这儿是要交回 CLI 了：它自己会造 marker，我们这个得收回去
    remove_marker(marker)

    cli = find_cli()

    if failed is not None:
        # **code 系 CLI 走的是同一个 socket、同一份报文**，必然再失败一次 —— 不该白起
        # 一次 node，更不该用一句 CLI 的退出码盖掉真正的原因。换个**通道**还有救：
        # $EDITOR 配的 vim / nano 不依赖窗口，那种交回去仍然有意义（老行为）。
        if cli is None or cli_kind(cli[0]) == CLI_KIND_CODE:
            sys.exit('edit: %s' % reply_failure(failed))

        sys.stderr.write('edit: %s；改用 %s\n' % (reply_failure(failed), cli[0]))
        why_cli = reply_failure(failed)

    if not cli:
        sys.exit('找不到 cli（%s）' % ' / '.join(CODE_LIKE + VIM_LIKE))

    # remote-cli 只认 IDE 集成终端：没有可用的 hook 时它必定拒绝（原话就是下一行那句
    # "Command is only available in WSL or inside a Visual Studio Code terminal."）。
    # 换成能照做的提示 —— 只在 remote-cli 这条路上打，vim / $EDITOR 场景一个字不多打
    if why_cli and have_remote_cli(os.path.dirname(cli[0])):
        sys.stderr.write(hint_remote_cli(why_cli))

    # cli 是 argv 列表：[可执行文件, 自己配置里的参数...]（如 EDITOR='vim -u NONE'）
    kind = cli_kind(cli[0])
    argv = cli + to_argv(tokens, kind)     # 按 kind 翻译（EMIT 表）
    line = shlex.join(argv)                # 可以直接复制执行的一行（bash/fish 都认）

    if flags.dry_run:
        print(line)
        return

    logger.debug('exec %s', line)          # 真正执行的命令，和 --dry-run 打的是同一个串
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
