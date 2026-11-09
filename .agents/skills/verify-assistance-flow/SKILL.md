---
name: verify-assistance-flow
description: "验证独立即时协助的轮次、回复和可选产物提交。修改 finish_assistance、产物数量门禁或轮次重试时使用，检查一轮最多保存一个产物。"
---

# 验证即时协助产物提交

一个教学轮次最多保存一个产物。否则非法工具结果会绕过约定并进入会话。

## 执行

1. 按[验证入口](../../../docs/formal-verification/README.md)配置 TLC。
2. 阅读[覆盖记录](references/coverage.json)、[模型](assets/AssistanceFlow.tla)与[配置](assets/AssistanceFlow.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system assistance-flow --mutants --code-mutations`。
4. 用 `/statechart` 读取每次结果，并用 [view](assets/view.mjs)区分暂存、原子保存、失败和显式重试。

## 对齐代码

`Send` 对应 `assistance_turn`，`Start` 对应 worker 的 generating 转换。`ReceiveDraft` 表示存储边界收到候选结果，不是保存成功。零产物与一个产物都合法，两个产物是必须拒绝的外部输入。

`Commit` 是 `finish_assistance` 的单个事务。回复、产物和 run ready 不拆为可被其他命令观察的保存步骤。真实故障实验把单产物门禁从大于一改为大于二。

## 边界与维护

- 有界范围为一个会话、最多两次请求。第二次代表后续轮次或一次重试。候选产物数量为零、一或二。
- `AtMostOneArtifactPerTurn` 是唯一形式检查性质。原子性依赖已存在 SQLite 事务，不是本模型对数据库崩溃恢复的证明。
- 不证明旧 run 身份门禁、continue 建议动作、白板并发、HTML 安全或内容质量。该子系统不关联课程成绩。
- 同步基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`，覆盖记录另存工作区摘要。
- 源码变化时先用 `/maintain-formal-verification-skill` 复核。确认对应关系后才推进 sync_commit 和摘要。
- 保留真实反例，不弱化门禁或自动改产品代码。
