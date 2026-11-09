---
name: verify-course-flow
description: "验证澄清、调研、蓝图批准和逐单元展开的课程状态机。修改 finish_unit、蓝图确认、局部保存或课程 ready 规则时使用。"
---

# 验证造课与逐单元提交

只有全部单元保存完成，课程结构才能 ready。否则学习者会进入尚不完整的课程。

## 执行

1. 按[验证入口](../../../docs/formal-verification/README.md)配置 TLC。
2. 根据[覆盖记录](references/coverage.json)阅读源码，核对[模型](assets/CourseFlow.tla)和[配置](assets/CourseFlow.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system course-flow --mutants --code-mutations`。
4. 用 `/statechart` 读取每次 TLA+ 结果，并使用 [view](assets/view.mjs)查看用户流程与最短反例。

## 对齐代码

- `NoQuestions` 与 `NeedAnswers` 对应 `finish_clarification` 的两种已保存结果。
- `ResearchDone` 对应 `finish_research` 原子保存报告并进入 blueprint。`SaveBlueprint` 对应 `finish_blueprint`。
- `Approve` 与 `Adjust` 对应 `blueprint_command`。调整会补充调研，不能越过批准直接展开。
- `BeginUnit` 与 `FinishUnit` 分别对应同名存储事务。结束一个单元不是结束整门课程。

故障实验把真实 `finish_unit` 的 all 检查换为 any。两个单元中第一个提交后，模型和真实测试都必须抓住过早就绪。

## 边界与维护

- 有界范围为一个课程、两个单元、最多一次蓝图反馈。每个单元的结构与 claims 已经校验，作为模型前提。
- 只形式检查 `ReadyRequiresAllUnits`。完整课程图、claims 传播、版本竞争、重试重用和教学质量不在该性质内。停止后的重试由共享生命周期技能单独展示。
- 同步基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`。覆盖记录含当前脏工作区文件摘要。
- 源码变化时用 `/maintain-formal-verification-skill` 复核。确认对应关系后才推进 sync_commit 和摘要。
- 反例先用代码步骤重放。模型错误时修模型，真实缺陷时报告，不弱化性质或擅改产品代码。
