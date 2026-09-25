#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""edit <文件...> —— 在当前 IDE 窗口打开文件

用法：
  edit <文件...>               在当前 IDE 窗口打开文件
  edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
  eval "$(edit --init bash)"   同上（bash / sh / dash）

  注意 fish 下不能写 eval (edit --init fish)：fish 的 eval 会把多行输出
  用空格拼成一条命令，必须用 | source 才能逐行执行。
  另外 --init 要在集成终端里生成（那里才有 hook 和 remote-cli）。

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
import shlex
import shutil
import sys

IPC_HOOK = 'VSCODE_IPC_HOOK_CLI'
CLI_LIST = ('code', 'buddycn', 'trae-cn', 'cursor',)

USAGE = '用法: edit <文件...>'


def find_ipc_hook():
    """取 VSCODE_IPC_HOOK_CLI 环境变量
    """

    return os.environ.get(IPC_HOOK)


def find_remote_cli():
    if not os.environ.get(IPC_HOOK):
        return None

    PATH = os.environ.get('PATH')
    if not PATH:
        return None

    HOME = os.environ.get('HOME')
    if not HOME:
        return None

    for d in PATH.split(os.pathsep):
        if not d:
            continue

        d = d.rstrip(os.sep)

        if not d.startswith(HOME):
            continue

        b = os.path.basename(d)
        if b != 'remote-cli':
            continue

        for i in sorted(os.listdir(d)):
            x = os.path.join(d, i)
            if os.path.isfile(x) and os.access(x, os.X_OK):
                return x

def find_path_cli():
    for i in CLI_LIST:
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
    for i in ('vim', 'vi',):
        cli = shutil.which(i)
        if cli:
            return cli

def find_cli():
    """取 命令行编辑工具

    1. 终端里 PATH 通常就含 <安装目录>/bin/remote-cli，而且排在很前面，
    如果这个目录下有可执行文件，就用它。

    2. 如果 PATH 里没有，就看看 CLI_LIST 中的哪个命令行在 PATH 里，
    如果能找到，就用它。

    3. 如果 PATH 里没有，就看看 VISUAL 和 EDITOR 环境变量，
    如果有，就用它。

    4. 什么都没有，就 fallback 到 vim 或 vi
    """

    for choice in (find_remote_cli, find_path_cli, find_env_cli, find_fallback_cli):
        cli = choice()
        if cli:
            return cli

def print_init_script(shell):
    ipc = find_ipc_hook()
    if not ipc:
        sys.exit('edit --init: 当前终端没有 {}（请在 IDE 集成终端里生成）'.format(IPC_HOOK))

    cli = find_remote_cli()
    if not cli:
        sys.exit('edit --init: 当前终端没找到 {}（请在 IDE 集成终端里生成）'.format(' / '.join(CLI_LIST)))

    dir = os.path.dirname(cli)

    # fish 下只能 `edit --init fish | source`
    # fish 的 eval 会把多行输出用空格拼成一条命令
    if shell == 'fish':
        print('''
set -gx {env} "{ipc}"
if not contains "{dir}" $PATH
    set -p PATH "{dir}"
end
'''.format(env=IPC_HOOK, ipc=ipc, dir=dir))
    else:
        print('''
export {env}="{ipc}"
case ":$PATH:" in
*:"{dir}":*) ;;
*) export PATH="{dir}:$PATH" ;;
esac
'''.format(env=IPC_HOOK, ipc=ipc, dir=dir))

def build_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--init', choices=['fish', 'bash'])
    return parser.parse_known_args()

def main():
    flags, args = build_args()
    if flags.init:
        if args:
            sys.exit('edit --init 不接受文件参数')
        print_init_script(flags.init)
        return

    cli = find_cli()
    if not cli:
        # TODO: 错误信息只列 CLI_LIST，与现在含 $VISUAL/$EDITOR/vim 的链路不符，且几乎不可达
        sys.exit('找不到 cli（%s）' % ' / '.join(CLI_LIST))

    argv = [cli,] + args
    os.execv(cli, argv)

if __name__ == '__main__':
    sys.exit(main())
