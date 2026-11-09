# AssistanceFlow

TLC reached 41 states and 88 steps. The chart draws 9 states and 17 arrows.
The chart does not draw 35 steps that stay in one chart state.

## AtMostOneArtifactPerTurn breaks
The shortest path has 4 steps:
0. 独立会话，可直接提问
1. 发送问题或明确继续: 教学轮次排队
2. 开始教学: 正在教学，产物尚未提交
3. 得到尚未保存的候选结果: 正在教学，产物尚未提交
4. 校验并原子保存回复和可选产物: 一轮错误地保存多个产物

## Rules that hold
NoDeadlock
