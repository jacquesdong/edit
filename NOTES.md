# edit 设计笔记

这份文档记录**为什么这么写**、**协议是怎么摸出来的**、以及**还没做的事**。
用法看 `README.md` 或 `edit.py --usage`；行为断言看 `test_edit.py`。

## 背景

`edit` 原来住在 dotfiles（`~/config/scripts/.scripts/edit.py`）。拆到这里是为了让
代码、测试、协议笔记在一起；dotfiles 里那份**保留**，由使用者手动同步
（`conf.d/edit.fish` 里的软链、`~/.local/bin/edit` 都还在 dotfiles 那边维护）。

## 窗口 socket 上的协议（实测）

窗口的 `VSCODE_IPC_HOOK_CLI`（`/run/user/<uid>/vscode-ipc-<uuid>.sock`）上跑的是
**HTTP/1.1 + JSON**。`remote-cli`（`<安装目录>/out/server-cli.js`）自己也是这么发的：

```
POST / HTTP/1.1
content-type: application/json
Content-Length: 189

{"type":"open","fileURIs":["file:///tmp/a.txt:3"],"folderURIs":[],
 "diffMode":false,"mergeMode":false,"addMode":false,"gotoLineMode":true,
 "forceReuseWindow":false,"forceNewWindow":false}
```

**只有正文与 CLI 逐字节一致，HTTP 头不同**：CLI 发的是
`Transfer-Encoding: chunked` + `Connection: keep-alive`（`server-cli.js` 自己这么发），
`edit` 发的是 `content-length` + `connection: close`。两种服务端都收，
实测 `edit` 直连能开文件，所以头不必对齐 —— 对齐了反而要处理 keep-alive。

服务端（`out/server-main.js`）只分派四种 `type`：

| type | 作用 | 回复 |
|---|---|---|
| `open` | 开文件 / 文件夹、diff、merge、add | JSON |
| `status` | 让**窗口**跑 `_remoteCLI.getSystemStatus`，返回诊断文本 | JSON 字符串 |
| `openExternal` | 交给系统打开 URL | JSON |
| `extensionManagement` | 装/卸扩展 | JSON |

`remote-cli` 的收包逻辑（抓自 `server-cli.js`）：读完整回复 → `JSON.parse` →
**`statusCode === 200` 算成功**，否则失败；解析不出来也算失败。我们照抄这个判据。

### 各参数对应哪个字段

| 命令行 | 报文 |
|---|---|
| `edit a.txt` | `fileURIs:["file:///…/a.txt"]`、`gotoLineMode:false` |
| `edit a.txt:3` | **行号拼在 URI 里**：`file:///…/a.txt:3`、`gotoLineMode:true` |
| `edit a.txt:3:5` | `file:///…/a.txt:3:5`（列号可选） |
| `edit -r a.txt` | `forceReuseWindow:true` |
| `edit -n a.txt` | `forceNewWindow:true` |
| `edit -a a.txt` | `addMode:true` |
| `edit -d a.txt b.txt` | `diffMode:true`，两个 `fileURIs` |
| `edit somedir/` | 进 `folderURIs`，`fileURIs` 为空 |

URI 编码与 `remote-cli` 逐字节一致：空格 `%20`、非 ASCII 按 UTF-8 percent 编码，
**行号前的冒号不转义**（所以不能用 `pathlib.Path.as_uri()`，它会把 `:` 编成 `%3A`）。

`remoteAuthority` / `waitMarkerFilePath` 只有在对应场景才发，普通 open 没有。
`--wait` 时多一个 `waitMarkerFilePath`（CLI 现造的临时文件，每次路径都不同）。

**唯一与 CLI 故意不同的字段**：`gotoLineMode`。CLI 只有 `--goto` / `-g` 才发 `true`，
位置参数 `code file:3` 发的是 **`false`**（`:3` 照样拼在 URI 里，也就是不跳行）；
而 `edit file:3` 要的是"跳到第 3 行"，所以按 `--goto` 的语义发 `true`。
这条差异记在 fixtures 对应条目的 `diff` 里，不是 bug。

### 怎么再摸一次协议

`test_edit.py` 里的 `FakeWindow` 就是现成的假窗口。想抓 **CLI** 发的字节，反过来做
——把 hook 指到自己的 socket 上，再跑一次 CLI：

```python
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(path); srv.listen(1)
env = dict(os.environ, VSCODE_IPC_HOOK_CLI=path)
subprocess.run([cli, '--goto', '/tmp/a.txt:3'], env=env, timeout=3)   # 会一直等回复
# srv.accept() 拿到请求，chunked：第一行长度、第二行 JSON
```

注意 CLI 会等回复（我们那次等超时了），所以给它 3 秒左右就够。

这段已经固化成 `tools/capture_cli.py`：

```bash
python3 tools/capture_cli.py --name open-diff -- -d /tmp/a.txt /tmp/b.txt
python3 tools/capture_cli.py --name open-goto --except gotoLineMode=true -- /tmp/a.txt:3
```

它起假窗口、把 `VSCODE_IPC_HOOK_CLI` 指过去、跑一次 CLI，把报文脱敏后写进
`fixtures/protocol.json`（`waitMarkerFilePath` → `<marker>`、家目录 → `<home>`）。
`test_edit.py` 的 `ProtocolFixtureTest` / `ProbeTest` 拿它当基准，对照
`open_request()` 与 `status` 探测。

抓包要真 CLI，所以**它不在测试里跑**，测试只读 fixtures。fixtures 只有一份：
code / trae-cn / buddycn 三个产品、7 个安装版本实测发出的 JSON **逐字节相同**
（同一套 `server-cli.js`），按产品分只是冗余，真正的变量是版本。

## 执行路径

```
有 VSCODE_IPC_HOOK_CLI ？
  ├─ 参数能翻译成 open 报文 → 直连 socket（不找 CLI、不起 node）
  │     └─ HTTP 200 → 结束；否则 stderr 提示 + 回退 CLI
  └─ 翻不了（--wait / -g / 未知选项 / -- / 无参数）或没有 socket → 交给 remote-cli
        （code / buddycn / trae-cn，从 PATH 或 EDIT_CLI 找）
```

`--dry-run` 会告诉你走哪条：直连打印 `socket <路径> {json}`，CLI 路径打印模拟的命令行。

## 窗口发现与 workspace

- `find_sockets()`：扫 `/proc/net/unix`（只列已 bind 的，天然过滤残留 socket 文件）+
  `/proc/*/fd` 的 `socket:[inode]` 反查 pid → `/proc/<pid>/exe` 推安装目录；
  **判据是结构事实**（上两级有可执行的 `node`），所以只认 server 端，
  桌面版 `code` 的 socket 会被过滤掉。
- 同一个 socket 可能被多个进程/fd 认领（server + 继承 fd 的子进程），
  取舍规则：**优先留能推出 `<安装目录>/bin/remote-cli` 的那条**。
- `--list` / `--init --interactive` 会对每个候选直连一次只读 `{"type":"status"}`，
  从 `Process Argv: --remote <authority> <workspace>` 取 workspace（行号：走
  `parse_status()`；本地窗口没有 `--remote`，那就认不出来）。8 个窗口约 0.3s
  （线程池 ≤8，单个 1.5s 超时），失败显示 `?`。

试过但**没采用**的两条路：

- 持有 socket 的 server 进程的 `/proc/<pid>/cwd`：实测是 `$HOME` 或安装目录，没辨识价值；
- `/proc` 走模块级 `PROC` 常量（默认是 `/proc`）：`test_edit.py` 的 `make_proc()` 照着
  真表的结构造一份假的（`net/unix` + `<pid>/fd` 里的 `socket:[inode]` + `<pid>/exe`），
  再把 `edit.PROC` 指过去，窗口发现就能确定性测到（不用真 IDE、不用真进程表）。
- 扫 `/proc/*/environ` 找 `VSCODE_IPC_HOOK_CLI=<sock>` 的进程、看它们的 cwd：
  免费（5ms）且能区分窗口，但只给"该窗口里终端的目录"、要写去噪规则、也不好测，
  既然已经要直连 `status`，就不留这层。

## 还没做 / 待办

1. `--wait`（要 `waitMarkerFilePath`，等窗口回写 marker）、`--merge`、`-g` 现在都交回 CLI；
   要不要也接上由需求决定。这三种的报文已经抓在 fixtures 里（`open-wait` /
   `open-merge` / `open-goto-flag`，都标着 `direct:false`），接的时候照抄即可。
2. `--interactive` 选中的窗口**直接开文件**还没做：现在只有当前终端的 hook 走直连。
   要支持"先挑窗口再开文件"，把选中的 socket 传下去，或在早期写回
   `os.environ[IPC_HOOK]`（那样四个 `current_socket()` 调用点一行都不用改）。
3. 桌面版（macOS / Linux 桌面）其实也有 `vscode-ipc-*.sock`，只是被 `find_sockets()`
   的 node 判据过滤了。放宽判据即可复用同一条直连路径。
4. ~~回归脚本还能补：`status` 探测、`--list` / `--init` 的输出~~ 已补：`PROC` 可注入
   + `make_proc()` 造假进程表，见 `FindSocketsTest` / `ProbeTest` / `ListTest` /
   `InitTest`（进程内跑 `main()`，`sys.argv` / `stdout` / `input` 都打补丁）。

## 历史是怎么来的

`edit.py` 的历史是从 config 仓库按文件重放过来的：19 条提交里重放 16 条
（3 条纯改名因为内容没变被跳过），作者、日期、提交信息都保留，SHA 全新。

- 新仓库的最新提交 `b81db7c` ↔ config 的 `61a4ff2`（内容逐字节一致）；
- 再往前还包括 2020 年在 `bin/.bin/edit`、2022 年 `bin/.local/bin/edit` 的提交。
