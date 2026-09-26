#!/usr/bin/env python3
"""edit.py 的回归测试：python3 test_edit.py -v

不碰真实 IDE、不开窗口：
* socket 路径：起一个假窗口（AF_UNIX server），断言 edit 发过去的 JSON 与退出码
* CLI 路径：EDIT_CLI 指到假 CLI，断言 --dry-run 打印的命令行、或它是否真被调用
* 回退：假窗口回 500 / 连上就关，断言 stderr 有提示且假 CLI 真的被执行
"""

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

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = os.path.join(HERE, 'edit.py')

spec = importlib.util.spec_from_file_location('edit', EDIT)
edit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edit)


class FakeWindow:
    """假装是一个 IDE 窗口的 socket：收 POST，按设定回复"""

    def __init__(self, code=200, body='{}', silent=False):
        self.path = tempfile.mktemp(prefix='fake-window-', suffix='.sock')
        self.code = code
        self.body = body
        self.silent = silent
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

        self.win = None
        self.cli_out = os.path.join(self.dir, 'cli-args.txt')
        self.fake_cli = self._fake_cli()

    def tearDown(self):
        if self.win:
            self.win.close()

        self.tmp.cleanup()

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

        self.win = FakeWindow(**kw)
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


class DryRunTest(EditCase):
    """--dry-run：能直连时打 JSON，翻不了时打命令行"""

    def test_socket_json(self):
        self.win = FakeWindow()
        proc = self.run_edit('--dry-run', self.a, hook=self.win.path)

        self.assertEqual(proc.returncode, 0, proc.stderr)

        head, _, rest = proc.stdout.strip().partition(' ')
        self.assertEqual(head, 'socket')

        sock, _, payload = rest.partition(' ')
        self.assertEqual(sock, self.win.path)
        self.assertEqual(json.loads(payload)['fileURIs'], ['file://' + self.a])
        self.assertEqual(self.win.requests, [], '--dry-run 不该真的发请求')

    def test_cli_line(self):
        self.win = FakeWindow()
        proc = self.run_edit('--dry-run', '-g', self.a + ':3', hook=self.win.path)

        self.assertEqual(proc.stdout.split()[0], self.fake_cli)
        self.assertEqual(proc.stdout.split()[1:3], ['-g', self.a + ':3'])
        self.assertEqual(self.win.requests, [])


class FallbackTest(EditCase):
    """socket 不行时回退 CLI"""

    def assert_fell_back(self, proc):
        self.assertIn('socket 打不开', proc.stderr)
        self.assertEqual(proc.returncode, 7)            # 假 CLI 的退出码
        self.assertEqual(self.cli_args(), self.a)       # 假 CLI 真被调用了

    def test_http_500(self):
        self.win = FakeWindow(code=500, body='boom')

        self.assert_fell_back(self.run_edit(self.a, hook=self.win.path))

    def test_window_closes(self):
        self.win = FakeWindow(silent=True)

        self.assert_fell_back(self.run_edit(self.a, hook=self.win.path))

    def test_untranslatable_args(self):
        """--wait / -g / 无参数 / 没有 socket：一律交给 CLI"""

        for args in (['--wait', self.a], ['-g', self.a + ':3'], []):
            with self.subTest(args):
                proc = self.run_edit(*args)

                self.assertEqual(proc.returncode, 7, proc.stderr)
                self.assertNotIn('socket 打不开', proc.stderr)


if __name__ == '__main__':
    unittest.main()
