#!/usr/bin/env python3
"""edit.py 的回归测试：python3 test_edit.py -v

不碰真实 IDE、不开窗口：
* socket 路径：起一个假窗口（AF_UNIX server），断言 edit 发过去的 JSON 与退出码
* CLI 路径：EDIT_CLI 指到假 CLI，断言 --dry-run 打印的命令行、或它是否真被调用
* 回退：假窗口回 500 / 连上就关，断言 stderr 有提示且假 CLI 真的被执行
* 窗口发现：假 /proc（make_proc）+ 假窗口，测 find_sockets / status 探测 /
  --list / --init；这些在进程内跑，靠 edit.PROC 指到假目录
"""

import glob
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = os.path.join(HERE, 'edit.py')
FIXTURES = os.path.join(HERE, 'fixtures', 'protocol.json')

spec = importlib.util.spec_from_file_location('edit', EDIT)

assert spec is not None and spec.loader is not None      # 本地文件，必然能拿到

edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edit)


class FakeWindow:
    """假装是一个 IDE 窗口的 socket：收 POST，按设定回复"""

    def __init__(self, code=200, body='{}', silent=False, path=None,
                 unlink_marker=False):
        # path 给定就绑在指定路径上：find_sockets 只认名字里带 vscode-ipc- 的 socket
        self.path = path or tempfile.mktemp(prefix='fake-window-', suffix='.sock')
        self.code = code
        self.body = body
        self.silent = silent
        self.unlink_marker = unlink_marker
        self.requests = []

        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._srv.settimeout(5)

        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return          # 服务器关了

            try:
                with conn:
                    conn.settimeout(5)

                    msg = self._read(conn)
                    if msg is not None:
                        self.requests.append(msg)

                        # 假装用户把文件关了：窗口就是删 marker 来通知 CLI 的
                        if self.unlink_marker and msg.get('waitMarkerFilePath'):
                            try:
                                os.unlink(msg['waitMarkerFilePath'])
                            except OSError:
                                pass

                    if self.silent:
                        continue    # 连上就断，测"连不上"那条路

                    conn.sendall(self._reply())
            except OSError:
                pass

    @staticmethod
    def _read(conn):
        """读一个 HTTP 请求，返回解析后的 JSON（读不到返回 None）"""

        buf = b''

        while b'\r\n\r\n' not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                return None
            buf += chunk

        head, _, body = buf.partition(b'\r\n\r\n')

        m = re.search(rb'content-length:\s*(\d+)', head, re.I)
        need = int(m.group(1)) if m else 0

        while len(body) < need:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk

        try:
            return json.loads(body[:need].decode())
        except ValueError:
            return None

    def _reply(self):
        body = self.body.encode()
        head = ('HTTP/1.1 %d X\r\ncontent-type: application/json\r\n'
                'content-length: %d\r\n\r\n' % (self.code, len(body)))

        return head.encode() + body

    def close(self):
        self._srv.close()

        if os.path.exists(self.path):
            os.unlink(self.path)


class EditCase(unittest.TestCase):
    """公共环境：临时目录、假 CLI，以及跑 edit 的助手"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

        self.a = self._touch('a.txt')
        self.b = self._touch('b.txt')
        self.spaced = os.path.join(self.dir, 'probe dir')
        os.mkdir(self.spaced)
        self.spaced_file = self._touch(os.path.join('probe dir', 'a b.txt'))

        self.wins = []
        self.win = None
        self.cli_out = os.path.join(self.dir, 'cli-args.txt')
        self.fake_cli = self._fake_cli()

    def tearDown(self):
        for w in self.wins:
            w.close()

        self.tmp.cleanup()

    def add_window(self, **kw):
        """起一个假窗口并登记，tearDown 统一关"""

        w = FakeWindow(**kw)
        self.wins.append(w)

        return w

    def _touch(self, name):
        path = os.path.join(self.dir, name)

        with open(path, 'w') as f:
            f.write('x\n')

        return path

    def _fake_cli(self):
        """假 CLI：把收到的参数写进 $FAKE_CLI_OUT，再以 7 退出（好辨认）"""

        path = os.path.join(self.dir, 'fake-cli')

        with open(path, 'w') as f:
            f.write('#!/bin/sh\nprintf "%s" "$*" > "$FAKE_CLI_OUT"\nexit 7\n')

        os.chmod(path, 0o755)

        return path

    def run_edit(self, *args, hook=None):
        env = dict(os.environ)
        env.pop(edit.IPC_HOOK, None)
        env['EDIT_CLI'] = self.fake_cli
        env['FAKE_CLI_OUT'] = self.cli_out

        if hook is not None:
            env[edit.IPC_HOOK] = hook

        return subprocess.run([sys.executable, EDIT, *args], env=env,
                              capture_output=True, text=True, timeout=20)

    def open_msg(self, *args, **kw):
        """起假窗口，真发一次请求，返回窗口收到的报文"""

        self.win = self.add_window(**kw)
        proc = self.run_edit(*args, hook=self.win.path)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.win.requests,
                        '假窗口没收到请求（stderr: %s）' % proc.stderr)
        self.assertFalse(os.path.exists(self.cli_out), '不该回退到 CLI')

        return self.win.requests[-1]

    def cli_args(self):
        """假 CLI 收到的参数；没被调用过就是 None"""

        if not os.path.exists(self.cli_out):
            return None

        with open(self.cli_out) as f:
            return f.read()


class SocketOpenTest(EditCase):
    """能直连的那些参数 -> open 报文"""

    def test_plain_file(self):
        msg = self.open_msg(self.a)

        self.assertEqual(msg['fileURIs'], ['file://' + self.a])
        self.assertEqual(msg['gotoLineMode'], False)
        self.assertEqual(msg['folderURIs'], [])

    def test_goto_line(self):
        msg = self.open_msg(self.a + ':3')

        self.assertEqual(msg['fileURIs'], ['file://' + self.a + ':3'])
        self.assertEqual(msg['gotoLineMode'], True)

    def test_goto_line_col(self):
        msg = self.open_msg(self.a + ':3:5')

        self.assertEqual(msg['fileURIs'], ['file://' + self.a + ':3:5'])

    def test_flags(self):
        for flag, field in (('-r', 'forceReuseWindow'),
                            ('--reuse-window', 'forceReuseWindow'),
                            ('-n', 'forceNewWindow'),
                            ('-a', 'addMode')):
            with self.subTest(flag):
                msg = self.open_msg(flag, self.a)

                self.assertEqual(msg[field], True)
                self.assertEqual(msg['fileURIs'], ['file://' + self.a])

    def test_diff(self):
        msg = self.open_msg('-d', self.a, self.b)

        self.assertEqual(msg['diffMode'], True)
        self.assertEqual(msg['fileURIs'],
                         ['file://' + self.a, 'file://' + self.b])

    def test_folder(self):
        """目录进 folderURIs，且路径里的空格要转义"""

        msg = self.open_msg(self.spaced)

        self.assertEqual(msg['folderURIs'],
                         ['file://' + self.spaced.replace(' ', '%20')])
        self.assertEqual(msg['fileURIs'], [])

    def test_uri_encoding(self):
        msg = self.open_msg(self.spaced_file)

        self.assertEqual(msg['fileURIs'],
                         ['file://' + self.spaced_file.replace(' ', '%20')])

    def test_shape(self):
        """固定字段：remote-cli 发出来的也就是这几个"""

        msg = self.open_msg(self.a)

        self.assertEqual(msg['type'], 'open')
        self.assertEqual(msg['mergeMode'], False)
        self.assertEqual(msg['addMode'], False)
        self.assertEqual(msg['forceNewWindow'], False)


class GotoTest(EditCase):
    """-g / --goto 被忽略：行号只认位置参数写法（报文见 open-goto-short）"""

    def test_forms(self):
        """空格写法按位置参数处理：等价，且 :3 不被转义成 %3A"""

        want = ['file://' + self.a + ':3']

        for args in (['-g', self.a + ':3'],
                     ['--goto', self.a + ':3']):
            with self.subTest(args):
                msg = edit.open_request(args)

                self.assertEqual(msg['fileURIs'], want)
                self.assertEqual(msg['gotoLineMode'], True)

    def test_without_line(self):
        """取值没有行号：就是个普通文件（-g 不带来任何东西）"""

        msg = edit.open_request(['-g', self.a])

        self.assertEqual(msg['fileURIs'], ['file://' + self.a])
        self.assertEqual(msg['gotoLineMode'], False)

    def test_flag_is_ignored(self):
        """-g / --goto 不消费参数、也不留下 token：后面是选项就等于没有它"""

        self.assertEqual(edit.normalize(['-g']), [])
        self.assertEqual(edit.normalize(['--goto']), [])
        self.assertEqual(edit.normalize(['-g', '-r', self.a + ':3']),
                         [('opt', '-r', 'forceReuseWindow', []),
                          ('goto', self.a, '3', None)])

        for args in (['-g'], ['-g', '-r'], ['-r', '-g']):
            with self.subTest(args):
                self.assertIsNone(edit.open_request(args))

    def test_inline_form_is_not_special_cased(self):
        """--goto=X / -g=X 不特判：跟别的"不认识的选项"一样交给 CLI"""

        for args in (['--goto=-r'], ['--goto='], ['-g=' + self.a]):
            with self.subTest(args):
                self.assertEqual(edit.normalize(args), [('other', args[0])])

        self.assertIsNone(edit.open_request(['--goto=' + self.a + ':3']))

    def test_mixes_with_flags(self):
        msg = edit.open_request(['-r', '-g', self.a + ':3'])

        self.assertEqual(msg['forceReuseWindow'], True)
        self.assertEqual(msg['fileURIs'], ['file://' + self.a + ':3'])

    def test_sent_to_window(self):
        """端到端：真发给假窗口，不回退 CLI"""

        msg = self.open_msg('-g', self.a + ':3')

        self.assertEqual(msg['fileURIs'], ['file://' + self.a + ':3'])
        self.assertEqual(msg['gotoLineMode'], True)


class MergeTest(EditCase):
    """-m / --merge：吃 4 个路径（path1 path2 base result），见 open-merge-short"""

    def test_forms(self):
        """-m 与 --merge 等价：4 个路径原样进 fileURIs，并置 mergeMode"""

        want = ['file://' + p for p in (self.a, self.b, self.a, self.b)]

        for flag in ('-m', '--merge'):
            with self.subTest(flag):
                msg = edit.open_request([flag, self.a, self.b, self.a, self.b])

                self.assertEqual(msg['fileURIs'], want)
                self.assertEqual(msg['mergeMode'], True)
                self.assertEqual(msg['diffMode'], False)

    def test_relative_becomes_absolute(self):
        """相对路径按 cwd 解成绝对路径 —— CLI 也是这么发的（capture 里试过）"""

        msg = edit.open_request(['-m', 'a', 'b', 'base', 'result'])

        self.assertEqual(msg['fileURIs'],
                         ['file://' + os.path.join(os.getcwd(), n)
                          for n in ('a', 'b', 'base', 'result')])

    def test_too_few_paths_falls_back(self):
        """不足 4 个路径：交回 CLI 让它自己报错"""

        for args in (['-m'], ['-m', self.a], ['-m', self.a, self.b],
                     ['-m', self.a, self.b, self.a]):
            with self.subTest(args):
                self.assertIsNone(edit.open_request(args))

    def test_value_is_option_falls_back(self):
        """4 个取值里混进一个选项：同样交回 CLI"""

        self.assertIsNone(edit.open_request(['-m', self.a, '-r', self.b, self.a]))

    def test_mixes_with_flags(self):
        msg = edit.open_request(['-r', '-m', self.a, self.b, self.a, self.b])

        self.assertEqual(msg['forceReuseWindow'], True)
        self.assertEqual(msg['mergeMode'], True)
        self.assertEqual(msg['fileURIs'],
                         ['file://' + p for p in (self.a, self.b, self.a, self.b)])

    def test_wait_marker(self):
        """--wait -m …：4 个路径也算"有文件"，带上 marker 就能直连"""

        msg = edit.open_request(['--wait', '-m', self.a, self.b, self.a, self.b], '/m')

        self.assertEqual(msg['waitMarkerFilePath'], '/m')
        self.assertEqual(msg['mergeMode'], True)

    def test_sent_to_window(self):
        """端到端：真发给假窗口，不回退 CLI"""

        msg = self.open_msg('-m', self.a, self.b, self.a, self.b)

        self.assertEqual(msg['mergeMode'], True)
        self.assertEqual(msg['fileURIs'],
                         ['file://' + p for p in (self.a, self.b, self.a, self.b)])


class CliArgvTest(EditCase):
    """CLI 后端：同一份 token 按 kind 翻译成不同的命令行"""

    def test_goto_per_kind(self):
        """行号：code 插 --goto，vim 用 +行号 前置，认不出的只传文件"""

        arg = 'a.txt:12'

        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_CODE), ['--goto', arg])
        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_VIM), ['+12', 'a.txt'])
        self.assertEqual(edit.cli_argv([arg], None), ['a.txt'])

    def test_column_per_kind(self):
        """列号：nano 用逗号、emacs 系用冒号、vim 不带（只有 vim 不带列）"""

        arg = 'a.txt:12:3'

        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_CODE), ['--goto', arg])
        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_VIM), ['+12', 'a.txt'])
        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_NANO), ['+12,3', 'a.txt'])
        self.assertEqual(edit.cli_argv([arg], edit.CLI_KIND_EMACS), ['+12:3', 'a.txt'])
        self.assertEqual(edit.cli_argv([arg], None), ['a.txt'])

    def test_column_with_goto_flag(self):
        """-g 的取值带列：走位置参数那套，列号照样翻出来"""

        self.assertEqual(edit.cli_argv(['-g', 'a.txt:12:3'], edit.CLI_KIND_NANO),
                         ['+12,3', 'a.txt'])
        self.assertEqual(edit.cli_argv(['--goto', 'a.txt:12:3'], edit.CLI_KIND_EMACS),
                         ['+12:3', 'a.txt'])

    def test_token_shape_guard(self):
        """形状外的 token 直接炸：token 联合是穷尽的，漏一种就该在这儿暴露

        故意塞一个形状不对的 token —— 两处都得 ignore 类型检查，因为要测的正是
        "运行期真收到怪形状"时 case _ 有没有兜住。
        """

        bogus = [('bogus', 'x', 'y')]

        with self.assertRaises(AssertionError):
            edit.to_argv(bogus, edit.CLI_KIND_CODE)      # type: ignore[arg-type]

        with self.assertRaises(AssertionError):
            edit.to_msg(bogus)                           # type: ignore[arg-type]

    def test_plus_kinds(self):
        """nano / emacs / emacsclient 各成一类，行号写法与 vim 相同（+N 前置）"""

        for name, kind in (('nano', edit.CLI_KIND_NANO),
                           ('emacs', edit.CLI_KIND_EMACS),
                           ('emacsclient', edit.CLI_KIND_EMACS)):
            with self.subTest(name):
                self.assertEqual(edit.cli_kind('/usr/bin/' + name), kind)
                self.assertEqual(edit.cli_argv(['a.txt:12'], kind), ['+12', 'a.txt'])
                self.assertEqual(edit.cli_argv(['-g', 'a.txt:12'], kind),
                                 ['+12', 'a.txt'])
                self.assertEqual(edit.cli_argv(['--wait', 'a.txt'], kind), ['a.txt'])

    def test_goto_flag_is_ignored(self):
        """-g / --goto 被忽略：code 系照样插入自己的 --goto"""

        for args in (['-g', 'a.txt:12'], ['--goto', 'a.txt:12']):
            with self.subTest(args):
                self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_CODE),
                                 ['--goto', 'a.txt:12'])

        # 内联写法不特判：原样交给 CLI
        self.assertEqual(edit.cli_argv(['--goto=a.txt:12'], edit.CLI_KIND_CODE),
                         ['--goto=a.txt:12'])

    def test_goto_flag_translated_for_vim(self):
        """vim 系不认 -g：按 +行号 翻一遍（vim -g 是启动 GUI，会 E25 报错退出 2）"""

        for args in (['-g', 'a.txt:12'], ['--goto', 'a.txt:12']):
            with self.subTest(args):
                self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_VIM),
                                 ['+12', 'a.txt'])

        self.assertEqual(edit.cli_argv(['--goto=a.txt:12'], edit.CLI_KIND_VIM),
                         ['--goto=a.txt:12'])

    def test_goto_flag_without_line(self):
        """-g 的取值没有行号：只剩文件（不能把文件一起丢了）"""

        for kind in (edit.CLI_KIND_VIM, edit.CLI_KIND_NANO, edit.CLI_KIND_EMACS, None):
            with self.subTest(kind):
                self.assertEqual(edit.cli_argv(['-g', 'a.txt'], kind), ['a.txt'])
                self.assertEqual(edit.cli_argv(['--goto', 'a.txt'], kind), ['a.txt'])

    def test_many_targets_each_get_their_own_goto(self):
        """多个目标各插一份 --goto：实测 CLI 的 -g 可重复，报文是累加的"""

        args = ['a.txt:3', '-g', 'b.txt:9']

        self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_VIM),
                         ['+3', 'a.txt', '+9', 'b.txt'])
        self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_CODE),
                         ['--goto', 'a.txt:3', '--goto', 'b.txt:9'])

    def test_unknown_options_keep_their_place(self):
        """认不出的原样透传，而且位置不变（回退时交给 CLI 的就是它）"""

        self.assertEqual(
            edit.cli_argv(['--locale', 'zh-cn', '-r', 'a.txt:3'], edit.CLI_KIND_CODE),
            ['--locale', 'zh-cn', '-r', '--goto', 'a.txt:3'])

    def test_abspath_only_for_code(self):
        """存在的路径：code 系转绝对（remote-cli 是代理），vim 系保持相对"""

        rel = os.path.relpath(self.a)

        self.assertEqual(edit.cli_argv([rel], edit.CLI_KIND_CODE), [self.a])
        self.assertEqual(edit.cli_argv([rel], edit.CLI_KIND_VIM), [rel])

    def test_wait_dropped_unless_code(self):
        self.assertEqual(edit.cli_argv(['--wait', self.a], edit.CLI_KIND_VIM), [self.a])
        self.assertEqual(edit.cli_argv(['-w', self.a], None), [self.a])

    def test_code_switches_dropped(self):
        """-r / -n / -a：非 code 系各有别解（vim -r 恢复交换文件、nano -n 只写不读…），一律摘掉"""

        for kind in (edit.CLI_KIND_VIM, edit.CLI_KIND_NANO, edit.CLI_KIND_EMACS, None):
            for flag in ('-r', '-n', '-a',
                         '--reuse-window', '--new-window', '--add'):
                with self.subTest((kind, flag)):
                    self.assertEqual(edit.cli_argv([flag, self.a], kind), [self.a])

    def test_diff_kept_for_code_and_vim(self):
        """-d：code 系和 vim 都是 diff 模式（等价，保留）；nano / emacs / 认不出的摘掉"""

        args = ['-d', self.a, self.b]

        self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_CODE), args)
        self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_VIM), args)

        for kind in (edit.CLI_KIND_NANO, edit.CLI_KIND_EMACS, None):
            with self.subTest(kind):
                self.assertEqual(edit.cli_argv(args, kind), [self.a, self.b])

    def test_merge_keeps_its_paths(self):
        """-m：合并没有等价物 —— 开关丢掉，四个路径照开（不能把文件一起丢了）"""

        args = ['-m', self.a, self.b, self.a, self.b]
        paths = [self.a, self.b, self.a, self.b]

        self.assertEqual(edit.cli_argv(args, edit.CLI_KIND_CODE), args)

        for kind in (edit.CLI_KIND_VIM, edit.CLI_KIND_NANO, edit.CLI_KIND_EMACS, None):
            with self.subTest(kind):
                self.assertEqual(edit.cli_argv(args, kind), paths)

    def test_literal_after_dashdash(self):
        self.assertEqual(edit.cli_argv(['--', '-w', 'a.txt:3'], edit.CLI_KIND_CODE),
                         ['--', '-w', 'a.txt:3'])

    def test_future_remote_cli_like_code(self):
        """remote-cli 里的新产品名也按 code 系：行号翻成 --goto"""

        install = os.path.join(self.dir, 'future-ide')
        cli_dir = os.path.join(install, 'bin', 'remote-cli')
        os.makedirs(cli_dir)
        cli = os.path.join(cli_dir, 'future-code')

        for path in (cli, os.path.join(install, 'node')):
            with open(path, 'w'):
                pass
            os.chmod(path, 0o755)

        kind = edit.cli_kind(cli)
        self.assertEqual(kind, edit.CLI_KIND_CODE)

        arg = 'a.txt:12:3'
        self.assertEqual(edit.cli_argv(['-g', arg], kind), ['--goto', arg])


class CliKindTest(EditCase):
    """认 CLI 是哪一类：basename 查表 + `<安装目录>/bin/remote-cli` 结构兜底

    结构兜底要求"上两级有可执行的 node"（防误判，见 NOTES）。find_remote_cli 复用
    同一个判据（have_remote_cli），所以一起测。
    """

    def make_install(self, product='future-code', node=True, mode=0o755, name='ide'):
        """造 server 端安装目录，返回 <…>/bin/remote-cli/<产品>

        node=False 干脆不放；mode 给 0o644 就是造一个不可执行的。
        """

        install = os.path.join(self.dir, name)
        cli = os.path.join(install, 'bin', 'remote-cli', product)
        os.makedirs(os.path.dirname(cli), exist_ok=True)

        with open(cli, 'w'):
            pass
        os.chmod(cli, 0o755)

        if node:
            with open(os.path.join(install, 'node'), 'w'):
                pass
            os.chmod(os.path.join(install, 'node'), mode)

        return cli

    def test_structure_without_node_is_unknown(self):
        """结构对但没 node：不当 code 系（判据是防误判，不能只看目录名）"""

        cli = self.make_install(node=False)

        self.assertFalse(edit.have_remote_cli(os.path.dirname(cli)))
        self.assertIsNone(edit.cli_kind(cli))
        self.assertEqual(edit.cli_argv(['-g', 'a.txt:12:3'], None), ['a.txt'])

    def test_node_must_be_executable(self):
        cli = self.make_install(mode=0o644)

        self.assertFalse(edit.have_remote_cli(os.path.dirname(cli)))
        self.assertIsNone(edit.cli_kind(cli))

    def test_have_remote_cli_needs_the_dir_name(self):
        """目录名不是 remote-cli（哪怕上两级真有 node）：不认"""

        self.make_install()
        other = os.path.join(self.dir, 'ide', 'bin', 'not-remote-cli')
        os.makedirs(other)

        for d in (other, os.path.join(self.dir, 'ide'),
                  os.path.join(self.dir, 'ide', 'bin'), self.dir):
            with self.subTest(d):
                self.assertFalse(edit.have_remote_cli(d))

    def test_basename_wins_over_structure(self):
        """表里认识的名字优先：remote-cli 结构里的 vim 还是 vim"""

        cli = self.make_install(product='vim')

        self.assertEqual(edit.cli_kind(cli), edit.CLI_KIND_VIM)

    def test_unknown_name_outside_structure(self):
        cli = self._touch('weird-editor')
        os.chmod(cli, 0o755)

        self.assertIsNone(edit.cli_kind(cli))

    def test_find_remote_cli(self):
        """PATH 里有 remote-cli 且有 hook：就用它"""

        cli = self.make_install()

        with patch.dict(os.environ, {edit.IPC_HOOK: '/tmp/fake.sock',
                                     'PATH': os.path.dirname(cli)}, clear=True):
            self.assertEqual(edit.find_remote_cli(), [cli])

    def test_find_remote_cli_needs_hook(self):
        """没有 VSCODE_IPC_HOOK_CLI 就不找（remote-cli 缺 hook 自己会报错）"""

        cli = self.make_install()

        with patch.dict(os.environ, {'PATH': os.path.dirname(cli)}, clear=True):
            self.assertIsNone(edit.find_remote_cli())

    def test_find_remote_cli_skips_dir_without_node(self):
        """PATH 里那个没 node 的不算，继续往后找（和 cli_kind 同一判据）"""

        bad = self.make_install(node=False, name='bad-ide')
        good = self.make_install(name='good-ide')
        path = os.pathsep.join((os.path.dirname(bad), os.path.dirname(good)))

        with patch.dict(os.environ, {edit.IPC_HOOK: '/tmp/fake.sock',
                                     'PATH': path}, clear=True):
            self.assertEqual(edit.find_remote_cli(), [good])


class DryRunTest(EditCase):
    """--dry-run：能直连时打 JSON，翻不了时打命令行"""

    def test_socket_json(self):
        self.win = self.add_window()
        proc = self.run_edit('--dry-run', self.a, hook=self.win.path)

        self.assertEqual(proc.returncode, 0, proc.stderr)

        head, _, rest = proc.stdout.strip().partition(' ')
        self.assertEqual(head, 'socket')

        sock, _, payload = rest.partition(' ')
        self.assertEqual(sock, self.win.path)
        self.assertEqual(json.loads(payload)['fileURIs'], ['file://' + self.a])
        self.assertEqual(self.win.requests, [], '--dry-run 不该真的发请求')

    def test_goto_is_direct(self):
        """-g 现在能直连：--dry-run 打的是报文，不是命令行"""

        self.win = self.add_window()
        proc = self.run_edit('--dry-run', '-g', self.a + ':3', hook=self.win.path)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        head, _, rest = proc.stdout.strip().partition(' ')
        self.assertEqual(head, 'socket')

        payload = json.loads(rest.partition(' ')[2])
        self.assertEqual(payload['fileURIs'], ['file://' + self.a + ':3'])
        self.assertEqual(payload['gotoLineMode'], True)
        self.assertEqual(self.win.requests, [])

    def test_cli_line(self):
        """没有 socket 时交回 CLI：判不出是哪一类就不认行号，只传文件"""

        proc = self.run_edit('--dry-run', '-g', self.a + ':3')

        self.assertEqual(proc.stdout.split()[0], self.fake_cli)
        self.assertEqual(proc.stdout.split()[1:], [self.a])

    def test_cli_line_code_kind(self):
        """假 CLI 改叫 buddycn（判成 code 系）：按 code 的写法插 --goto"""

        code_cli = os.path.join(self.dir, 'buddycn')

        with open(code_cli, 'w') as f:
            f.write('#!/bin/sh\nprintf "%s" "$*" > "$FAKE_CLI_OUT"\nexit 7\n')

        os.chmod(code_cli, 0o755)
        self.fake_cli = code_cli

        proc = self.run_edit('--dry-run', '-g', self.a + ':3')

        self.assertEqual(proc.stdout.split(),
                         [code_cli, '--goto', self.a + ':3'])


class FallbackTest(EditCase):
    """socket 不行时回退 CLI"""

    def assert_fell_back(self, proc):
        self.assertIn('socket 打不开', proc.stderr)
        self.assertEqual(proc.returncode, 7)            # 假 CLI 的退出码
        self.assertEqual(self.cli_args(), self.a)       # 假 CLI 真被调用了

    def test_http_500(self):
        self.win = self.add_window(code=500, body='boom')

        self.assert_fell_back(self.run_edit(self.a, hook=self.win.path))

    def test_window_closes(self):
        self.win = self.add_window(silent=True)

        self.assert_fell_back(self.run_edit(self.a, hook=self.win.path))

    def test_untranslatable_args(self):
        """--wait / 取值不够的 --merge / 无参数 / 没有 socket：一律交给 CLI"""

        for args in (['--wait', self.a], ['--merge', self.a], []):
            with self.subTest(args):
                proc = self.run_edit(*args)

                self.assertEqual(proc.returncode, 7, proc.stderr)
                self.assertNotIn('socket 打不开', proc.stderr)


class NoTargetTest(EditCase):
    """-a / -d / --wait 空着（没有目标）→ 直接提示退出，不交给 CLI"""

    def test_needs_target_options_error(self):
        for args in (['-d'], ['--diff'], ['-a'], ['--add'], ['--wait'], ['-w'],
                     ['-r', '-d']):
            with self.subTest(args):
                proc = self.run_edit(*args)

                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn('没有文件或目录', proc.stderr)
                self.assertIsNone(self.cli_args(), '不该交给 CLI')

    def test_has_target_is_fine(self):
        """有目标就不拦：-d 跟两个文件、--wait 跟一个文件、-a 跟目录"""

        for args in (['-d', self.a, self.b], ['--wait', self.a], ['-a', self.dir]):
            with self.subTest(args):
                proc = self.run_edit(*args)

                self.assertEqual(proc.returncode, 7, proc.stderr)   # 交给假 CLI
                self.assertNotIn('没有文件或目录', proc.stderr)

    def test_bare_and_window_flags_still_fall_back(self):
        """裸调用 / 只给 -r / -n / -g：照旧交给 CLI（code 系的开窗口/复用窗口有定义）"""

        for args in ([], ['-r'], ['--reuse-window'], ['-n'], ['-g']):
            with self.subTest(args):
                proc = self.run_edit(*args)

                self.assertEqual(proc.returncode, 7, proc.stderr)
                self.assertNotIn('没有文件或目录', proc.stderr)

    def test_unknown_token_counts_as_target(self):
        """-- 之后的字面量算"有东西"：交回 CLI 让它去理解，不能报错"""

        proc = self.run_edit('-d', '--', 'a.txt')

        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertNotIn('没有文件或目录', proc.stderr)

    def test_error_comes_before_picking_a_window(self):
        """判定在挑窗口之前：--interactive 不该让用户白挑一次"""

        proc = self.run_edit('--interactive', '-d')

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('-d 后面没有文件或目录', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)


def load_fixtures():
    """fixtures/protocol.json：真 CLI 发出来的报文快照（tools/capture_cli.py 抓的）"""

    with open(FIXTURES, encoding='utf-8') as f:
        return json.load(f)


def status_body(workspace, authority='ssh-remote+7'):
    """假窗口答 status 时用的正文：JSON 字符串，里面含窗口自己的 argv

    probe_workspaces 就是从这行 'Process Argv: --remote …' 里抠 workspace 的。
    """

    return json.dumps('Process Argv:     --remote %s %s' % (authority, workspace))


def make_proc(root, windows):
    """造一个最小 /proc，让 find_sockets 能在假目录上跑

    windows: [(socket 路径, pid, 安装目录)]。安装目录里补上 node 与
    bin/remote-cli/buddycn —— find_sockets 的判据就是这两样的结构，
    所以假进程表只要结构对得上就够用了。
    """

    proc = os.path.join(root, 'proc')
    os.makedirs(os.path.join(proc, 'net'))

    lines = ['Num RefCount Protocol Flags Type St Inode Path']

    for n, (sock, pid, install) in enumerate(windows, 1):
        ino = 10000 + n
        # 照真实 /proc/net/unix 的行写：Path 在最后一列，前面的 Inode 要和
        # fd 里 socket:[inode] 对上
        lines.append('%016x: 00000002 00000000 00010000 0001 01 %d %s' %
                     (n, ino, sock))

        fd_dir = os.path.join(proc, str(pid), 'fd')
        os.makedirs(fd_dir)
        os.symlink('socket:[%d]' % ino, os.path.join(fd_dir, '7'))

        for path in (os.path.join(install, 'node'),
                     os.path.join(install, 'bin', 'remote-cli', 'buddycn')):
            os.makedirs(os.path.dirname(path), exist_ok=True)

            with open(path, 'w'):
                pass

            os.chmod(path, 0o755)

        os.symlink(os.path.join(install, 'node'), os.path.join(proc, str(pid), 'exe'))

    with open(os.path.join(proc, 'net', 'unix'), 'w') as f:
        f.write('\n'.join(lines) + '\n')

    return proc


class ProcCase(EditCase):
    """假 /proc + 假窗口：窗口发现、status 探测、--list / --init 的公共环境"""

    fzf = '0'                       # 默认关掉 fzf（FzfTest 里改成 ''）

    def setUp(self):
        super().setUp()
        self.sock1 = os.path.join(self.dir, 'vscode-ipc-1.sock')
        self.sock2 = os.path.join(self.dir, 'vscode-ipc-2.sock')
        self.install = os.path.join(self.dir, 'ide')
        self.cli_dir = os.path.join(self.install, 'bin', 'remote-cli')
        self.proc = make_proc(self.dir, [(self.sock1, '101', self.install),
                                         (self.sock2, '202', self.install)])

    def candidates(self):
        """用假 /proc 跑一次 find_sockets"""

        with patch.object(edit, 'PROC', self.proc):
            return edit.find_sockets()

    def run_main(self, *argv, hook=None, answer=None):
        """进程内跑 main：返回 (stdout, stderr, 退出码)

        SystemExit 在这里接住（--init 报错、--interactive 取消都走它），
        否则测试只能靠 subprocess 才能看到退出码。
        """

        out, err = StringIO(), StringIO()
        env = dict(os.environ)
        env.pop(edit.IPC_HOOK, None)
        # 关掉 fzf：测试不该真拉起一个选择器（要测它的话自己打 use_fzf 的补丁）
        env[edit.EDIT_FZF] = self.fzf

        if hook is not None:
            env[edit.IPC_HOOK] = hook

        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['edit.py', *argv]))
            stack.enter_context(patch.object(edit, 'PROC', self.proc))
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch('builtins.input', return_value=answer))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))

            try:
                edit.main()
                code: str | int | None = 0
            except SystemExit as e:
                code = e.code        # SystemExit.code 就是 str / int / None

        return out.getvalue(), err.getvalue(), code


class FindSocketsTest(ProcCase):
    """find_sockets：认 socket、推出安装目录与 CLI"""

    def test_lists_windows(self):
        found = self.candidates()

        self.assertEqual([s['sock'] for s in found], [self.sock1, self.sock2])
        self.assertEqual([s['pid'] for s in found], ['101', '202'])
        self.assertEqual(found[0]['install'], self.install)
        self.assertEqual(found[0]['cli'], os.path.join(self.cli_dir, 'buddycn'))

    def test_ignores_other_sockets(self):
        """名字里没有 vscode-ipc- 的一律不认"""

        other = os.path.join(self.dir, 'other.sock')
        proc = make_proc(os.path.join(self.dir, 'alt'),
                         [(other, '303', self.install),
                          (self.sock1, '101', self.install)])

        with patch.object(edit, 'PROC', proc):
            found = edit.find_sockets()

        self.assertEqual([s['sock'] for s in found], [self.sock1])

    def test_no_proc(self):
        """没有 /proc（macOS）是 None，不是空列表：调用方靠它区分"不适用" """

        with patch.object(edit, 'PROC', os.path.join(self.dir, 'no-such')):
            self.assertIsNone(edit.find_sockets())

    def test_no_net_unix(self):
        """/proc 在但读不到 net/unix 也是 None"""

        empty = os.path.join(self.dir, 'empty-proc')
        os.makedirs(empty)

        with patch.object(edit, 'PROC', empty):
            self.assertIsNone(edit.find_sockets())


class PruneTest(ProcCase):
    """--prune：只删没人 bind 的 vscode-ipc socket，活着的一个都不动

    安全第一：这些用例一律把 prune_dirs 锁死在临时目录里（patch 掉），真实的
    $XDG_RUNTIME_DIR 一个 socket 都不许碰 —— 唯一的"真删"路径也只扫临时目录。
    """

    def dead_sock(self, name):
        """造一个"死了的" socket 文件：bind 过、名字还在、没人再管它"""

        path = os.path.join(self.dir, name)
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.close()                       # 名字留下（正是残留文件的样子）
        return path

    def prune(self, dry_run=False):
        """跑一次 prune_sockets：假 /proc + 只扫 self.dir"""

        with ExitStack() as stack:
            stack.enter_context(patch.object(edit, 'PROC', self.proc))
            stack.enter_context(patch.object(edit, 'prune_dirs', lambda: [self.dir]))
            return edit.prune_sockets(dry_run)

    def test_removes_dead_keeps_alive(self):
        """活着的（假 /proc 里 bind 着）不动；死掉的删掉；同名的普通文件不动"""

        alive = self.dead_sock('vscode-ipc-1.sock')     # sock1：make_proc 里 bind 着
        dead = self.dead_sock('vscode-ipc-dead.sock')   # 不在 net/unix 里
        plain = os.path.join(self.dir, 'vscode-ipc-plain.sock')

        with open(plain, 'w'):
            pass

        result = self.prune()

        self.assertEqual([p for _, p in result.removed], [dead])
        self.assertEqual((result.alive, result.not_socket, result.failed), (1, 1, []))
        self.assertFalse(os.path.exists(dead))
        self.assertTrue(os.path.exists(alive))
        self.assertTrue(os.path.exists(plain))

    def test_dry_run_removes_nothing(self):
        """--dry-run：照样列出会删哪些，但一个都不删"""

        dead = self.dead_sock('vscode-ipc-dead.sock')

        result = self.prune(dry_run=True)
        text = '\n'.join(edit.format_prune(result, True))

        self.assertEqual([p for _, p in result.removed], [dead])
        self.assertIn(dead, text)
        self.assertIn('（--dry-run：没有真删）', text)
        self.assertTrue(os.path.exists(dead))

    def test_sorted_oldest_first(self):
        """按 mtime 升序：最该删的（最旧）排最前"""

        young = self.dead_sock('vscode-ipc-young.sock')
        old = self.dead_sock('vscode-ipc-old.sock')

        os.utime(old, (1_600_000_000, 1_600_000_000))       # 2020-09
        os.utime(young, (1_700_000_000, 1_700_000_000))     # 2023-11

        result = self.prune(dry_run=True)

        self.assertEqual([p for _, p in result.removed], [old, young])
        self.assertTrue(edit.format_prune(result, True)[0].startswith('2020-'))

    def test_ignores_other_names(self):
        """名字不带 vscode-ipc- 或不以 .sock 结尾的，碰都不碰"""

        other = self.dead_sock('other.sock')
        prefixed = self.dead_sock('vscode-ipc-noext')

        result = self.prune()

        self.assertEqual(result.removed, [])
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.exists(prefixed))

    def test_prune_dirs(self):
        """候选目录：$XDG_RUNTIME_DIR / $TMPDIR / hook 所在目录 —— 去重，只留存在的"""

        env = {edit.IPC_HOOK: os.path.join(self.dir, 'hook.sock'),
               'XDG_RUNTIME_DIR': self.dir,
               'TMPDIR': os.path.join(self.dir, 'no-such')}

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(edit.prune_dirs(), [self.dir])

        # 没有 XDG_RUNTIME_DIR 时靠 hook 所在目录兜底
        with patch.dict(os.environ, {edit.IPC_HOOK: os.path.join(self.dir, 'hook.sock')},
                        clear=True):
            self.assertEqual(edit.prune_dirs(), [self.dir])

    def test_no_proc(self):
        """没有 /proc：prune_sockets 返回 None，print_prune 报错退出（一个也不删）"""

        with patch.object(edit, 'PROC', os.path.join(self.dir, 'no-such')):
            self.assertIsNone(edit.prune_sockets())

            with self.assertRaises(SystemExit) as ctx:
                edit.print_prune()

        self.assertIn('没有', str(ctx.exception))

    def test_rejects_files_and_conflicts(self):
        """--prune 不接受文件参数，也不和 --init / --list / --interactive 一起用"""

        for argv in (('--prune', 'a.txt'), ('--prune', '--list'),
                     ('--prune', '--interactive'), ('--prune', '--init', 'fish')):
            with self.subTest(argv):
                _, _, code = self.run_main(*argv)

                self.assertTrue(str(code).startswith('edit --prune'), code)

    def test_main_dry_run(self):
        """走一遍 main：--prune --dry-run 打印清单，退出码 0，文件还在"""

        dead = self.dead_sock('vscode-ipc-dead.sock')

        with patch.object(edit, 'prune_dirs', lambda: [self.dir]):
            out, err, code = self.run_main('--prune', '--dry-run')

        self.assertEqual(code, 0)
        self.assertIn(dead, out)
        self.assertIn('（--dry-run：没有真删）', out)
        self.assertTrue(os.path.exists(dead))


class ProbeTest(ProcCase):
    """status 探测：真给假窗口发一次请求，把 workspace 填回候选"""

    def test_fills_workspace(self):
        self.add_window(path=self.sock1, body=status_body('/w/proj'))
        self.add_window(path=self.sock2, body=status_body('/w/other'))

        socks = self.candidates()
        edit.probe_workspaces(socks)

        self.assertEqual([s['workspace'] for s in socks], ['/w/proj', '/w/other'])
        self.assertEqual(socks[0]['authority'], 'ssh-remote+7')

    def test_unreachable_is_none(self):
        """连不上或答非所问 -> workspace 留 None（显示成 ?），不抛异常"""

        self.add_window(path=self.sock1, body='{}')     # 不是 JSON 字符串

        socks = self.candidates()                        # sock2 没人监听
        edit.probe_workspaces(socks)

        self.assertIsNone(socks[0]['workspace'])
        self.assertIsNone(socks[1]['workspace'])

    def test_status_request_matches_cli(self):
        """探测用的 status 报文要和 CLI 的一模一样"""

        w = self.add_window(path=self.sock1, body=status_body('/w/proj'))

        edit.probe_workspaces(self.candidates())

        self.assertEqual(w.requests[-1], load_fixtures()['status']['msg'])


class ProtocolFixtureTest(unittest.TestCase):
    """拿真 CLI 的报文快照对照 open_request

    断言的是"字段集合 + 取值"，不是字节：CLI 用 chunked + keep-alive，我们用
    content-length + close，HTTP 头本来就不同（见 NOTES）。
    direct=false 那几条是现在交回 CLI 的，断言 open_request 翻不出来 —— 哪天
    直连支持了，这条会失败，正好提醒把 direct 改成 true。
    """

    def cases(self):
        data = load_fixtures()

        self.assertTrue(data, 'fixtures/protocol.json 是空的')

        return data

    def test_open_matches_cli(self):
        for name, case in sorted(self.cases().items()):
            if case['msg'].get('type') != 'open':
                continue                            # status 另有断言

            with self.subTest(name):
                # diff 记的是我们与 CLI 故意不同的字段，值取我们的
                want = dict(case['msg'], **case.get('diff', {}))
                # --wait 那条要带上 marker，否则按设计会翻不出来（交回 CLI）
                got = edit.open_request(case['args'],
                                        case['msg'].get('waitMarkerFilePath'))

                if not case['direct']:
                    self.assertIsNone(got, '%s 现在该交回 CLI' % name)
                    continue

                self.assertEqual(got, want)

    def test_diff_is_still_needed(self):
        """标了 diff 的字段必须真的与 CLI 不同，否则上游改了、例外该删"""

        for name, case in sorted(self.cases().items()):
            for key, ours in (case.get('diff') or {}).items():
                with self.subTest(name + '.' + key):
                    self.assertNotEqual(
                        case['msg'].get(key), ours,
                        '%s.%s 已经和 CLI 一致了，例外该删掉' % (name, key))


class WaitTest(EditCase):
    """--wait / -w：直连发 marker，等窗口把它删掉（= 等文件被关）"""

    def test_marker_in_request(self):
        for flag in ('--wait', '-w'):
            with self.subTest(flag):
                msg = edit.open_request([flag, self.a], '/m')

                self.assertEqual(msg['waitMarkerFilePath'], '/m')
                self.assertEqual(msg['fileURIs'], ['file://' + self.a])

    def test_without_marker_falls_back(self):
        """没给 marker 就翻不出来 —— CLI 自己会造一个"""

        self.assertIsNone(edit.open_request(['--wait', self.a]))

    def test_only_folder_falls_back(self):
        """CLI 要求 --wait 至少带一个文件，只给目录它也不认"""

        self.assertIsNone(edit.open_request(['--wait', self.spaced], '/m'))

    def test_end_to_end(self):
        """假窗口收到就删 marker：edit 该等到了再退，且不回退 CLI"""

        self.win = self.add_window(unlink_marker=True)
        proc = self.run_edit('--wait', self.a, hook=self.win.path)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(self.cli_args(), '不该回退到 CLI')

        marker = self.win.requests[-1]['waitMarkerFilePath']
        self.assertTrue(os.path.basename(marker).startswith('edit-wait-'), marker)
        self.assertFalse(os.path.exists(marker), 'marker 该被删掉')

    def test_marker_cleaned_when_falls_back(self):
        """报文翻不出来时不能把 marker 留在 /tmp"""

        before = set(glob.glob(os.path.join(tempfile.gettempdir(), 'edit-wait-*')))

        self.win = self.add_window()
        proc = self.run_edit('--wait', '--merge', self.a, hook=self.win.path)

        self.assertEqual(proc.returncode, 7, proc.stderr)   # 假 CLI 被调起
        # --merge 只给了 1 个路径（要 4 个），翻不出来 -> 交回 CLI；
        # --wait 被摘掉了（假 CLI 不是 VS Code 系，见下），我们造的 marker 已收回
        self.assertEqual(self.cli_args(), '--merge ' + self.a)

        left = set(glob.glob(os.path.join(tempfile.gettempdir(), 'edit-wait-*'))) - before
        self.assertEqual(left, set(), 'marker 该被收回去')

    def test_wait_dropped_for_other_cli(self):
        """交回的 CLI 不是 VS Code 系（这里假 CLI 谁都不认）：--wait / -w 摘掉

        vim 没有 --wait（实测 Unknown option argument 退出 1），-w 在 vim 里还是
        "把键入的命令写进文件"，留着会坏事；而终端 vim 本来就前台阻塞到退出。
        """

        for flag in ('--wait', '-w'):
            with self.subTest(flag):
                proc = self.run_edit('--dry-run', flag, self.a)

                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.split(), [self.fake_cli, self.a])

    def test_wait_kept_for_code_cli(self):
        """VS Code 系认得 --wait：原样交给它（直连翻不出来时它会自己造 marker）"""

        self.assertEqual(edit.cli_argv(['--wait', self.a], edit.CLI_KIND_CODE),
                         ['--wait', self.a])

    def test_wait_marker_returns_when_deleted(self):
        marker = self._touch('marker')

        def remove() -> None:            # 别用 lambda + and：unlink 返回 None，读起来像有话要说
            if os.path.exists(marker):
                os.unlink(marker)

        threading.Timer(0.05, remove).start()
        edit.wait_marker(marker, interval=0.01)

        self.assertFalse(os.path.exists(marker))

    def test_wait_marker_removes_on_interrupt(self):
        """Ctrl-C：先把 marker 收回去，再把中断抛给 main（那边转成 130）"""

        marker = self._touch('marker')

        with patch('time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                edit.wait_marker(marker)

        self.assertFalse(os.path.exists(marker))


class ListTest(ProcCase):
    """--list：表格里要有 socket / cli / workspace，当前那个标 *"""

    def test_list(self):
        self.add_window(path=self.sock1, body=status_body('/w/proj'))

        out, err, code = self.run_main('--list')

        self.assertEqual(code, 0)
        self.assertEqual(err, '')

        rows = out.strip().split('\n')
        self.assertEqual(len(rows), 3)                  # 表头 + 两个窗口
        self.assertIn(self.sock1, rows[1])
        self.assertIn('buddycn', rows[1])
        self.assertIn('/w/proj', rows[1])
        self.assertIn('?', rows[2])                      # 没人监听的那个

    def test_marks_current(self):
        self.add_window(path=self.sock1, body=status_body('/w/proj'))

        out, _, _ = self.run_main('--list', hook=self.sock1)

        rows = out.strip().split('\n')
        self.assertTrue(rows[1].startswith('*'))
        self.assertFalse(rows[2].startswith('*'))

    def test_rejects_files(self):
        _, _, code = self.run_main('--list', self.a)

        self.assertIn('不接受文件参数', code)


class InteractiveOpenTest(ProcCase):
    """--interactive <文件>：挑中的窗口直接开文件（不必先 --init 导入 hook）"""

    def setUp(self):
        super().setUp()
        self.w1 = self.add_window(path=self.sock1, body=status_body('/w/proj'))
        self.w2 = self.add_window(path=self.sock2, body=status_body('/w/other'))

    def opens(self, win):
        """该窗口收到的 open 报文（探测 workspace 的 status 不算）"""

        return [m for m in win.requests if m.get('type') == 'open']

    def test_opens_in_chosen_window(self):
        _, _, code = self.run_main('--interactive', self.a, answer='2')

        self.assertEqual(code, 0)
        self.assertEqual(self.opens(self.w1), [], '1 号不该被打开')
        self.assertEqual(self.opens(self.w2)[-1]['fileURIs'], ['file://' + self.a])

    def test_dry_run_shows_chosen_socket(self):
        out, _, code = self.run_main('--dry-run', '--interactive', self.a, answer='2')

        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('socket %s ' % self.sock2), out)
        self.assertEqual(self.opens(self.w1), [])
        self.assertEqual(self.opens(self.w2), [], '--dry-run 不该真发')

    def test_hook_is_written_back(self):
        """挑完把 socket 写回 VSCODE_IPC_HOOK_CLI：后面的 current_socket() 都是它"""

        seen = {}

        def spy(sock, msg, **kw):
            seen['sock'] = sock
            seen['hook'] = os.environ.get(edit.IPC_HOOK)

            return True, '{}'

        with patch.object(edit, 'socket_open', spy):
            _, _, code = self.run_main('--interactive', self.a, answer='2')

        self.assertEqual(code, 0)
        self.assertEqual(seen['sock'], self.sock2)
        self.assertEqual(seen['hook'], self.sock2)

    def test_enter_picks_current(self):
        """有 hook 时回车 = 当前窗口"""

        self.run_main('--interactive', self.a, hook=self.sock1, answer='')

        self.assertEqual(self.opens(self.w1)[-1]['fileURIs'], ['file://' + self.a])
        self.assertEqual(self.opens(self.w2), [])

    def test_cancel(self):
        _, _, code = self.run_main('--interactive', self.a, answer='q')

        self.assertIn('没有选中窗口', code)
        self.assertEqual(self.opens(self.w1), [])
        self.assertEqual(self.opens(self.w2), [])

    def test_conflicts_with_list(self):
        _, _, code = self.run_main('--interactive', '--list', self.a)

        self.assertIn('冲突', code)


class FzfTest(ProcCase):
    """--interactive 有 fzf 时用它挑窗口（这里把 fzf 换成假的 subprocess.run）"""

    def setUp(self):
        super().setUp()
        self.w1 = self.add_window(path=self.sock1, body=status_body('/w/proj'))
        self.w2 = self.add_window(path=self.sock2, body=status_body('/w/other'))

    def opens(self, win):
        return [m for m in win.requests if m.get('type') == 'open']

    def run_fzf(self, out, code=0, answer='1'):
        """假 fzf 返回 out（code != 0 = 被取消），返回它收到的参数"""

        seen = {}

        def fake(argv, **kw):
            seen['argv'] = argv
            seen['input'] = kw.get('input')

            return subprocess.CompletedProcess(argv, code, out, '')

        with patch.object(edit, 'use_fzf', lambda: True), \
                patch('subprocess.run', fake):
            self.out, self.err, self.code = self.run_main('--interactive', self.a,
                                                          answer=answer)

        return seen

    def test_selects_line(self):
        """选中 2 号那行 -> 开在 2 号窗口（行首编号反查候选项）"""

        lines = edit.format_sockets(self.candidates(), None)
        seen = self.run_fzf(lines[2] + '\n')

        self.assertEqual(seen['argv'][0], 'fzf')
        self.assertIn('--header-lines=1', seen['argv'])
        self.assertIn(self.sock1, seen['input'])
        self.assertEqual(self.opens(self.w1), [], '1 号不该被打开')
        self.assertEqual(self.opens(self.w2)[-1]['fileURIs'], ['file://' + self.a])

    def test_cancel_falls_back(self):
        """Esc / Ctrl-C（fzf 非 0 退出）-> 落到编号输入，不直接退出"""

        self.run_fzf('', code=130, answer='1')

        self.assertEqual(self.code, 0)
        self.assertIn('选择窗口编号', self.err)
        self.assertEqual(self.opens(self.w1)[-1]['fileURIs'], ['file://' + self.a])
        self.assertEqual(self.opens(self.w2), [])

    def test_unparsable_line_falls_back(self):
        """选中的行认不出编号 -> 同样落到编号输入"""

        self.run_fzf('garbage\n', code=0, answer='1')

        self.assertIn('选择窗口编号', self.err)
        self.assertEqual(self.opens(self.w1)[-1]['fileURIs'], ['file://' + self.a])

    def test_stdout_stays_clean(self):
        """fzf 的界面走 stderr：stdout 仍只留给 --init 的片段"""

        self.run_fzf(edit.format_sockets(self.candidates(), None)[2] + '\n')

        self.assertEqual(self.out, '')

    def test_not_used_when_off(self):
        """EDIT_FZF=0：根本不拉 fzf"""

        def boom(*a, **kw):
            raise AssertionError('不该拉起 fzf')

        with patch('subprocess.run', boom):
            self.out, self.err, self.code = self.run_main('--interactive', self.a,
                                                          answer='2')

        self.assertEqual(self.opens(self.w1), [])
        self.assertEqual(self.opens(self.w2)[-1]['fileURIs'], ['file://' + self.a])


class UseFzfTest(unittest.TestCase):
    """use_fzf：显式关掉 / stdin 不是 tty / 没装 fzf 都不用"""

    def env(self, **over):
        env = {k: v for k, v in os.environ.items() if k != edit.EDIT_FZF}
        env.update(over)

        return env

    def patched(self, env, isatty, has_fzf):
        stdin = patch('sys.stdin')
        which = patch.object(edit.shutil, 'which', lambda n: '/bin/fzf' if has_fzf else None)

        return patch.dict(os.environ, env, clear=True), stdin, which

    def check(self, env, isatty, has_fzf, want):
        envp, stdin, which = self.patched(env, isatty, has_fzf)

        with envp, stdin as s, which:
            s.isatty.return_value = isatty

            self.assertEqual(edit.use_fzf(), want)

    def test_off_values(self):
        for off in ('0', 'off', 'never'):
            with self.subTest(off):
                self.check(self.env(**{edit.EDIT_FZF: off}), True, True, False)

    def test_needs_tty(self):
        self.check(self.env(), False, True, False)

    def test_needs_fzf(self):
        self.check(self.env(), True, False, False)

    def test_on(self):
        self.check(self.env(), True, True, True)


class InitTest(ProcCase):
    """--init：挑窗口 -> 只把该窗口的 hook 与 remote-cli 目录写进片段"""

    def test_interactive_picks_window(self):
        self.add_window(path=self.sock1, body=status_body('/w/proj'))
        self.add_window(path=self.sock2, body=status_body('/w/other'))

        out, err, code = self.run_main('--init', 'bash', '--interactive', answer='2')

        self.assertEqual(code, 0)
        self.assertIn('export %s=%s' % (edit.IPC_HOOK, self.sock2), out)
        self.assertIn(self.cli_dir, out)
        self.assertNotIn(self.sock1, out)               # 挑的是 2 号
        self.assertIn('选择窗口编号', err)               # 提示走 stderr

    def test_interactive_cancel(self):
        self.add_window(path=self.sock1, body=status_body('/w/proj'))

        out, _, code = self.run_main('--init', 'fish', '--interactive', answer='q')

        self.assertIn('没有选中窗口', code)
        self.assertEqual(out, '')                       # 取消了就什么都不输出

    def test_needs_hook(self):
        """不带 --interactive 且当前终端没 hook：报错，不给片段"""

        out, _, code = self.run_main('--init', 'bash')

        self.assertIn('当前终端没有', code)
        self.assertEqual(out, '')

    def test_interactive_needs_files(self):
        """不带 --init 又不给文件：挑了窗口也没东西可开"""

        _, _, code = self.run_main('--interactive')

        self.assertIn('要带文件', code)


if __name__ == '__main__':
    unittest.main()
