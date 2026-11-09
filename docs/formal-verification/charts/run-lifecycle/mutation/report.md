# RunLifecycle

TLC reached 49 states and 198 steps. The chart draws 8 states and 17 arrows.
The chart does not draw 138 steps that stay in one chart state.

## NoConflictingReplay breaks
The shortest path has 2 steps:
0. 尚未提交
1. 提交命令: 任务排队
2. 重发同标识的不同内容: 错误地接受了同标识的不同命令

## Rules that hold
NoDeadlock
