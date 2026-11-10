# CourseRecovery

TLC reached 112 states and 281 steps. The chart draws 10 states and 12 arrows.
The chart does not draw 218 steps that stay in one chart state.

## CommittedUnitsPreserved breaks
The shortest path has 4 steps:
0. 原任务生成 / 已保存0个单元
1. 开始未保存单元: 原任务生成 / 已保存0个单元
2. 保存完整单元: 原任务生成 / 已保存1个单元
3. 停止当前任务: 原任务已停止 / 已保存1个单元
4. 显式继续剩余内容: 接续生成 / 重试重置了已保存单元

## Rules that hold
NoDeadlock
