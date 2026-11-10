---
name: verify-run-lifecycle
description: "验证 Hyperknow 共享任务状态和命令回执。修改 command、重放、取消、重试或重启流转时使用，检查同一命令标识不能接受不同内容。"
---

# 验证共享任务与命令回执

同一个命令标识不能接受不同内容。否则重发命令可能读到另一个操作的结果。

## 执行

1. 从仓库根目录执行命令。先按[验证入口](../../../docs/formal-verification/README.md)配置固定版本 TLC。
2. 阅读[覆盖记录](references/coverage.json)中的源码和符号，再检查[模型](assets/RunLifecycle.tla)与[配置](assets/RunLifecycle.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system run-lifecycle --mutants --code-mutations`。
4. 用 `/statechart` 读取这次 TLA+ 检查结果。使用本技能的模型、配置和 [view](assets/view.mjs)。通过时查看状态图，失败时逐步核对最短反例与真实代码。

## 对齐代码

`Create`、`ReplaySame`、`ReplayDifferent` 对应 `Database.command` 的同一 SQLite 事务。receipt 表示固定命令标识的 payload 指纹，不表示普通业务版本。其他动作展示 `transition`、`retry_run`、`interrupt_inflight` 和 worker 生命周期。

新增`lesson_basis`和`teacher_turn`复用已有Start与Finish。其创建仍经`Database.command`，完成处理各自包在事务内，不写command_receipts。teacher内部状态更新对唯一命令回执性质是不改变投影状态的步骤，不由本模型证明教学回合协议或worker活性。

真实故障实验仅在隔离副本中禁用指纹冲突守卫。基线应通过，故障副本应产生测试断言失败，恢复后应再次通过。不能把导入失败或工具错误当作抓到回归。

## 边界与维护

- 有界范围为一个原命令、两种 payload 指纹和一次新任务重试。重试代表新 run，不是重置父 run。
- `NoConflictingReplay` 是本技能唯一形式检查性质。worker 槽位、晚到结果、事务崩溃恢复和多客户端公平性不在该性质内。
- 同步基准为 `e42d4cfe5eb79bec9e03ee18794328a6fd295038`。该提交之外已有工作区改动，覆盖记录另存本次核对文件的 SHA256。
- 源码摘要变化时先用 `/maintain-formal-verification-skill` 复核。只有确认模型仍描述新代码，才推进 sync_commit 与摘要。
- 当前实现违反性质时保留反例，不弱化性质，不自动修改产品代码。
