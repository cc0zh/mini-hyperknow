# 从零重写面向学习任务的评测

状态：已完成并归档。实现、真实实验、文档、76项专项及最终全仓门禁（392项Python、22项Node）通过。未完成的独立人工校准与全量真实覆盖转入技术债，不因归档冒称通过。

## 目标、范围与风险

- 用户诉求：旧评测严重偏离设计初衷；以新接手者视角完整重写，可参考 DeepTutor 的目的与实现，不照抄。
- 目标：围绕学习目标、学习者已有知识与误区，真实执行产品；分别回答业务是否完成、知识是否正确、教学是否适配、多轮是否回应新困惑。不得用保存／格式成功替代教学质量，不宣称模拟学生带来真人学习增益。
- 包含：撤换 `eval_core`、旧 `hyperknow/eval_*` 与旧开发题集；一个 `hyperknow_eval` 包和 `scripts/run_eval.py` 入口；显式 Python 业务场景、跨领域任务、可选有界学生模拟器、独立证据评分、评分校准、只读报告与严格配对比较。
- 不包含：产品提示优化、产品长期学习者记忆、RAG／工具扩权、任意 Agent 通用平台、任务自动发布平台、浏览器视觉验收、真人教学实验。旧结果保留原字节，不自动扫描或转换。
- 授权：用户已授权本地完整重写及必要验证。新增模型调用须显式 `--execute`；不部署、不外部写入。不得查看 `.env` 值或用户现有 `eval_result/2026-10-29/` 内容。
- 风险：真实业务费用／长耗时、提交回执未知、自动评分假阳性、模拟学生泄题、历史兼容包袱。缓解：独立空数据实例、写前落盘命令身份、无隐式重发、冻结证据、原始请求响应及用量、显式校准状态、公共／私有材料分离；历史结果不迁移。
- 关联：[产品范围](../../design-docs/index.md)、[即时协助](../../design-docs/instant-assistance.md)、[真实验证](../../design-docs/real-validation.md)。现行评测设计随实现重写到 [backend-evaluation-pipeline.md](../../design-docs/backend-evaluation-pipeline.md)。

## 新契约与验收标准

1. **任务**：schema v3，每项包含领域、真实业务 workflow、学习者背景／目标／误区、公开开场与有限追问、私有参考事实与来源、逐项判据、预算。参考与判据不进入被测请求，学生模拟器也看不到正确理解。开发集明确为助手编写／待独立人工校准，不冒充留出集。
2. **执行**：显式业务函数使用真实 HTTP，不再解释 JSON 状态 DSL 或要求七方法 Adapter。支持 assistance、course、research、lesson、question、practice、exam、artifact；下游课程任务自行通过真实造课建立材料，不写假 fixture。只允许独立空库，HTTP health 与只读 SQLite 路径身份一致后才能写。
3. **持久证据**：每次命令先记录请求及 command_id，再发送一次。未知提交不自动重发。结果含业务 run、保存内容、逐轮对话、来源、内容摘要和模型调用记录。报告只读；重评新增 attempt，不替换原判定。
4. **教学判断**：确定性工程检查与模型判据分离。判据按 correctness／pedagogy／adaptation／grounding 分组，结果为 met／not_met／insufficient，必须引用真实证据及精确引文。错误／缺证据／格式非法／预算超限不得默认通过。模型身份、提示版本、私有标准和证据摘要绑定评分。
5. **学生模拟**：可选、无工具、有轮数与请求预算、只看不含答案的学习者设定和真实对话；不以学生自称“懂了”或自评分判定教学有效。固定追问与自适应模拟分别披露。
6. **校准与比较**：正例、事实错误、忽略误区、虚构引用、证据内注入等控制样本实际调用同一评分器；记录逐项期望与混淆，不把控制样本通过写成人类对齐已完成。比较仅对任务哈希、交互方式、评分定义／配置一致的单元配对，缺失、失败及未判定均进入报告。
7. **验证**：纯函数／真实磁盘／实际本地 HTTP 测试，不使用 Mock／Fake 模型。跑完整 Python 测试及仓库检查；配置可用时执行小规模真实教学链及评分控制校准，明确真实覆盖边界和全部未验业务。

## 进度与决定

- [x] 审计产品、旧实现与一手参考；确认产品运行时不反向依赖旧评测。
- [x] 固定新契约与替换范围。
- [x] 实现任务、证据存储、真实场景、学生模拟、评分、报告和 CLI；删除旧执行实现及旧题集。
- [x] 取得工程检查及小规模真实模型证据；修复SDK重定向、外接参数和超限停发问题。
- [x] 同步长期设计、导航、使用说明、质量事实、history与learning；旧计划标记退役，先改入链再归档。
- [x] 运行收尾全仓门禁并登记结果。
- 2026-10-29：采用产品专属的简单场景函数，而非提前设计跨产品协议；不保留旧执行／迁移／发布命令，避免维护两套框架。旧 JSON／HTML 作为独立历史工件保存，新入口不会重写它们。
- 2026-10-29：参考 DeepTutor 论文 `2604.26962v3` 的知识缺口、多轮交互、参考答案隔离与独立校准；核实官方仓库固定提交 `fa26e7e999ccc04e042dcc842b890da5d2d317f4` 的 `deeptutor/services/rag/eval/` 实际为检索评测，不能称作 TutorBench 实现。
- 2026-10-29：独立保存业务工程检查与计费观察。远端费用终止unknown不推翻已证实的工程事实，也不当成零费用。`max_actions`限业务写命令，`max_observed_calls`是在只读采证后决定是否继续，不是供应商派发硬封顶。
- 2026-10-29：只给judge完整教学投影及实际来源，不将全部管理快照混入输入，也不截断正文求通过。评分要求回答公开问题，不要求答完未被提问的整份reference。
- 2026-10-29：SDK锁定版本默认跟随重定向，`max_retries=0`仍防不住307／308重发POST。显式禁重定向及环境代理，真实loopback拒绝响应逐项验证；保存HTTP状态／正文，未知响应不默认重试。
- 2026-10-29：输出usage超过请求上限时立即停止当前runner／batch／calibration后续收费请求，剩余not_run保留。正常用满输出预算但未作答属于评分不足，不与已知预算违约混淆。
- 2026-10-29：受控进程身份来自实际产品源码／锁文件摘要，blocked进程也保留身份；不是借用CLI Git HEAD。Windows仅终止自己拥有的进程树。最后只读采证归Runtime退出收尾，不重复计费引用。
- 2026-10-29：比较拒绝不完整矩阵、不同生效judge／student定义与同trial自身重评；同源不同trial只可作重复性／负控并警告，绝不自动接受候选。最新attempt错误也不回退到有利旧结果。
- 2026-10-29：文档检查及模板遍历不进入data／eval_result，私有运行工件只写代码路径而不建立Markdown链接；防止工程门禁触碰保护目录。移除旧题集后同步真实模板打包测试，不保留失效入口。
- 2026-10-29：收尾发现输出已拒绝保护目录，但离线读取尚未统一拒绝。存储层增加artifact_path，JSON、批量输入、报告、锁与后端路径均在内容I/O前拦截；词法命中的路径在resolve前拒绝，解析后的别名也核对。新增两项拒绝测试，不打开、扫描或改写旧文件，不追加模型调用。

## 验收与交接

### 实现与确定性验证

- 唯一入口：`uv run --frozen python scripts/run_eval.py`，仅validate／run／judge／calibrate／report／compare；当前契约schema-v3。删除eval_core、产品eval_*、旧测试及旧两套题集，不提供旧执行兼容、迁移、发布或ATIF平台。
- 任务：`evals/suite.json`，17项、9学科、8 workflow，全部author_reviewed。覆盖误区与公开追问，不是独立人工审核或held-out benchmark；practice／exam只生成真实题组，不伪造作答成绩。
- 最新专项：`uv run --frozen python -m unittest discover -s tests -p test_learning_eval_*.py`，76项、10.898s、OK，包含真实磁盘／SQLite／HTTP、受控后端生命周期与保护历史的I/O前拒绝，无模型费用。所有301／302／303／307／308／429／500／503拒绝均只一次请求，学生失败无fallback。
- 新增外接suite测试先暴露两个fixture错误（purpose必须development、实际environment字段为database），均已修正并在当时74项专项中复验。此前70项／386项通过只是新增边界测试前的结果，不冒充最终全仓验证。
- Windows全仓临时目录清理失败定位为test_research_http子服务cwd占用临时root；改为repository cwd，SQLite与禁dotenv仍在隔离临时目录。未关闭非自有服务或修改产品运行策略。
- 首轮收尾CI的模板打包测试仍期待旧题集，并把已删除源码目录中的忽略缓存当作旧实现；改为验证新suite／case／CLI及旧源码文件不存在。失败日志保留在 `data/evals/learning-rewrite-20261029/engineering-ci.log`，未覆盖；修正后的390项Python／22项Node通过日志另存 `engineering-ci-final.log`。
- 统一保护目录读取边界后，最终 `npm run ci` 再次通过：392项Python（41.816s）、22项Node（pass 22、fail 0），同时包含文档链接、仓库卫生、Actions固定版本、CJS语法、模板实际打包及真实本地服务检查。完整日志为 `data/evals/learning-rewrite-20261029/engineering-ci-protected-path.log`，此次没有收费模型请求。前一份390项结果仍保留，不称最终数量。
- `uv run --frozen python scripts/run_eval.py validate` 通过：17项／9学科／8 workflow、全部author_reviewed、0 calls；`uv run --frozen python -m compileall -q src tests scripts`、`node scripts/check-docs.cjs`、限定 `.gitignore/README.md/pyproject.toml/docs/evals/scripts/src/tests` 的 `git diff --check` 均通过。前端未改，本轮没有重跑前端构建或浏览器验收，也没有执行远端CI／发布／部署。

### 四条真实业务链

新工件统一在忽略的 `data/evals/learning-rewrite-20261029/`，未访问或改写旧结果。以下不是17项全量通过率，也不是产品双版本回归。

| 固定任务 | 新子目录 | 真实业务／工程 | 最新自动教学 | 评分请求与限制 |
| --- | --- | --- | --- | --- |
| chain-rule-transfer | chain-rule | completed／met | met | 两次judge，旧4096耗尽，显式16384新attempt完成 |
| recursive-return-simulated | simulated-recursion | completed／met | met | 两次无答案学生请求；两次judge，第二次显式16384完成 |
| tense-flashcards | tense-flashcards | completed／met | met | 一次16384输出预算judge完成 |
| binary-search-lesson | binary-lesson | completed／met | insufficient | 完整证据超过本地96000上下文预算，评分未发送 |

四条业务均观察到deepseek-flash；judge／student也是deepseek-flash，endpoint为 `https://api.deepseek.com`。角色隔离不代表模型家族独立。受控产品source identity均为 `bc17e5014f9e53ad5310e196625569764d0cbdb4f1570ccc8ad3b9dc1b64ba68`；backend_build unknown、model_verified false原样披露，不冒充官方构建证明。

链式法则与递归首次judge都finish_reason=length、最终content为0，completion各4096；reasoning分别13812／13410字符。原错误与用量保留。明确说明后只对冻结答卷追加16384输出预算，不重生成教学、不做JSON修复或静默重试；新completion为9083／4338，均stop且有严格判据JSON。CLI judge默认输出改为16384不代表产品教学改善，ModelSettings类自身默认仍为4096。

二分讲义本地estimated_input=115023，output_reserve=16384，estimated_total=131407，大于96000门槛；is_estimate=true，不冒称供应商实测或上下文拒绝。没有截断正文，也没有扩预算求通过。

### 作者控制与用量

`controls/`使用4096输出配置，`controls-16k/`使用16384；各6／6与作者期望匹配，false_acceptances／false_rejections／errors均0。每套只有5次真实judge请求，无教学输出的控制不发请求。控制覆盖正确回应、事实错误、正确但不教学、提示注入、无输出和虚构来源；两套通过都不等于独立人工校准，报告calibration_status仍unreviewed。

| 范围／角色 | 已观测请求 | prompt tokens | completion tokens | total tokens |
| --- | ---: | ---: | ---: | ---: |
| 四条真实业务 | 20 | 98748 | 49241 | 147989 |
| 学生模拟 | 2 | 3895 | 1083 | 4978 |
| 四条答卷judge，含两次旧失败 | 5 | 89710 | 22616 | 112326 |
| 4096作者控制 | 5 | 6269 | 3443 | 9712 |
| 16384作者控制 | 5 | 6275 | 4099 | 10374 |
| 合计 | 37 | 204897 | 80482 | 285379 |

这些是显式工件中供应商返回的已观测usage，不是账单或远端收费终止证明。业务只按每run最终调用快照计数，不将采证引用重复相加；全部已观测调用的这些usage已知，金额与远端计费状态仍unknown。

新生成离线入口 `acceptance-report.html` 合并四条业务；`acceptance-summary.json` 包含四条业务、两套作者控制及全角色用量。它们只读取明确工件，不扫描历史、不重新调用模型。各trial保存完整请求／原始响应、独立SQLite与日志；旧attempt不覆盖。

### 文档、交接与真实限制

- 长期契约已同步[设计](../../design-docs/backend-evaluation-pipeline.md)、[使用说明](../../../evals/README.md)、[架构](../../ARCHITECTURE.md)、[安全](../../SECURITY.md)、[质量事实](../../QUALITY_SCORE.md)及[一手参考](../../references/deeptutor-learning-evaluation.md)。
- 变更索引见[history](../../histories/2026-10/20261029-0127-learning-evaluation-rewrite.md)，可迁移知识见[预算不是判决](../../learnings/2026-10/20261029-judgment-budgets-not-verdicts.md)。旧三份active评测计划标记被取代后归档，原失败与未执行事实不改写为成功。
- 17项并未全部真实运行，独立人工任务审核／judge校准、未见任务泛化、真人学习增益、浏览器产物呈现与真实双版本配对均未验。三条met仅是当前自动判据结果，不是通用教学质量保证。
- 大证据评分策略、剩余真实覆盖与独立校准见[技术债](../tech-debt-tracker.md)；不再为收尾工程修复追加收费请求。
