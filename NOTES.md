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
| `edit -g a.txt:3` | 同上：`-g` 被忽略，跟位置参数 `a.txt:3` 完全一样（直连，与 CLI 一致） |
| `edit -r a.txt` | `forceReuseWindow:true` |
| `edit -n a.txt` | `forceNewWindow:true` |
| `edit -a a.txt` | `addMode:true` |
| `edit -d a.txt b.txt` | `diffMode:true`，两个 `fileURIs` |
| `edit -m a.txt b.txt base result` | `mergeMode:true`，四个 `fileURIs`（path1 path2 base result） |
| `edit somedir/` | 进 `folderURIs`，`fileURIs` 为空 |

URI 编码与 `remote-cli` 逐字节一致：空格 `%20`、非 ASCII 按 UTF-8 percent 编码，
**行号前的冒号不转义**（所以不能用 `pathlib.Path.as_uri()`，它会把 `:` 编成 `%3A`）。

`remoteAuthority` / `waitMarkerFilePath` 只有在对应场景才发，普通 open 没有。
`--wait` 时多一个 `waitMarkerFilePath`（CLI 现造的临时文件，每次路径都不同）。

**唯一与 CLI 故意不同的字段**：`gotoLineMode`，两个方向各一格：

- 我们**多发**：位置参数 `code file:3` 发的是 `false`（`:3` 照样拼在 URI 里，也就是
  不跳行），而 `edit file:3` 要的是"跳到第 3 行"，所以按 `--goto` 的语义发 `true`；
- 我们**少发**：`edit -g f`（目标没有行号）发 `false`，CLI 发 `true` —— 我们忽略 `-g`
  之后就不知道"用户想跳转"，但 URI 里没有行号可解析，行为等价。

这两格都记在 fixtures 对应条目的 `diff` 里，不是 bug。

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
  └─ 翻不了（未知选项 / -- / 无参数 / 没有 socket）
        → 交给 remote-cli（code / buddycn / trae-cn，从 PATH 或 EDIT_CLI 找）

先拦一道：-a / -d / --wait 空着（没文件也没目录）→ `edit: -d 后面没有文件或
目录`，退出 1，不交给 CLI。裸调用与只给 -r / -n 照旧走上面的回退 —— 实测那几个
在真 CLI 里都会真的发报文（裸调用 = 开/聚焦窗口，-r = 复用窗口，-n = 新窗口），
空发但都有定义。
```

带 `--interactive` 时先多一步：列出窗口让你挑，把挑中的 socket 写回
`os.environ[IPC_HOOK]`，再走上面这张图 —— 所以"当前窗口"可以是挑出来的那个，
且回退到 CLI 时它继承的也是同一个 hook（不用先 `--init` 导入）。
只保证**打开**，不保证那个窗口被置前（见下"打开 ≠ 激活"）。

**没有 hook 时**还有两条路，都不需要 stdin：

- `--first`：取候选的第一个直连（`pick_first()`）。候选已按创建时间倒序，所以就是
  **最新的那个窗口** —— 等效于 `--interactive` 敲 1，但能写进脚本；一个候选都没有
  就报错退出（明确，好过悄悄回退去开 vim）。
- 不显式要就照旧交回 CLI。但如果选中的是 **remote-cli**（用现成的
  `have_remote_cli()` 判目录结构），那它**必定拒绝** —— 它只认 IDE 集成终端，原话是
  `Command is only available in WSL or inside a Visual Studio Code terminal.`，
  看不出该干什么。所以这种时候 `hint_remote_cli()` 换成能照做的提示（缺 hook、
  hook 指向的 socket 已不通，两种原因分开说，并报一下有几个窗口可挑）。
  **只在 remote-cli 这条路上打**：vim / `$EDITOR` 场景（比如 `git commit`）一个字不多打。
  这条容易踩：`sudo` / `su` / `env -i` / 从别处起的 tmux 里 PATH 可能仍带着
  `<安装目录>/bin/remote-cli`，`find_path_cli()` 按产品名会撞上它（`find_remote_cli()`
  有 hook 门控、会跳过，绕过门控的就是它）。

挑窗口这一步，装了 fzf 且 stdin 是 tty 就交给 fzf（`use_fzf()`）：

- 候选行（就是 `--list` 那张表）喂 fzf 的 stdin，`--header-lines=1` 把表头固定住；
- 它的界面走它自己的 stderr（继承终端），**我们的 stdout 留给初始化片段**，
  选中项从它的 stdout 读回来，按行首编号反查候选项（`socket_number()`）；
- 没选中（Esc / Ctrl-C）、认不出行、拉不起来：一律落回"列编号 + 读一行"那套，
  行为和不装 fzf 时一模一样；
- `EDIT_FZF` 设成 `ENV_OFF` 那套（空 / 0 / false / f / off / no / n / never，大小写
  不敏感）就显式关 —— 和 `EDIT_DEBUG` 共用 `env_flag()`，不各写一套；测试里必须关
  （否则会真拉起一个选择器）。

### 命令行只扫一次：normalize + 两个后端

早先每个功能各扫一遍命令行（`open_request` 认选项翻报文、`wants_wait` 找 `--wait`、
`drop_wait` 摘 `--wait`、`apply_goto` / `goto_args` / `abspath_args` / `has_goto`
再改写一遍给 CLI），加一个选项要动三四处。现在只扫一次：

```
args --normalize--> [token] --to_msg---> open 报文（socket 后端）
                           \-to_argv--> CLI 命令行（CLI 后端，按 kind 查 EMIT）
```

叫 `normalize` 而不是 `tokenize`：它不做保真的一比一还原，`-g` / `--goto` 这类选项
会被消化掉（见下），留下来的只有 token 之间的**顺序**。

- `OPTIONS`：名字 -> (报文字段, 取值个数)，认识的参数就这一张表（只剩开关与
  `-m` / `--merge`）；
- token 是 tuple：`('opt', 名字, 报文字段, [取值])` / `('goto', 文件, 行号, 列号)` /
  `('file', 路径)` / `('folder', 路径)` / `('other', 原文)`；
- `EMIT`：每个 kind 怎么翻译（goto 写成什么、`--wait` 保不保留、路径转不转绝对、
  跳转选项是不是只能给一次）—— "针对不同程序翻译命令"就这一张表；
- 认不出来的（不认识的选项、取值不够的、`--` 之后的字面量）一律整成
  `('other', 原文)`：socket 后端见它就返回 None 交回 CLI，CLI 后端原样吐回去。

两条约束：

1. **保序**：中间表示是列表，不是"字段袋" —— 否则 `buddycn --locale zh -r f`
   会被重排，语义就变了（旧代码里 `apply_goto` "就地成对插"就是在保序，只是
   这一点藏得太深）。
2. **认不出的原样透传**：不认识的选项只能标注、不能报错，回退时照原样交给 CLI；
   认得的（`-g`）不保证原样 —— 它会被归一化掉（下一节）。

重构时拿 HEAD 的旧实现逐条对照过：27 组参数 × 2 种 marker × 3 种 kind，两个后端
的输出**全部一致**；护栏还有 72 个测试 + fixtures（真 CLI 报文快照）。

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

### 交回别的 CLI 时摘掉 VS Code 系的开关

`--wait` / `-w` / `-r` / `-n` / `-a` / `-d` / `-m` 都是 VS Code 系的开关（直连时各自
对应报文里的一个字段）。别的 CLI 拿到这些短选项，含义一个比一个偏 —— 实测（本机
vim 9.1 / nano 7.2 / emacs 29.4 / emacsclient 29.4）：

| 选项 | vim | nano | emacs | emacsclient |
|---|---|---|---|---|
| `-r` | 列/恢复交换文件 | `-r <数字>`：把文件名当填充宽度 | `-rv` 反色显示 | `--reuse-frame` |
| `-n` | 不用交换文件 | `--noread`：**只写不读** | 未知选项，报错 | `--no-wait` |
| `-a` | 未知选项，报错 | `--atblanks` | 未知选项，报错 | 要参数，报错 |
| `-d` | **就是 diff 模式（等价）** | `--rebinddelete` | `-d display` **吃文件名** | `-d display` 吃文件名 |
| `-m` | 禁止写文件 | `--mouse` | 未知选项，报错 | `unrecognized option` |
| `-w` | `-w <scriptout>`：把命令写进文件 | — | — | `--timeout=SECONDS`（要数字） |
| `--wait` | 未知选项，报错 | — | 未知选项，报错 | 未知选项，报错 |

于是 `EMIT` 里**一个选项一项**（键就是 token 的 `field` 名：`wait` /
`forceReuseWindow` / `forceNewWindow` / `addMode` / `diffMode` / `mergeMode`，
不共用 —— 每项在别的 CLI 里的含义都不同，逐项的注释就是上面这张表；同名是刻意的，
`to_argv` 里 `emit[field]` 直接查表），认不出就摘掉。两个例外：

- `-d` 对 vim 是**正解**（`vim -d a b` = vimdiff），所以 vim 那一项是 True、保留；
- `-m`（合并，带 4 个路径）没有等价物：**丢开关、留取值** —— 那四个路径照样当文件
  打开，总比把用户要编辑的文件一起丢掉好。

emacs 系**没有命令行的 diff 入口**：`emacs --help` 里只有 `--eval EXPR` /
`--execute EXPR` / `-f FUNC`（没有 `--diff`，也没有 `-e`），`emacsclient` 是
`-e, --eval`。`-f ediff-files` 也不行 —— 它是交互式函数，会去 minibuffer 提问，不吃
命令行上的文件名。**所以这块不翻译**：ediff 的两个文件是位置参数（`-d` 的 arity 是 0，
文件个数与它无关），要重写就得整条命令一起改造，还要处理 Lisp 转义。想 diff 就这么写
（两条都实测过，pty 里真的开出了 `*Ediff Control Panel*`）：

```
emacs -nw --eval '(ediff-files "A" "B")'                  # 终端；GUI 版去掉 -nw
emacsclient -t -e '(progn (ediff-files "A" "B") nil)'     # 必须先有 frame（-t 或 -c）
```

（`emacsclient -e` 而 daemon 里没有 frame 时，`ediff-files` 会静默返回 nil、什么都不
显示 —— 实测；`nil` 是为了不让 emacsclient 把求值结果回显。三方 diff 用
`ediff-files3`，它也存在。nano 则**完全没有** diff 模式。）

老规矩仍然成立：终端 vim 本来就前台阻塞、退出才返回，所以把 `--wait` 摘掉正好
（GUI 版 gvim / mvim 会 fork 后立刻返回，那要 `-f`（foreground）—— 但本机 `vim -f`
退出 1、`vim -h` 里也没有，那是 GUI 版才有的开关，所以**不翻译**）；emacsclient 默认
也阻塞到 server 缓冲区结束，`--wait` 的语义天然满足。

`--dry-run` 会告诉你走哪条：直连打印 `socket <路径> {json}`，CLI 路径打印模拟的命令行。

### -g / --goto 直接被忽略

`-g` / `--goto` 的语义只有一条：置 `gotoLineMode`。而 edit 对**任何**带行号的位置
参数本来就置它（见上"唯一与 CLI 故意不同的字段"），所以这两个选项在 edit 里没有
信息量 —— `-g f:3` 与 `f:3` 发出的是同一份报文、同一个命令行，于是直接忽略：

- `-g` / `--goto` **不消费参数**：后面那个参数自己按位置参数处理，所以 `-g -r f:3`
  里 `-r` 仍然是选项。真 CLI 也是这么理解的（实测 `buddycn -g -r` 发的是
  `gotoLineMode:true` + `forceReuseWindow:true` + 空 fileURIs）；
- 内联写法 `--goto=X` / `-g=X` **不特判**，跟别的"不认识的选项"一样整成
  `('other', 原文)` 交给 CLI —— 上游自己都不认这种写法（实测 `buddycn --goto=f:3`
  把取值当布尔丢了、`-g=f:3` 把取值塞进 `gotoLineMode` 字段，两者 fileURIs 都是空的），
  我们没必要比上游多支持一种语法；
- 于是"是否跳转"的唯一裁判是 `parse_goto`（位置参数那两步：真实文件优先 +
  `非目录:数字[:数字]`），`split_goto` 退化成它内部的一步。

顺带修掉两处对不齐 CLI 的地方（都是实测）：

| 命令 | 旧行为 | 真 CLI | 现在 |
|---|---|---|---|
| `edit -g <目录>` | 目录进 `fileURIs` | `folderURIs` | `folderURIs` |
| `edit -g f`（值没行号） | 置 `gotoLineMode` | 置 | 不置（URI 相同、没行号可跳，看不出差别） |

代价是 `-g x:3` 且真实存在名为 `x:3` 的文件时按"真实文件优先"、不跳行 —— 位置参数
今天也是这个行为，统一判断必然如此。

**绝不能把 `-g` 原样透传**给别的 CLI（这是忽略它的收益之一）：

- vim：`vim -g f` -> `E25: GUI cannot be used: Not enabled at compile time`，退出 2
  （`-g` 是启动 GUI）；
- emacs（29.4 实测）：`--help` 写着 `--geometry, -g GEOMETRY`，于是 `-g` 把后面的
  **文件名吃掉当几何参数** —— `--batch -g f` 里 `(buffer-file-name)` 是 `nil`
  （不带 `-g` 才是 f）：既不报错也不打开文件，比 vim 的 E25 更隐蔽；
- emacsclient（29.4 实测）：`unrecognized option '-g'`；
- nano：`-g` 是 `--showcursor`（"在文件浏览器和帮助里显示光标"），跟跳转无关；
- 认不出是哪一类的（kind 为 None）：压根没这个选项。

行号只在交回 CLI 时才需要翻译，按 kind 查 `EMIT['goto']`：code 系
`--goto 文件:行:列`（一个目标一份 —— 实测 CLI 的 `-g` 可以重复，`buddycn -g a:3 -g b:9`
与 `-g a:3 b:9` 发出的报文逐字节相同）、vim 系 `+行号`、认不出的一类只传文件
（`ed a.txt:3` 会去开/建一个叫 `a.txt:3` 的文件）。真机（`--dry-run`，去掉 socket
才走得到 CLI 路径）：

```
edit -g /tmp/a.txt:3  ->  /usr/bin/vim  +3 /tmp/a.txt
                          /usr/bin/nano +3 /tmp/a.txt
                          /usr/local/bin/emacs       +3 /tmp/a.txt
                          /usr/local/bin/emacsclient +3 /tmp/a.txt
                          /usr/bin/ed   /tmp/a.txt
edit -g /tmp/a.txt    ->  /usr/bin/vim  /tmp/a.txt        # 没行号：只留文件
edit -g /tmp/a.txt:3 /tmp/b.txt:9
                      ->  re…/buddycn --goto /tmp/a.txt:3 --goto /tmp/b.txt:9
```

行号写法各家一致（`+N f`），**只有列号不同**：

| kind | 带列吗 | 写法 |
|---|---|---|
| code 系 | 带 | `--goto 文件:行:列`（列跟行同一串） |
| emacs / emacsclient | 带 | `+N:M`（冒号，和我们的 `文件:行号:列` 同源） |
| nano | 带 | `+N,M`（逗号） |
| vim | 不带 | `+N`（vim 靠 `+{命令}` / `-c`） |

所以 nano / emacs 各是一个 kind（`CLI_KIND_NANO` / `CLI_KIND_EMACS`），
`EMIT` 里各挂一个 `goto_plus(sep)`（vim 那行是 `goto_plus(None)`）。基准两边都是 **1 起**（emacs 29.4 实测
`+3:5` 的光标落在 0 起第 4 列；nano 的 man 写"默认是 line 1, column 1"），
和我们自己的 `文件:行号:列` 一致，拼接时不用 ±1。

实测互不兼容（所以必须分开给）：emacs 拿到 `+3,5` 退化到第 1 行，nano 拿到
`+3:5` 报 `Invalid`。

两个没测到 / 已知不管的：

- nano 的光标列**没实测**（curses 屏抓不到、poslog 也没写出来），只确认了给它
  `+3,5` 不报错、也不会冒出名为 `+3,5` 的文件；
- 老版本 nano 可能只认 `+line`，那种会把 `+3,5` 当文件名（打开/新建它）。
  没法探测版本，**已知不管**。

翻译出来的 `vim +3 f` 真跳：真 pty 下 `call writefile([line(".")], …)` 写出 `3`
（`-es` 是 ex 模式，光标规则不一样，不能拿它测这个）。

多个文件各带行号（`edit a.txt:3 b.txt:9`）vim 只会把两个 `+N` 依次用在第一个
buffer 上 —— 只有位置参数的版本里就已经是这样，不是这次引入的。

### 认不出产品名时怎么定 kind（`cli_kind` 的两条判据）

1. 先比 basename 查 `CLI_KIND`（`code` / `vim` / `nano` / `emacs`）；
2. 名字不在表里、但路径是 `<安装目录>/bin/remote-cli/<产品>`，**且上两级有可执行的
   `node`**，就按 VS Code 系处理 —— 新产品名不必进白名单。

第 2 条那个 `node` 是**故意的防误判**：目录名恰好叫 `remote-cli` 的自制目录、别家
工具都能撞上，只看目录名会把它们的行号翻成 `--goto`、把 `--wait` 留下来（对
vim / nano / emacs 那几家是有害的，见上两节）。要求"上两级有 `node`"才是 server
端包装脚本的特征（`<安装目录>/bin/<版本>/bin/remote-cli/<产品>` 的包装脚本会
exec 上一层目录里的 `node`）—— 和"窗口发现"里认 socket 用的是**同一个结构事实**。

代价：`find_remote_cli` 复用同一个判据，所以也变严了 —— 真遇到没有 `node` 的安装
就不再认它，会退回 `$VISUAL` / `$EDITOR` / vim 兜底。本机实测
`<安装目录>/bin/<版本>/node` 存在且可执行（123MB），满足。用例：
`CliArgvTest.test_future_remote_cli_like_code`（造一个假 `future-code` + `node`）。

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
- 表里第一列是 socket 的**创建时间**（`sock_created()`，取文件 mtime，理由同 `--prune`；
  文件不在了显示 `?`）：同一个窗口会同时挂着好几个 socket（实测十分钟内三个），
  时间是目前唯一能区分它们的字段。
- 候选按创建时间**倒序**（新的排最前，`find_sockets()` 的返回契约）：最新的那个才是
  当前会话。这份顺序 `--list` 的表、`#` 编号、`--interactive` 的编号输入与 fzf 的行序
  全部共用 —— 只有一处排序，编号就不会和看到的行错位。
- **读不到创建时间的不丢**（文件已被删 / 无权限）：当最旧沉到最后，表里显示 `?`。
  丢掉会让"还有几个窗口"答不准，也和 `sock_created` / `probe_workspaces` 的 `?` 降级
  不一致；加上 `connect()` 需要和 `stat()` 同样的目录权限，"stat 不到但连得上"基本不存在，
  丢掉换不来什么。
- 同一时间退回**路径序**（先按路径排一遍，再稳定地按时间倒序）：`/proc` 的枚举顺序不稳，
  而编号是靠位置认的，顺序必须确定。实测这台机器连续 6 次 `bind()` 拿到的 `st_mtime_ns`
  **完全相同**（内核记 mtime 用粗粒度时钟）—— 同一个 tick 内的几个 socket 本来就分不出
  先后，跨 tick 才分得出（真实场景里间隔几分钟，够用）。所以测试要断言编号就得用
  `os.utime` 把时间钉住（`ProcCase.pin_created`），不能指望 bind 的先后。

### `--prune`：清掉死掉的 socket

IDE 每次 listen 一个新 UUID 的 socket、旧的既不关也不删文件，于是
`$XDG_RUNTIME_DIR` 里会越攒越多（这台机器 582 个，只有 3 个还活着）。判"死"用的
就是 `find_sockets()` 那份数据 —— 抽成了 `unix_bind_paths()`，两边共用一份解析：

- 名字是 `vscode-ipc-*.sock` **且** `S_ISSOCK`（同名的普通文件不动）**且**路径不在
  `/proc/net/unix` 里（还 bind 着一个都不动）；只扫 `$XDG_RUNTIME_DIR` / `$TMPDIR` /
  hook 所在目录，不递归；没有 `/proc`（macOS）直接报错退出，一个也不删。
- **不能拿 connect 探测判死**：实测刚 `bind()` 还没 `listen()` 的 unix socket，
  `connect()` 直接 `ECONNREFUSED` —— 和"文件已死"完全一样的错。所以只信 `/proc/net/unix`。
- 显示的"创建时间"是 `st_mtime`：Linux 上 `st_birthtime` 拿不到（实测 AttributeError），
  而 socket 文件 bind 之后没人再写它（实测收发数据后 mtime / ctime 都不变），
  所以 mtime 就是 bind 那一刻。
- `--dry-run` 复用既有开关：同一份清单，末尾换成"（--dry-run：没有真删）"。
- **测试的安全线**：`PruneTest` 一律把 `prune_dirs` patch 成临时目录 —— 真实
  `$XDG_RUNTIME_DIR` 一个 socket 都不许碰（唯一的真删路径也只扫临时目录）。

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
   `-g` / `--goto` 现在直接忽略（取值按位置参数走，所以照旧直连；
   fixtures 的 `open-goto-short` / `open-goto-flag` 报文仍逐字节对得上）。
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
   的 node 判据过滤了。放宽判据即可复用同一条直连路径。**暂时不做**，记下要留意的点：

   - 那条判据现在**三处共用**：窗口发现（`find_sockets`）、`find_remote_cli`、
     `cli_kind` 的兜底 —— 放宽会同时影响这三处，别只改一处；
   - 未决的是"怎么把桌面版窗口 socket 和普通 unix socket 区分开"：看路径形态
     （如 `$TMPDIR` 下的 `vscode-ipc-*`）还是对候选发一次只读 `{"type":"status"}`
     探活，各有代价（前者可能误收别人的 socket，后者多一次往返）；
   - 手边**没有桌面版环境可实测**，只能靠 fixtures + 假 `/proc` 推 —— 落地前先想清楚
     怎么验证。

4. ~~`goto` 渲染的优化~~ 已做：`emit['goto']` 现在吃**一个跳转目标元组**（数据源
   本来就是 `('goto', f, line, c)`，唯一那处调用不用再 `*` 解包了，也和
   `goto_target(goto)` 同风格）；三种形状各是一个函数 —— `goto_inline(flag)`（code）、
   `goto_plus(sep)`（vim 用 `None`、nano `,`、emacs 系 `:`）、`goto_file`（认不出：
   只留文件）。`plus_goto` / `plus_col` 不再存在：vim 那行就是 `goto_plus(None)`，
   条件写成 `if sep and column` 一句覆盖三家。认不出的那类**没有**并进 inline ——
   `goto_inline` 会把行号一起带上，那是行为变化（`goto_file` 的 docstring 里点明了）。
   顺带在 `goto_target` 的 docstring 里写明它为何自己 abspath。行为不变：五个 kind 的
   `--dry-run` 输出与改前逐字一致（`--goto f:3:5` / `+3 f` / `+3,5 f` / `+3:5 f` /
   只给 `f`）。

5. `cli_argv(args, kind)` 是**测试缝**：`test_edit.py` 26 处用它换一行的可读，而生产
   路径不能用它（同一份 token 要喂 `to_msg` 和 `to_argv`，粘回去就等于扫两遍）。
   要不要在 docstring 里点明这一点、或干脆挪进测试文件，**暂时不动**。

6. ~~回归脚本还能补：`status` 探测、`--list` / `--init` 的输出~~ 已补：`PROC` 可注入
   + `make_proc()` 造假进程表，见 `FindSocketsTest` / `ProbeTest` / `ListTest` /
   `InitTest`（进程内跑 `main()`，`sys.argv` / `stdout` / `input` 都打补丁）。

7. ~~token 分层重写（`match` + 类型化 + mypy 接进检查）~~ 已做（4 步：`34f0489` 定类型、
   `a474c65` to_msg、`c8754ea` to_argv + EMIT 行、`79f65ff` 兜底与标注）：

   - token 是**带 `Literal` 标签的元组联合**（`Token` / `ArgToken` / `GotoTarget`，
     每个形状还各有一个别名）。**没选 NamedTuple**：运行时表示不变 → doctest 与调试
     输出逐字不变；字段名交给 `match` 的 value pattern（`case ('opt', flag, field, values)`）。
     两者启动代价几乎一样（都 ≈ +4~5 ms，主要是 `import typing`），而 NamedTuple 会把
     13 行 doctest 的期望输出从最长 90 列推到 119 列（repr 单行、doctest 折不了）。
   - `to_msg` / `to_argv` 的分派换成 `match` + `case _: raise AssertionError(t)` 兜底
     （`typing.assert_never` 是 3.11+，手写；实测 mypy 不报 unreachable）。
   - 报文与 EMIT 行各有一个 TypedDict（`OpenMsg` / `EmitRow`）。`waitMarkerFilePath`
     与 `NotRequired` 同理（3.11+）：用 `total=False` 继承表达"选填"。
   - mypy 接进门禁：`[tool.mypy]`（`check_untyped_defs` + `files` 三个文件），
     `uv run mypy` 干净。它顺带抓出并修掉：test 里 `spec` 可能是 None、
     `SystemExit.code` 的类型、`lambda: … and os.unlink(…)`（返回 None 还当值用）、
     `capture_cli` 的 `out` 被推成 `dict[str, str]`。
   - 收尾（`988a52e` 之后）：EMIT 那 6 个开关键改成与 token 的 `field` 同名
     （`reuse_window` → `forceReuseWindow`、`add` → `addMode`…），于是 `to_argv` 里
     6 条 `if field == … and not emit[…]` 收成 `if not emit[field]:`（加一个开关只需要
     往 EMIT 那几行加一项）。类型上正好对上：`field: OptionField` 那 6 个字面量 =
     `EmitRow` 的 6 个布尔键。
   - 还剩一件（不急）：`--strict` 还有 91 条，要上得另开一轮。
   - 门槛提醒仍然成立：`match` 是 3.9 的**语法错误**，解析期就炸、程序内做不了友好
     提示（README 开头已写明最低 3.10）；本机只有 3.12，旧版本机器没法实测。

## 历史是怎么来的

`edit.py` 的历史是从 config 仓库按文件重放过来的：19 条提交里重放 16 条
（3 条纯改名因为内容没变被跳过），作者、日期、提交信息都保留，SHA 全新。

- 新仓库的最新提交 `b81db7c` ↔ config 的 `61a4ff2`（内容逐字节一致）；
- 再往前还包括 2020 年在 `bin/.bin/edit`、2022 年 `bin/.local/bin/edit` 的提交。
