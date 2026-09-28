#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 IDE 自己的 CLI 发到窗口 socket 上的报文抓下来，存进 fixtures/protocol.json

用法：

    python3 tools/capture_cli.py --name open-goto -- /tmp/a.txt:3
    python3 tools/capture_cli.py --name open-diff -- -d /tmp/a.txt /tmp/b.txt
    python3 tools/capture_cli.py --name open-wait --direct false -- --wait /tmp/a.txt
    python3 tools/capture_cli.py --name open-goto --except gotoLineMode=true -- /tmp/a.txt:3
    python3 tools/capture_cli.py --cli ~/.vscode-server/bin/<hash>/bin/remote-cli/code \
        --name open-goto --print -- /tmp/a.txt:3

做法：起一个 AF_UNIX server 假扮窗口，把 VSCODE_IPC_HOOK_CLI 指过去跑一次 CLI，
收下它发来的第一条请求（chunked），脱敏后写进 fixtures。CLI 发完就一直等回复，
所以"超时"是正常现象（默认 6 秒，--timeout 调）。

存进去的是**报文**，不是 HTTP 头：CLI 用 Transfer-Encoding: chunked +
keep-alive，edit 用 content-length + close，两者 server 都吃，头不必对齐。
不在 test_edit.py 里跑：它要真 CLI，环境一变就失败；测试只读 fixtures。
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.pardir, 'fixtures', 'protocol.json')

MARKER = '<marker>'          # CLI 每次现造的临时文件，路径不可重现
HOME = '<home>'              # 本机家目录，不该进仓库

REPLY = (b'HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n'
         b'content-length: 2\r\n\r\n{}')


def default_cli():
    """PATH 里第一个能用的 CLI（code / buddycn / trae-cn / cursor）"""

    for name in ('code', 'buddycn', 'trae-cn', 'cursor'):
        cli = shutil.which(name)
        if cli:
            return cli

    sys.exit('capture: PATH 里没有 CLI，用 --cli 指一个 remote-cli 的可执行文件')


def unchunk(raw):
    """取 chunked 正文：第一行是长度（16 进制），接着是数据，0 收尾

    >>> unchunk(b'HTTP/1.1 200 OK\\r\\n\\r\\n7\\r\\n{"a":1}\\r\\n0\\r\\n\\r\\n')
    b'{"a":1}'
    >>> unchunk(b'HTTP/1.1 200 OK\\r\\n\\r\\n7\\r\\n{"a"')     # 数据没收全
    b''
    """

    _, _, rest = raw.partition(b'\r\n\r\n')
    out = []

    while True:
        line, _, rest = rest.partition(b'\r\n')

        try:
            size = int(line.split(b';')[0], 16)
        except ValueError:
            break

        if size == 0:
            break

        if len(rest) < size:
            break                       # 数据没收全，别把后面的 0\\r\\n 也吞进去

        out.append(rest[:size])
        rest = rest[size + len(b'\r\n'):]

    return b''.join(out)


def capture(cli, args, timeout=6):
    """假扮窗口跑一次 CLI，返回它发来的报文（dict）；失败返回 None"""

    path = tempfile.mktemp(prefix='capture-', suffix='.sock')
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    srv.settimeout(timeout)

    got = []

    def serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return

        with conn:
            conn.settimeout(timeout)

            try:
                data = conn.recv(65536)
                while data:                 # CLI 等着回复，靠超时收尾
                    got.append(data)
                    data = conn.recv(65536)
            except OSError:
                pass

            try:
                conn.sendall(REPLY)
            except OSError:
                pass

    threading.Thread(target=serve, daemon=True).start()

    env = dict(os.environ, VSCODE_IPC_HOOK_CLI=path)

    try:
        subprocess.run([cli, *args], env=env, timeout=timeout, capture_output=True)
    except subprocess.TimeoutExpired:
        pass                                # CLI 等回复，超时是预期结果
    except OSError as e:
        sys.exit('capture: 跑不了 %s（%s）' % (cli, e))

    srv.close()
    if os.path.exists(path):
        os.unlink(path)

    if not got:
        return None

    try:
        return json.loads(unchunk(b''.join(got)).decode())
    except ValueError:
        return None


def normalize(msg):
    """脱敏：marker 换成占位符、家目录换成 <home>，否则 fixture 不可重现

    >>> normalize({'waitMarkerFilePath': '/tmp/abc123', 'fileURIs': []})
    {'waitMarkerFilePath': '<marker>', 'fileURIs': []}
    """

    home = os.environ.get('HOME')

    def fix(v):
        if not isinstance(v, str):
            return v

        if home:
            v = v.replace(home, HOME)

        return v

    out: dict[str, object] = {}          # 值有 str / list[str] / bool 三种，别推成 dict[str, str]

    for k, v in msg.items():
        if k == 'waitMarkerFilePath':
            out[k] = MARKER
        elif isinstance(v, list):
            out[k] = [fix(i) for i in v]
        else:
            out[k] = fix(v)

    return out


def source_of(cli):
    """记下这份快照是哪家的哪个安装：<产品> @ <安装目录>（家目录同样脱敏）"""

    install = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(cli))))
    home = os.environ.get('HOME')

    if home:
        install = install.replace(home, HOME)

    return {'cli': os.path.basename(cli), 'install': install}


def save(out, name, entry):
    data = {}

    if os.path.exists(out):
        with open(out, encoding='utf-8') as f:
            data = json.load(f)

    data[name] = entry

    os.makedirs(os.path.dirname(out), exist_ok=True)

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('--cli', help='remote-cli 的可执行文件，默认取 PATH 里第一个')
    parser.add_argument('--name', required=True, help='存进 fixtures 的名字')
    parser.add_argument('--out', default=OUT, help='默认 fixtures/protocol.json')
    parser.add_argument('--timeout', type=float, default=6.0)
    parser.add_argument('--direct', choices=('true', 'false'), default='true',
                        help='edit 现在能不能直连发这种报文（不能就写 false）')
    parser.add_argument('--except', dest='diff', action='append', default=[],
                        metavar='KEY=VALUE',
                        help='我们与 CLI 故意不同的字段（值是我们的取值），可多次')
    parser.add_argument('--print', dest='show', action='store_true',
                        help='只打印，不写文件')

    flags, rest = parser.parse_known_args()

    if rest and rest[0] == '--':
        rest = rest[1:]

    if not rest:
        sys.exit('capture: 没给 CLI 参数，例如 --name open-goto -- /tmp/a.txt:3')

    cli = flags.cli or default_cli()
    msg = capture(cli, rest, flags.timeout)

    if not msg:
        sys.exit('capture: 没收到报文（%s %s）' % (os.path.basename(cli), ' '.join(rest)))

    # --wait 的 marker 是 CLI 现造的临时文件，它被超时杀掉时不会自己清理
    marker = msg.get('waitMarkerFilePath')
    if marker and os.path.isfile(marker):
        os.unlink(marker)

    diff = {}

    for item in flags.diff:
        key, _, value = item.partition('=')

        try:
            diff[key] = json.loads(value)        # true / false / 数字 / "字符串"
        except ValueError:
            diff[key] = value

    entry = {
        'args': rest,
        'direct': flags.direct == 'true',
        'source': source_of(cli),
        'msg': normalize(msg),
    }

    if diff:
        entry['diff'] = diff

    if flags.show:
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return

    save(flags.out, flags.name, entry)
    print('%s -> %s' % (flags.name, os.path.relpath(flags.out, HERE)))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
