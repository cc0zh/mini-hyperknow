---
name: verify-classroom-flow
description: "验证白板课堂讲义、播放、提问和手动完成状态机。修改 complete_lesson、确认位置、课堂暂停或恢复行为时使用。"
---

# 验证课堂的显式完成

只有确认最后总结后才能手动完成课时。提前离开不能生成完成事实。

## 执行

1. 按[验证入口](../../../docs/formal-verification/README.md)配置 TLC。
2. 按[覆盖记录](references/coverage.json)检查后端事务与客户端暂停语义，再读[模型](assets/ClassroomFlow.tla)和[配置](assets/ClassroomFlow.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system classroom-flow --mutants --code-mutations`。
4. 用 `/statechart` 读取每次结果。使用 [view](assets/view.mjs)区分已确认位置、暂停、提问和显式完成。

## 对齐代码

`Prepare`、`SaveScript`、`Advance`、`Ask`、`Complete` 对应 `prepare_lesson`、`finish_lesson`、`save_progress`、`ask_question`、`complete_lesson` 的独立事务。`Answer` 对应 `finish_lesson` 的 question 分支。`Play`、`Pause` 与 `Refresh` 抽象客户端播放意图。刷新后本地时钟暂停，不生成讲义。

`Complete` 同时代表事务中的完成事实、课程版本和暂停状态，不拆成可被其他命令观察的中间状态。真实故障实验禁用最后 summary 门禁，检查提前完成必须断言失败。

## 边界与维护

- 有界范围为一个脚本，三步分别代表讲解、检查点和最后总结。cursor 为 -1 到 2，每次只确认一步。
- `CompletionRequiresSummary` 是唯一形式检查性质。假设脚本已经通过结构校验，且用户界面等到后端确认才展示。
- 不证明浏览器定时器并发、重放命令所有权、回看锚点合法性、多问题竞争或学习掌握度。完成后的再次问答不在本模型中。
- 同步基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`。覆盖记录包含本次工作区摘要。
- 源码变化时先运行 `/maintain-formal-verification-skill`。复核后才推进 sync_commit 和摘要。
- 真实缺陷保留为反例，不弱化性质，不自动修改产品代码。
