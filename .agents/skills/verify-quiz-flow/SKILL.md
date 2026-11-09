---
name: verify-quiz-flow
description: "验证练习与考核的逐题保存、下一题和显式提交状态机。修改 submit_quiz、答题 cursor、结果保存或完成事实时使用。"
---

# 验证题组提交

全部题目作答或明确跳过后才能提交结果。否则未完成的尝试会被计入完成记录。

## 执行

1. 按[验证入口](../../../docs/formal-verification/README.md)配置 TLC。
2. 按[覆盖记录](references/coverage.json)核对 `answer_quiz`、`next_question`、`submit_quiz` 和客户端状态，再读[模型](assets/QuizFlow.tla)及[配置](assets/QuizFlow.cfg)。
3. 运行 `uv run --frozen python scripts/verify_state_machines.py --system quiz-flow --mutants --code-mutations`。
4. 用 `/statechart` 读取每次结果，并用 [view](assets/view.mjs)展示末题反馈和已提交结果是不同状态。

## 对齐代码

`Answer` 对应独立保存答案的事务，cursor 不自动增加。`NextQuestion` 单独前进。`Submit` 同事务保存结果、完成事实和课程版本。作答不自动提交，开始或再练需要明确动作。

真实故障实验禁用 `len(attempt["answers"]) != len(quiz["questions"])` 门禁。未答完的显式提交必须被模型与真实数据库测试抓住。

## 边界与维护

- 有界范围为一个不可变题组、一个尝试和两题。跳过与正常答案对完成门禁等价，均算已回答。
- `SubmissionRequiresAllAnswers` 是唯一形式检查性质。模型前提为题组合法、答案按当前题保存、计分纯函数正确。
- 不证明计分数学、并发唯一索引、多尝试历史、版本与网络回执竞争。提交完成不代表掌握度。
- 同步基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`。覆盖记录另存脏工作区摘要。
- 用 `/maintain-formal-verification-skill` 复核漂移，只有确认模型对应新代码后才推进 sync_commit 和摘要。
- 反例先回放到真实命令。保留真实缺陷，不弱化性质或自动改产品代码。
