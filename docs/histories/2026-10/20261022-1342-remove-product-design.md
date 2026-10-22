# 撤销产品设计改动并建立初始提交

## 用户诉求

撤销 design 相关的改动后提交一个 commit。

## 改动与原因

- 删除 Hyperknow 产品设计任务的三份执行计划、六份研究与方案材料，以及原任务的 history，共十份文档。
- 保留既有 Python Agent、工具脚本、测试，以及通用设计目录中的 `index.md`、`core-beliefs.md`；不撤销模板原有的文档治理改动。
- 检查时仓库尚无任何提交，全部项目文件均未跟踪，无法使用 Git 恢复历史版本；按任务材料与引用范围清理后，将保留的项目状态建立为一个初始提交。
- 本次只操作本地仓库，不推送、不发布。

## 关键路径

- `docs/exec-plans/active/` 与 `docs/exec-plans/completed/`：移除产品设计任务计划，保留模板维护记录。
- `docs/exec-runs/`：移除该产品设计任务的研究、提案和历史草案，保留通用说明与模板。
- `docs/histories/2026-10/`：用本记录替代已撤销任务的交付记录。

## 验证

- `npm.cmd run ci` 通过：文档链接与锚点、仓库卫生、Action 固定版本、脚本语法检查，以及 21 项 Node.js 测试和 10 项 Python 测试全部通过。
- 已删除任务的文件名、任务标识和研究材料引用搜索无残留。
- `src/`、`tests/`、`scripts/` 和 `docs/design-docs/` 中非缓存文件的 SHA-256 校验一致，确认代码、工具、测试与通用设计规范未改动。
- 已知限制：没有历史 Git 基线；撤销依据为工作区内可明确归属的产品设计任务文件。
- 原有 `src/agent_core/types.py` 文件末尾有一个额外空行，默认 `git diff --cached --check` 会提示；为保持代码原样不修整该文件，提交前单次使用 `core.whitespace=-blank-at-eof` 检查其他空白问题，不修改仓库 Git 配置。
