# 本仓库的任务入口。pyproject.toml 只是配置容器（不发包、运行期零依赖），
# 所以这里没有 build / publish 之类的配方，只有开发时反复跑的那几步。
#   just          列出配方
#   just check    提交前的门禁：lint + test
#
# 注：下面都用 `uv run`，跑的是 .venv 里的 python（mypy / ruff 在 dev 组里）。
# 跑产品本身用系统 python3：python3 edit.py --help

# 列出配方（just 不带参数时跑的就是它）
default:
    @just --list

sync:
    uv sync

lint:
    uv run ruff check . && uv run mypy

# 两摊测试：edit.py 文档里那些 >>> 例子（--self-test）+ unittest 那套（test_edit.py）
test:
    uv run python edit.py --self-test
    uv run python test_edit.py

# 依赖写在头部行：just check 会依次跑 lint 与 test
check: lint test
