# ClassroomFlow

TLC reached 21 states and 50 steps. The chart draws 9 states and 17 arrows.
The chart does not draw 10 steps that stay in one chart state.

## CompletionRequiresSummary breaks
The shortest path has 4 steps:
0. 进入课堂，只读已有状态
1. 明确准备本课: 正在准备讲义
2. 开始生成: 正在准备讲义
3. 保存讲义，初始暂停: 暂停，可回看
4. 明确完成本课: 未展示总结就记录完成

## Rules that hold
NoDeadlock
