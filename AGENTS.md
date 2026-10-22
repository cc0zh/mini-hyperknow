# mini-hyperknow

这个仓库是面向 Agent-first 开发的基础模板。`AGENTS.md` 提供任务入口，`docs/` 是仓库知识的正式来源；prompt、规则和架构约束随仓库版本化。

## 执行与完成

- 在用户已授权的范围内，自主完成本地编辑、检查及本次改动引起的问题修复，直到满足验收要求；用户要求实施时，交付经过验证的结果。
- 一般实现细节沿用仓库惯例，必要时说明假设并继续。只有缺失信息会改变目标、验收或授权范围时才请求确认；已有授权持续有效。
- 本地可逆操作无需逐步确认。发布、部署、外部写入和破坏性操作需要已有授权或单独确认；遵守运行环境的权限限制。
- 改动保持聚焦，并同步受影响文档。验证与风险匹配：文档改动检查内容、引用和文档骨架；代码改动运行相关测试及必需检查。通过后，仅在新改动、失败或未解决风险出现时扩大或重复验证。交付时说明结果、验证和未完成项。

## 按任务查阅

从当前任务涉及的文件和直接依赖开始，按下表读取相关文档。已有且仍适用的上下文可以复用；局部修正无需先通读全仓库。Skill 按具体工作流选用，并按需加载支持材料。

| 任务或决策 | 查阅入口 |
| --- | --- |
| 修改协作流程、提交约定或文档规则 | `docs/REPO_COLLAB_GUIDE.md` |
| 调整目录、模块边界或依赖方向 | `docs/ARCHITECTURE.md` |
| 新增或修改架构、产品设计与长期决策 | `docs/design-docs/index.md` |
| 调整 Agent-first 模板的设计原则 | `docs/design-docs/core-beliefs.md` |
| 编写或修改代码 | `docs/CODING_BEHAVIOR.md`、`docs/coding-standards/README.md` |
| 复杂或高风险任务 | `docs/PLANS_GUIDE.md`，先将 execution plan 落到 `docs/exec-plans/` |
| 长任务需要拆分过程或验收记录 | `docs/exec-runs/README.md`（普通任务直接维护计划） |
| 产品取舍；质量评估或治理 | 分别查阅 `docs/PRODUCT_SENSE.md`；`docs/QUALITY_SCORE.md` |
| 稳定性、观测性或上线准备 | `docs/RELIABILITY.md` |
| 认证、数据处理或外部集成 | `docs/SECURITY.md` |
| 依赖、SBOM 或制品 provenance | `docs/SUPPLY_CHAIN_SECURITY.md` |
| 构建、CI/CD 或交付流程 | `docs/CICD.md` |
| Windows 环境、命令入口或原生 Agent 执行 | `docs/WINDOWS.md` |
| 选用外部沙箱扩展 | `docs/SECURITY.md`（外部扩展不随新项目默认分发） |
| 讲解改动、调用路径或架构 | `docs/code-understanding/README.md` |
| 提 PR；维护发布记录；沉淀外部资料 | 分别查阅 `CONTRIBUTING.md`；`docs/releases/README.md`；`docs/references/README.md` |
| 完成代码或流程变更 | 按 `docs/HISTORY_GUIDE.md` 记录到 `docs/histories/` |

## 阶段完成后的学习沉淀

代码变更涉及新概念、可迁移知识、需要解释的原理或权衡、易踩陷阱、可复用模式中的至少两项时，按 `docs/learnings/WRITING_GUIDE.md` 写入 `docs/learnings/YYYY-MM/`。未命中时可在 history 中简述，无需单独成文。

计划归档时，先更新仓库内指向该计划的链接；如果计划中的决定已经成为长期约束，同步到对应设计文档。质量状态只有发生变化时才更新 `docs/QUALITY_SCORE.md`，并链接验收证据，避免重复维护过程记录。
