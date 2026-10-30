# 学习任务评测

固定学习任务 → 真实产品执行 → 冻结证据 → 分维度评判 → 可复核报告。代码在 `src/hyperknow_eval/`，唯一入口是 `scripts/run_eval.py`。工程完成、知识正确、教学适配和多轮回应分别报告；没有一个“万能通过率”。设计与边界见[教学评测设计](../docs/design-docs/backend-evaluation-pipeline.md)。

## 先做不收费的检查

在仓库根目录执行：

```powershell
uv run --frozen python scripts/run_eval.py validate
uv run --frozen python scripts/run_eval.py validate --case evals/cases/chain-rule-transfer.json
uv run --frozen python scripts/run_eval.py --help
```

当前 `suite.json` 包含17项、9个学科、8种业务。全部是助手编写并复核的**开发任务**，状态为 `author_reviewed`，不是独立人工审核、留出测试集或已校准的 benchmark。`cases/` 存任务，`calibration.json` 存明确标注为作者编写内容的评分控制，不混作真实产品答卷。

每项任务包含学习者背景、目标、误区、公开问题、私有参考与判据、执行预算。业务只收到 `id/workflow/task/budget`；学生模型只能额外看到学习者设定与真实对话，不能看到正确理解或评分标准。资料引用用于核验事实，不要求每个回答背出所有参考内容。

## 运行真实产品（收费）

没有 `--execute` 不会执行业务或模型。每个 trial 默认启动真实 Uvicorn 和独立空 SQLite，结束后关闭自己拥有的进程。不会复用作者默认库，也不会读取旧课来冒充新生成。输出目录必须新建，不能覆盖既有实验。

```powershell
# 只执行与采证，之后再决定是否付费评分
uv run --frozen python scripts/run_eval.py run --case evals/cases/chain-rule-transfer.json --output data/evals/my-chain --execute

# 对已冻结答卷独立评分；不重新生成教学内容
uv run --frozen python scripts/run_eval.py judge --input data/evals/my-chain --judge-model YOUR_JUDGE_MODEL --judge-max-output-tokens 16384 --execute

# 使用有界、无工具、看不到答案的模拟学生，并独立评分
uv run --frozen python scripts/run_eval.py run --case evals/cases/recursive-return-simulated.json --output data/evals/my-recursion --student-model YOUR_STUDENT_MODEL --judge-model YOUR_JUDGE_MODEL --execute
```

被测模型由产品自身配置。评分模型与学生模型必须分别用 `--judge-model`／`--student-model` 或 `HK_EVAL_JUDGE_MODEL`／`HK_EVAL_STUDENT_MODEL` 指定，**不回退到教学模型**。凭据可使用已有后端 `OPENAI_API_KEY`，也可用 `HK_EVAL_JUDGE_API_KEY`／`HK_EVAL_STUDENT_API_KEY` 独立配置；base URL、timeout、输出和上下文预算各有同角色参数。不要把密钥放入命令、Case、报告或聊天。

CLI 默认评分输出上限16384、上下文预算96000；学生输出上限1024、上下文预算32000，请求 timeout 120秒。输出上限可能同时包含供应商 reasoning 与最终答案，不保证一定返回有效 JSON。上下文预算是本地保守估计门禁，不是精确 token 数或供应商容量声明。完整教学证据放不下就拒绝评分，不静默截断；改变预算须显式新增评分 attempt，保留旧失败与用量。

八类业务为 `assistance/course/research/lesson/question/practice/exam/artifact`。即时协助保持无课程、无搜索、空可信 Skill 白名单；不会因评测而扩权。下游课堂／题组任务通过真实造课和确认准备课程。practice／exam 当前评测生成题组及内容，**不读取正确答案伪造学生作答、分数或学习增益**。

批量执行可使用 `--suite evals/suite.json --repetitions 2`；先保存完整矩阵，再逐个隔离运行。未运行项、失败、未判项都留在分母；不能只报告成功交集。`--base-url` 与 `--data-dir` 必须成对且只用于单个新 trial，后端须为 loopback、独立空库，通过 health 存储指纹和只读 SQLite 文件身份核对。外接源码身份未知就报告 unknown，不冒用 CLI 的 Git HEAD。

## 先验证评分器，再解释教学结论

```powershell
uv run --frozen python scripts/run_eval.py calibrate --output data/evals/my-controls --judge-model YOUR_JUDGE_MODEL --judge-max-output-tokens 16384 --execute
```

六类控制分别为正确且回应、事实错误、正确但不教学、证据内提示注入、无输出和虚构来源。逐项报告预期与观测、误受、误拒和执行错误；无输出控制不调用模型。控制通过只证明此模型配置对这些**作者控制**匹配，不能改写为独立人工校准、人类对齐或通用学科判断可靠。

评分只发一次无工具请求；保存完整请求、原始响应、finish_reason 和实际 usage。未知响应、超限、非法／重复 JSON 字段、非精确证据引文或拒答均不能默认通过；不做 JSON 修复、隐式重试或模型 fallback。重评追加新 attempt，最新一次生效，即使最新一次是错误也不退回有利旧判断。

## 只读报告与比较（不收费）

```powershell
uv run --frozen python scripts/run_eval.py report --input data/evals/my-chain --html data/evals/my-chain/review.html
uv run --frozen python scripts/run_eval.py compare --baseline data/evals/baseline --candidate data/evals/candidate
```

`report` 默认只输出结构化汇总，显式 `--html` 才新建离线 HTML，拒绝覆盖。`run` 自动新建 `report.html`，`judge` 为每次尝试新建独立报告；单项原始证据为 `trial.json`，批量入口为 `batch.json`。不再生成全局自动扫描的 review/catalog/index 平台。HTML 完整转义，不执行模型 HTML，不连服务或远程脚本。报告仍可能包含用户内容和私有判据，分享前须人工审查。

报告分开显示 execution、engineering、四个 teaching dimensions、coverage、评分配置／校准状态和各角色用量。业务 usage 只取每个 run 最后的调用快照，不与请求引用双计；未知用量不是零，金额和远端在途取消／费用终止没有证据则为 unknown。

compare 要求完整矩阵，以及任务、repetition、交互方式、学生定义、评分定义与实际评分配置一致。不同 trial 的同源执行可作重复性／负控并显著警告，不称版本改进；同一 trial 的重评不能冒称两个产品版本。失败／不足仍显示，同源、模型差异和未知身份都披露，不自动接受候选。

`run/judge` 遇教学／工程判据失败退出1，执行未完成或评分不足退出2；离线 report 的0仅说明报告生成，不表示内容通过。`calibrate` 不匹配退出1；非法输入或不完整比较退出2。细节以各子命令 `--help` 为准。

## 工件与历史边界

原始工件只写忽略的 `data/`、允许的 `eval_result/` 或仓库外新目录，不把含会话的文件提交 Git。`eval_result/2026-10-29/` 是明确保护目录：新框架拒绝访问，不能扫描、转换或改写。旧 schema 不自动迁移，旧 HTML 可自行作为历史文档查看；没有旧命令兼容层。

真实验证范围、模型、用量、预算失败和未验事项以[重写验收计划](../docs/exec-plans/completed/20261029-learning-evaluation-rewrite.md)为准。自动判据匹配、模拟学生说“懂了”、有保存产物，都不证明真人学习收益。
