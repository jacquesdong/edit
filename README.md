# edit

把文件（可带 `:行号[:列]`）打开在**当前 IDE 窗口**里的小工具。

本仓库从 dotfiles（`~/config`）拆出来单独维护：`edit.py` 的历史是按文件重放过来的
（`config@61a4ff2` 的 `scripts/.scripts/edit.py`，含改名前 `bin/.bin/edit` 的 2020 年提交；
3 条纯改名的提交因为内容未变没有重放）。dotfiles 里那份仍在，**由使用者手动同步**。

## 用法

```
edit <文件...>               在当前 IDE 窗口打开文件
edit <文件:行号[:列]>         跳到指定位置（VS Code 系用 --goto，vim 系用 +行号）
edit --init fish | source    把 hook 和 remote-cli 目录导入当前 shell
eval "$(edit --init bash)"   同上（bash / sh / dash）

EDIT_CLI=buddycn edit <文件>  点名用哪个 CLI（多个 IDE 都装着时有用，优先级最高）
edit --list                  列出存活的 IDE 窗口（只读、不读 stdin，会问各窗口 workspace）
edit --usage                 打印完整用法（--help 是透传给 IDE CLI 的）

edit --init fish --interactive   列出窗口并挑一个，输出它的初始化片段
                                 （普通终端里没有 hook 时用这个）
```

`edit.py` 开头的 docstring 是完整的用法与原理说明，`edit --usage` 打的就是它。

## 两条执行路径

1. **直连窗口 socket**（有 `VSCODE_IPC_HOOK_CLI` 时）：往 socket POST 一个 JSON
   —— `{"type":"open","fileURIs":[…],"gotoLineMode":…}`，行号按 VS Code 的写法拼在
   URI 里（`file:///x.py:12:3`，冒号不转义）。协议是从 `remote-cli`（`out/server-cli.js`）
   抓包对出来的，字段与它逐字节一致；回复只认 HTTP 200。
   这条路径不需要 PATH 里有 `remote-cli`，也不起 node。
2. **remote-cli**：没有 socket（桌面版），或参数翻不了（`--wait` / `-g` / 未知选项 /
   无参数）时，照旧找 `code` / `buddycn` / `trae-cn` 去开。直连失败也会回退到这里，
   并在 stderr 留一行提示。

`--list` / `--init --interactive` 会用同一个 socket 直连问每个候选窗口一次只读
`{"type":"status"}`，从回复的 `Process Argv: --remote <authority> <workspace>` 取得
窗口的 workspace，这样挑窗口时能认出哪个是哪个（失败就显示 `?`）。

## 开发

```bash
python3 edit.py --self-test      # 纯函数 doctest（不开窗口、毫秒级）
python3 test_edit.py -v          # 回归：假窗口 + 假 CLI，不碰真实 IDE
ruff check .                     # 用仓库里的 ruff.toml
```

`test_edit.py` 里的 `FakeWindow` 会起一个真的 AF_UNIX server 假装成 IDE 窗口，
因此"发出去的报文""HTTP 500 时回退 CLI""窗口连上就断"这些都能确定性测到，
而 `EDIT_CLI` 永远指向假 CLI —— 万一代码偷偷走了 CLI，测试里会立刻看出来。
