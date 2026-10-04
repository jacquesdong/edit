# edit

把文件（可带 `:行号[:列]`）打开在**当前 IDE 窗口**里的小工具。

本仓库从 dotfiles（`~/config`）拆出来单独维护：`edit.py` 的历史是按文件重放过来的
（`config@61a4ff2` 的 `scripts/.scripts/edit.py`，含改名前 `bin/.bin/edit` 的 2020 年提交；
3 条纯改名的提交因为内容未变没有重放）。dotfiles 里那份仍在，**由使用者手动同步**。

背景、协议细节（怎么抓包、字段怎么映射）与待办见 [NOTES.md](NOTES.md)。

需要 **Python 3.10+**（`requires-python` 在 `pyproject.toml` 里）—— token 分派要改写成
`match`（PEP 634），有意把下限从 3.8 抬到 3.10。3.9 上 `match` 是**语法错误**：在那一行
直接 `SyntaxError`，解析期就炸，程序里做不了"版本太低"的友好提示，换机器时留意这条。

## 用法

```
edit <文件...>               在当前 IDE 窗口打开文件
edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
edit --wait <文件>           等文件在编辑器里被关掉才返回（当 $EDITOR / core.editor 用）
edit -m <文件> <文件> <base> <结果>   三向合并（VS Code 系的 --merge）
edit --open <链接...>        把链接交给系统（本地）浏览器打开，不起 node
                             （fish: set -Ux BROWSER 'edit --open'，help 就走它）
edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
eval "$(edit --init bash)"   同上（bash / sh / dash）

EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
edit --list                  列出存活的 IDE 窗口（最新的排最前；每行带 socket 创建时间，
                             用来区分同一窗口的多个 socket；只读、不读 stdin，会问各
                             窗口 workspace）
edit --first <文件>          没有 hook 时也开在窗口里：取 --list 的第一个（最新那个），
                             不提问、不读 stdin（脚本里能用；要自己挑用 --interactive）
edit --prune                 清掉死掉的 vscode-ipc socket（没人 bind 的那些；逐条打印
                             创建时间与路径，--dry-run 只看不删）
edit --usage                 打印完整用法（--help 是透传给 IDE CLI 的）

edit --init fish --interactive   列出窗口并挑一个，输出它的初始化片段
                                 （普通终端里没有 hook 时用这个）
edit --interactive <文件...>     挑一个窗口，在挑中的那个里打开文件

EDIT_FZF=0 edit … --interactive  不用 fzf，改用编号挑（脚本里本来就是编号）

edit --color=always …            给输出上色（窗口表的表头、当前窗口那颗 *、--debug
                                 日志的时间戳与 <D>/<E>）；不传=auto：只在这条流是
                                 终端时上色，TERM=dumb 或设了 NO_COLOR 就不上色。
                                 --list 看 stdout、提示与日志看 stderr，各判各的。
                                 EDIT_COLOR=never 等价（edit 被当 $EDITOR 调起时用）；
                                 auto 下还认 FORCE_COLOR（非空且不是 0/false 就强制
                                 上色，压过 TERM=dumb / NO_COLOR / 不是终端）。
                                 裸 --color 后面不能直接跟文件（文件名会被当取值），
                                 那种写法要写 --color=always <文件>
```

着色只落在"结构性"的那几处，正文一律不着色；`--init` 的片段和喂给 fzf 的候选行
**永远不上色**（前者要被 `source`、后者 fzf 没加 `--ansi` 会把转义画出来）。配色与
三态判据移植自 `fixcomm-py` 的 `c3ebf44`，取舍记在 NOTES。

`--open` 走的是第三种报文 `{"type":"openExternal","uris":[…]}`（remote-cli 的
`--openExternal` 就是它，IDE 的 `bin/helpers/browser.sh` 也是这么开网页的）：链接不是
文件，塞进 `fileURIs` 会变成 `file:///当前目录/https:/…`，所以它单独一条路 —— 取值
原样当 `uris` 发出去，不像链接（没有 `://`）直接报错退出，不悄悄拿去当文件打开。
直连不上时退回两级：code 系 CLI 加 `--openExternal`（和直连等价，只是要起一次 node），
别的 CLI（vim / `$EDITOR`…）就退 `$BROWSER`（fish 的 `help` 认的那个变量，可带参数），
再不行是 `xdg-open`（macOS 才是 `open`：Debian 的 `/usr/bin/open` 是 run-mailcap，吃
文件不吃链接）。`BROWSER` 写的是 `edit --open` 自己时跳过 —— 没有窗口可直连时会一圈圈
exec 回来。

名字有个撞车要心里有数：Debian / Ubuntu 的 `mime-support` 自带 `/usr/bin/edit`
（`run-mailcap` 的别名，还有 `see` / `view` / `compose` / `print`）。我们的 `edit`
靠 `~/.local/bin` 排在 `/usr/bin` 前面压住它 —— 不加载 dotfiles 的 shell（`sh -lc`）、
sudo / cron、以及没放软链的机器上，`edit` 就是 run-mailcap：它按 mime 类型处理**文件**，
本机 `run-mailcap --action=edit a.txt` 直接报 `no "edit" rule for type "text/plain"`
（退出非 0，不会静默做错事，但也打不开文件）。

挑窗口（`--interactive`）时，装了 fzf 且 stdin 是终端就用 fzf 过滤。在 fzf 里 Esc /
Ctrl-C 就是取消（和输编号时按 `q` 一样的收场：一句提示后退出，不再多问一遍）；只有
fzf 拉不起来 / 报错 / 选中的行认不出编号，才落回"列编号 + 读一行"那套 —— 那时行为
和不装 fzf 时一致。fzf 的界面走 stderr，所以
`edit --init fish --interactive | source` 拿到的 stdout 仍然只有初始化片段。

`edit.py` 开头的 docstring 是完整的用法与原理说明，`edit --usage` 打的就是它。

## 两条执行路径

1. **直连窗口 socket**（有 `VSCODE_IPC_HOOK_CLI` 时）：往 socket POST 一个 JSON
   —— `{"type":"open","fileURIs":[…],"gotoLineMode":…}`，行号按 VS Code 的写法拼在
   URI 里（`file:///x.py:12:3`，冒号不转义）。协议是从 `remote-cli`（`out/server-cli.js`）
   抓包对出来的，字段与它逐字节一致；回复只认 HTTP 200。
   这条路径不需要 PATH 里有 `remote-cli`，也不起 node。
2. **remote-cli**：没有 socket（桌面版），或参数翻不了（未知选项 / `-m` 的取值
   没给够 / 无参数）时，照旧找 `code` / `buddycn` / `trae-cn` 去开。
   直连失败也会回退到这里，并在 stderr 留一行提示。

`-a` / `--wait` 空着（既没文件也没目录）算误用：`-d` 要 2 个文件、`-m` 要
4 个路径，不足直接 `edit: ...` 退出 1，不交给 CLI。裸调用、只给 `-r` / `-n` 不拦 —— 那是 `code` 系
"开窗口 / 复用窗口 / 新窗口"的既定用法。

`--wait` / `-w` 也走直连：先 mkstemp 一个空 marker，把路径放进报文的
`waitMarkerFilePath`，窗口关掉文件时删它，我们等它消失 —— 和 `remote-cli` 同机制
（它也是"造 marker + 每秒轮询"），所以当 `$EDITOR` / `core.editor` 用时全程不起 node。
它是 VS Code 系的选项：交回 vim 系 CLI 时会被摘掉（vim 没有 `--wait`，`-w` 还是
"把键入的命令写进文件"的意思；emacsclient 的 `-w` 是 `--timeout=SECONDS`；而
终端 vim / emacsclient 本来就等到退出）。

`-g` / `--goto` 直接**忽略**：行号只认位置参数写法（`文件:行号[:列]`），而 edit 对带
行号的参数本来就置 `gotoLineMode`，所以 `-g f:3` 和 `f:3` 完全等价；它们也不消费后面
的参数（`-g -r f:3` 里 `-r` 仍然是选项）。内联写法 `--goto=X` / `-g=X` **不特判** ——
上游自己也不认这种写法（实测 `--goto=f:3` 把取值丢了、`-g=f:3` 把取值塞进
`gotoLineMode` 字段，两者都没有文件），所以跟别的"不认识的选项"一样原样交给 CLI。

行号只在交回别的 CLI 时才需要翻译：code 系 `--goto 文件:行:列`（一个目标一份 ——
实测 CLI 的 `-g` 可以重复，报文是累加的）、vim 系 `+行号`、认不出是哪一类的 CLI
只传文件。
所以绝不能把 `-g` 原样透传过去（vim 的 `-g` 是启动 GUI 会 `E25` 退出 2；emacs 的
`-g` 是 `--geometry`，会把后面的文件名吃掉、什么都不打开；nano 的 `-g` 是
`--showcursor`）。

`--wait` 之外那几个 VS Code 系开关也一并按 kind 处理：`-r` / `-n` / `-a` 交回 vim 系时
摘掉（`vim -r` 是恢复交换文件、`nano -n` 是"只写不读"、`emacs -r` 是反色显示…），`-d`
只有 vim 是同义（`vim -d` 就是 vimdiff）所以保留，`-m` 合并没有等价物 —— 丢开关、四个
路径照开。这几项一个选项一项，逐项含义见 NOTES 的那张实测表。

emacs 系没有命令行的 diff 入口（`emacs --help` 里只有 `--eval`；`emacsclient` 是 `-e`），
所以 `-d` 摘掉后只是把文件打开 —— 要 diff 就自己 `M-x ediff-files`，或者用
`emacs --eval '(ediff-files A B)'`（`emacsclient` 得 `-t -e '(progn (ediff-files A B) nil)'`，
要先有 frame；见 NOTES）。

用 `+行号` 的不止 vim：`nano` 是一类、`emacs` 与 `emacsclient` 是一类。列号只有
vim 不支持：VS Code 系 `--goto 文件:行:列`、emacs 系 `+N:M`、nano `+N,M`
（都是 1 起，和我们的写法一致），vim 只用 `+N`。

`--list` / `--init --interactive` 会用同一个 socket 直连问每个候选窗口一次只读
`{"type":"status"}`，从回复的 `Process Argv: --remote <authority> <workspace>` 取得
窗口的 workspace，这样挑窗口时能认出哪个是哪个（失败就显示 `?`）。

## 开发

dev 工具（ruff / mypy）钉在 `uv.lock` 里，命令一律走 `uv run`（首次会自动建 `.venv`）：

```bash
uv sync                          # 建 .venv 并按 uv.lock 装 ruff / mypy（首次，之后可省）
uv run ruff check .              # 0.16.9，配置在 pyproject.toml 的 [tool.ruff]
uv run mypy                      # 2.3.1，配置在 [tool.mypy]（files 已列全，无需传参）
uv run python3 edit.py --self-test      # 纯函数 doctest（不开窗口、毫秒级）
uv run python3 test_edit.py -v          # 回归：假窗口 + 假 CLI，不碰真实 IDE
uv run python3 -m doctest tools/capture_cli.py   # 抓包工具的 doctest

# 手动（要真 IDE 的 CLI）：把 CLI 自己发的报文抓进 fixtures/protocol.json
uv run python3 tools/capture_cli.py --name open-goto -- /tmp/a.txt:3
```

不想用 uv 也行：直接用系统 `ruff` / `python3` 跑同样的命令，只是版本可能不是 lock
里那份（`ruff check` 的配置仍读 `pyproject.toml`）。

另外有个**第二意见**（不进 `uv.lock`、也不当门禁 —— 还是预览版）：

```bash
uvx ty check                     # Astral 的 ty（0.0.84），0.14 s
```

它的规则集和 mypy 不同，能报类型之外的东西 —— 实测现在 2 条，都是 `tempfile.mktemp`
的弃用告警（`test_edit.py:45`、`tools/capture_cli.py:89`），mypy 不管这类。这 2 条
**先留着**：那两处 `mktemp` 是为了拿一个 socket 路径名（不是真建文件），换 `mkstemp`
得先 unlink，不是机械替换。门禁以 `uv run mypy` 为准。

只跑 `ruff check`，**没有采用 `ruff format`**：仓库故意用了魔尾逗号（`[cli,]`）
和等号对齐（`CLI_KIND_VIM  = 'vim'`）这类写法，格式化会把它们拆开/压平
（ruff 0.16.9 实测全量重排 507 行：`edit.py` 253 / `test_edit.py` 215 / `tools` 39，
纯格式、无语义变化）。要统一得先接受那次全量重排。

`test_edit.py` 里的 `FakeWindow` 会起一个真的 AF_UNIX server 假装成 IDE 窗口，
因此"发出去的报文""HTTP 500 时回退 CLI""窗口连上就断"这些都能确定性测到，
而 `EDIT_CLI` 永远指向假 CLI —— 万一代码偷偷走了 CLI，测试里会立刻看出来。

`fixtures/protocol.json` 是从真 CLI（code / trae-cn / buddycn 实测逐字节相同）
抓下来的报文快照，`ProtocolFixtureTest` 拿它对照 `open_request()`：字段集合与
取值必须一致，标了 `diff` 的字段是我们故意不同的（目前只有 `gotoLineMode`），
`direct:false` 那几条是现在交回 CLI 的。抓包靠 `tools/capture_cli.py`，要真 CLI，
所以不进测试，测试只读 fixtures。
