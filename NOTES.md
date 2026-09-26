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
| `edit -g a.txt:3` | 同上：取值原样拼进 URI 并置 `gotoLineMode:true`（直连，与 CLI 一致） |
| `edit -r a.txt` | `forceReuseWindow:true` |
| `edit -n a.txt` | `forceNewWindow:true` |
| `edit -a a.txt` | `addMode:true` |
| `edit -d a.txt b.txt` | `diffMode:true`，两个 `fileURIs` |
| `edit -m a.txt b.txt base res` | `mergeMode:true`，四个 `fileURIs`（path1 path2 base result） |
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
python3 tools/capture_cli.py --name open-goto-short -- -g /tmp/a.txt:3
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
  │     ├─ HTTP 200 → 结束；带 --wait 就再等窗口删 marker（见下）
  │     └─ 否则 stderr 提示 + 回退 CLI
  └─ 翻不了（未知选项 / -- / 无参数 / --wait 但没给文件）或没有 socket
        → 交给 remote-cli（code / buddycn / trae-cn，从 PATH 或 EDIT_CLI 找）
```

带 `--interactive` 时先多一步：列出窗口让你挑，把挑中的 socket 写回
`os.environ[IPC_HOOK]`，再走上面这张图 —— 所以"当前窗口"可以是挑出来的那个，
且回退到 CLI 时它继承的也是同一个 hook（不用先 `--init` 导入）。
只保证**打开**，不保证那个窗口被置前（见下"打开 ≠ 激活"）。

挑窗口这一步，装了 fzf 且 stdin 是 tty 就交给 fzf（`use_fzf()`）：

- 候选行（就是 `--list` 那张表）喂 fzf 的 stdin，`--header-lines=1` 把表头固定住；
- 它的界面走它自己的 stderr（继承终端），**我们的 stdout 留给初始化片段**，
  选中项从它的 stdout 读回来，按行首编号反查候选项（`socket_number()`）；
- 没选中（Esc / Ctrl-C）、认不出行、拉不起来：一律落回"列编号 + 读一行"那套，
  行为和不装 fzf 时一模一样；
- `EDIT_FZF=0 / off / never` 显式关（测试里必须关，否则会真拉起一个选择器）。

### `--wait` 是怎么等的

`remote-cli` 的做法（`server-cli.js`，抓自本机安装目录）：

```js
if (i.wait) { if (!f.length) {…报错…; return}  d = lo(a) }   // mkstemp 空文件
C1({type:"open", …, waitMarkerFilePath:d, …})                 // 发报文
if (d) await Co(d)                                            // 等 marker 被删
async function Co(e){ for(; existsSync(e);) await sleep(1s) } // 1 秒轮询
```

窗口那一侧（`server-main.js`）把 `waitMarkerFilePath` 转成 `waitMarkerFileURI`
交给 `_remoteCLI.windowOpen`，**关掉那个文件时就把它删掉** —— 这就是"通知"。
我们照抄：

- `make_marker()`：`tempfile.mkstemp(prefix='edit-wait-')`，空文件；
- 报文里多一个 `waitMarkerFilePath`（fixtures 的 `open-wait` 就是这份快照，
  已经标成 `direct:true`）；
- `wait_marker()`：`while exists: sleep(1s)`，间隔照抄 CLI；Ctrl-C 时先把
  marker 删掉再抛（main 那里转成 130）；
- 翻不出来 / 发失败 / `--dry-run` 都把 marker 收回：交回 CLI 时它自己会造一个。
- 真机验证过了（`edit --wait <文件>` 挂后台，在窗口里关掉该标签页）：窗口接受
  带 `waitMarkerFilePath` 的报文、关文件时删掉 marker、我们退出 0 —— 不起 node。

`-w` 是 `--wait` 的别名（同上源码里 `wait:{type:"boolean",alias:"w"}`）。
`--wait` 只给目录不认（CLI 要求至少一个文件），这种就交回 CLI 让它报错。

`--dry-run` 会告诉你走哪条：直连打印 `socket <路径> {json}`，CLI 路径打印模拟的命令行。

### 打开 ≠ 激活（已知限制，别再去找"少发了什么"）

`--interactive` 挑别的 IDE 的窗口：`HTTP 200`、文件确实打开了，**但那个窗口不会被置前**。
实测（同一个 Trae 窗口，三个不同文件，各间隔 8s）：

| 方式 | 结果 |
|---|---|
| A 我们的直连 | 打开，不激活 |
| B 真 CLI `buddycn <文件>` | 打开，不激活 |
| C 真 CLI `buddycn -r <文件>` | 打开，不激活 |

不是我们漏了什么：

- open 报文就那 12 个字段（`type` / `fileURIs` / `folderURIs` / `diffMode` /
  `mergeMode` / `addMode` / `removeMode` / `gotoLineMode` / `forceReuseWindow` /
  `forceNewWindow` / `waitMarkerFilePath` / `remoteAuthority`），**没有 focus /
  activate 之类的东西**；
- `server-cli.js` 里 grep 不到 `focus`，发完报文就收工，没有后续动作；
- 我们发的和它逐字节一致（fixtures 保证），此环境无 `VSCODE_CLI_AUTHORITY`，
  `remoteAuthority` 两边都是空 —— 连唯一可能带窗口语义的字段都一样。

所以置前是**客户端 / 窗口管理器**层面的事（remote 下请求还是从隧道过来的），
服务器这边没法通过这条 socket 左右，官方 CLI 同款行为。要那个窗口到前面来，
只能自己点过去。

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

1. ~~`--wait`~~ 已直连（见上：mkstemp marker + 等窗口删它，与 CLI 同机制）。
   `-g` / `--goto` 也已直连：取值就是跳转目标，无条件按 `:行号[:列]` 拆
   （`split_goto()`，不做"真实文件优先"那层判断 —— CLI 也是这么拆的，
   fixtures 的 `open-goto-short` / `open-goto-flag` 都是证据）。取值缺失或
   又是个选项时交回 CLI 让它报错。
   `--merge` / `-m` 也已直连：吃 4 个路径（path1 path2 base result）原样进
   `fileURIs` 并置 `mergeMode`，不足 4 个、或某个取值又是个选项，交回 CLI
   （fixtures 的 `open-merge` / `open-merge-short` 已标 `direct:true`）。
   路径是相对时 CLI 也按 cwd 解成绝对（试过 `-m rel1 …` -> `file:///tmp/rel1`）。
   真机验过：`edit -m <4 个路径>` 发给另一个窗口，退出 0（窗口收下，不起 node）。
2. ~~`--interactive` 选中的窗口**直接开文件**~~ 已支持：`edit --interactive <文件>`
   挑完窗口把 socket 早期写回 `os.environ[IPC_HOOK]`，四个 `current_socket()`
   调用点一行没改 —— 直连、--init 的默认值、回退 CLI 继承的环境全都跟着走。
   不带文件、与 `--list` 冲突、取消（q / EOF）都报错退出。挑别的 IDE 时只打开、
   不激活那个窗口（限制见上，与官方 CLI 一致，不用再查）。
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
