---
name: verify-research-flow
description: "验证网页调研的搜索、阅读、报告与终止状态。修改 research_step、调研轮次或工具预算时使用，检查每轮最多十个已保存工具步骤。"
---

# 验证网页调研预算

每轮调研最多保存十个工具步骤，失败步骤也占预算。否则重试失败搜索会绕过预算。

## 执行

1. 按[验证入口](../../../docs/formal-verification/README.md)配置 TLC。
2. 根据[覆盖记录](references/coverage.json)核对 `research_step` 与[模型](assets/ResearchFlow.tla)、[配置](assets/ResearchFlow.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system research-flow --mutants --code-mutations`。
4. 使用 `/statechart` 读取每次检查结果，使用 [view](assets/view.mjs)查看预算反例和搜索阅读流程。

## 对齐代码

`Search`、`SearchFails` 和 `ReadPage` 都表示一次 `research_step` 事务。`Finish` 表示合法报告经过 `finish_research` 事务保存。搜索候选不等于已保存原文，二者分开记录。

真实故障实验把 `len(round_steps) >= 10` 改为 `> 10`。第十一步必须被模型和真实数据库测试拒绝。

## 边界与维护

- 有界范围为一个 run、一个 research_round，正常最多十步，故障变体最多十一步。搜索、读取成功与失败按有限类别抽象。
- 只形式检查 `ToolBudgetRespected`。不证明引用的逐字校验、语义蕴含、来源质量、网络安全或工具调用与持久化间的并发预算。报告内容合法性作为前提。
- 当前模型不声称真实搜索已评测，不调用搜索服务或收费模型。
- 同步基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`，另存工作区摘要。
- 用 `/maintain-formal-verification-skill` 复核源码漂移。确认模型和新代码对应后才推进 sync_commit 和摘要。
- 保留真实反例，不弱化预算，也不自动改产品代码。
