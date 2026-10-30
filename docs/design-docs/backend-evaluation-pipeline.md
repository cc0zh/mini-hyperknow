# 面向学习任务的教学评测

状态：2026-10-29从零撤换原通用评测框架。现行实现是 `src/hyperknow_eval/`，唯一命令入口为 `scripts/run_eval.py`；[使用说明](../../evals/README.md)承载命令，[执行计划](../exec-plans/completed/20261029-learning-evaluation-rewrite.md)承载实际验证。旧 ATIF 出口、Adapter、状态 DSL、资产发布与 review 平台不再保留；旧结果不自动扫描或迁移。

## 1. 为什么重新定义评测单位

Hyperknow 的目标不是完成八个 API，而是帮助一个具体学习者解决疑惑。原14项开发任务虽跨业务，学科集中在链式法则；结构、保存与业务成功不能证明知识正确。历史上出现自动教学评分通过却被数学反例否决，不能靠再加一条格式规则宣称修复了评分可靠性。

评测单位现在是：**学习者目标＋已有知识／误区＋公开学习任务＋有限交互＋可核验参考＋逐项判据**。固定任务经过真实产品执行，再冻结教学证据，最后独立判断。不把平台通用性、统一总分或自动接受候选作为目标。

参考 [DeepTutor](../references/deeptutor-learning-evaluation.md) 的知识缺口、第一人称多轮交互、参考答案隔离和人类核查思路，但不复制其产品。其固定源码 `deeptutor/services/rag/eval/` 是检索评测，不是已经获取的 TutorBench 实现。Hyperknow 不因此增加 RAG、长期学习者记忆、文件／命令权限、调研能力或 Skill 白名单。

## 2. 四个不能合并的问题

| 层次 | 要回答什么 | 证据／结论 |
| --- | --- | --- |
| 执行 | 是否完成本任务的真实业务目标 | 实际 HTTP 状态、SQLite 保存事实；completed／failed／blocked／interrupted／not_run |
| 工程 | 归属、状态、持久化、写入与已观测预算是否符合契约 | 确定性检查；met／not_met／insufficient |
| 教学 | 内容正确吗、讲法适合吗、是否回应新困惑、来源是否支持主张 | correctness／pedagogy／adaptation／grounding 各自逐项判定与精确证据引文 |
| 学习效果 | 真人是否掌握、能迁移、能保留 | 需独立作答、前后测与真实学习者研究；当前**未验证** |

没有“格式通过＝教学通过”。模拟学生是交互发生器，不是自己打分的学习收益测量仪；其自称懂了不能成为有效性证明。不适用维度不补造判据；缺输出、证据或判断为 insufficient，不从分母删除。

## 3. 简单的产品专属结构

```text
evals/suite.json + cases/*.json     固定开发任务，不执行资产发布状态机
evals/calibration.json             明确标注的 authored controls
schema.py / cases.py               严格 schema v3、任务加载与公开投影
storage.py                         原子持久化、单写锁、内容与 trial 摘要
runner.py / runtime.py             独立真实后端、一次命令提交与只读采证
scenarios.py                       八类显式 Python 业务场景
judging.py                         独立评分与无答案学生模拟
calibration.py                     控制运行与逐项预期对照
reporting.py / cli.py               分维汇总、严格配对、离线 HTML 与唯一 CLI
```

产品运行时不导入评测包。复用真实产品 API 与必要的只读存储，不再用通用 Adapter 或另一套 JSON DSL 解释业务状态机。课时、课堂问答、练习／考核等下游目标先真实完成造课与确认；不写库伪造 fixture。

任务采用严格、冻结、拒绝未知字段的 Pydantic 契约；JSON 拒绝重复键及非标准数值。公开投影只有 `id/workflow/task/budget`；学习者私有设定、参考正确理解和 rubric 不进入产品请求。当前17任务、9学科、8 workflow 均为助手编写并复核的开发集，独立人工审核待完成，不能称为留出 benchmark。

## 4. 真实执行与恢复边界

每个 trial 默认拥有自己的 Uvicorn 进程、空 SQLite 和新输出目录。仅允许 loopback；默认用户库、非空业务库、数据库文件身份变化或 health.storage_id 不一致均拒绝写入。外接后端必须显式绑定 URL＋目录；存储指纹只防误连，不是认证或恶意宿主隔离。

受控后端记录运行时产品源文件及依赖锁摘要，不用评测 CLI 的 Git HEAD 冒充服务身份；源码运行中改变就标 unknown。外接后端没有可验证源码身份就保留 unknown。health 的 configured 不代表模型连通已验证。

业务写命令先落盘固定 command_id、请求和 in_flight，再只发送一次。不跟随重定向，分块读取受绝对 deadline 约束。回执未知、超时或中断不自动重发，也不产生“恢复”命令来重放未知提交；下一实验使用新目录和新 trial。停止只作用于自己持有的进程树，不按端口或名字杀未知进程。

budget.max_actions 限业务写命令；max_observed_calls 依据采证后已持久调用决定能否继续，不承诺撤销已派发请求或严格远端费用上限。远端请求是否停止计费是独立 billing observation，unknown 不会伪装成零，也不污染其他已证实工程事实。

practice／exam 只验证真实题组生成与教学内容，不偷看答案伪造学生作答或分数。即时协助仍为无课程独立会话，可信 Skill 白名单为空、不装配搜索／文件／命令权限。

## 5. 冻结证据与隔离评判

trial 保存完整任务／配置、业务命令、业务 run、终态输出、真实逐轮对话、实际读到的来源和调用清单。证据项有稳定 ID、SHA-256 与 trial 身份；整体摘要绑定任务、证据和 transcript。原始工件只追加评分尝试，不改写旧失败；每次保存原子替换且要求单写锁，不覆盖已有实验目录。

评分不是把整份执行审计灌入 prompt：health、trace、model_calls 等仍完整冻结，但只向 judge 投影完整教学内容、相应输入和实际读到的来源。投影保留原 evidence ID／projection_fields，不删减教学正文、不假造来源。引用必须精确存在于绑定证据，JSON 严格覆盖全部 criterion，不能用不存在的引文支持 met。

judge 无工具；原任务／回答／来源里的指令均为待判断数据，不能改标准。每项返回 met、not_met 或 insufficient，并给 reason、evidence_id、quote。角色模型必须显式配置；记录计划配置、每次实际配置、定义哈希、证据哈希、完整请求、原始响应、finish_reason 和 usage。

请求先持久化 in_flight，再只发一次；SDK 自动重试关闭。拒答、超时、格式错误、输出预算不足、完整证据超上下文均不能通过，不做 JSON 修复、文本模板补答、备用模型或隐式重试。重评必须显式追加 attempt；最新尝试生效，错误也不能回退到有利旧判断。计划配置不改，实际变更显式提示并进入比较键。

评分 CLI 默认输出16384／上下文96000；学生1024／32000。reasoning 可能消耗 completion 上限，本地 token 估计也不等于实际 token；任何预算调整都不是教学内容改进。完整证据放不下时拒绝请求，不用截断换取成功。

学生模拟仅看 learner、公开 task 和真实 transcript，不见 reference／rubric，无工具、有限轮次；失败不 fallback。固定追问与模拟模式分别披露，模拟学生不兼任判卷人。

## 6. 控制、报告和版本比较

六类作者控制：正确且回应、事实错误、正确但不教学、提示注入、无输出、虚构来源。固定期望逐项对照，记录误受、误拒与错误；无输出不收费。通过仅代表当前配置在这些 authored controls 上匹配，**不等于独立人工校准、人类对齐或通用评分可信**。每份报告保留 calibration_status=unreviewed，不能因控制通过自动放行产品。

报告不平均成万能总分：execution、engineering、四类 teaching、任务／领域／业务覆盖、各角色用量分别呈现。业务只取每 run 最后 model_calls 快照，不能与 model_requests 中的业务引用双算；缺用量、价格或远端取消证据保留 unknown。

批量先保存完整任务×repetition 矩阵，未跑单元作为 not_run 留在分母。compare 必须矩阵、任务哈希、交互／学生定义及最新有效评分定义／配置一致；不能挑成功交集，不能把同 trial 重评称作两个产品版本。同源不同 trial 可作重复性／负控并警告；源码身份未知不伪造，教学模型差异披露，不自动接受候选。

HTML 只从显式 trial.json／batch.json 新建，完整转义，无外部脚本和执行操作，不递归扫描 data 或历史目录。包含私有判据／用户内容，不是自动脱敏件。新入口不支持旧 schema、发布、迁移、自动回流、ATIF 或全局 review；历史工件保留原字节，保护目录不得访问。安全约束见[安全默认](../SECURITY.md)。

## 7. 验证边界

纯函数、真实磁盘／SQLite、本地实际 HTTP 验证机制，真实模型链验证内容；不使用 Mock、Fake、patch 或录制模型响应冒充真实验收。全量本地测试、实际模型调用、独立人工校准、浏览器产物呈现和真人学习效果分别报告。

本次真实覆盖与失败见[验收计划](../exec-plans/completed/20261029-learning-evaluation-rewrite.md)，不把17项开发资产写成已全部真实通过，不把新框架上线写成产品教学已改善。下一步应独立审核参考与判据、用未见学科／真实错误答卷验证 judge，再固定预算做双版本配对；不能扩跑求一个更好看的通过率。
