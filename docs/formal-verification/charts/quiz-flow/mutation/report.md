# QuizFlow

TLC reached 15 states and 23 steps. The chart draws 10 states and 13 arrows.
The chart does not draw 4 steps that stay in one chart state.

## SubmissionRequiresAllAnswers breaks
The shortest path has 5 steps:
0. 进入练习或考核，只读
1. 明确准备题组: 正在准备题组
2. 开始出题: 正在准备题组
3. 保存不可变题组: 题组已保存，等待开始
4. 明确开始作答: 回答第一题
5. 明确看结果，事务计分并保存: 未答完就保存了结果

## Rules that hold
NoDeadlock
