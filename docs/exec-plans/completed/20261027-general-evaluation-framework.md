# 通用评测框架实施

状态：2026-10-29旧框架已被[学习任务评测重写](20261029-learning-evaluation-rewrite.md)取代，归档保留历史范围、授权、失败与未执行项，不冒称原任务全部完成；下文不作为现行命令。

## 目标、范围与风险

- 目标：落实[通用教学评测设计](../../design-docs/backend-evaluation-pipeline.md)，保留Case Pipeline及评测Pipeline；统一任务、动作恢复、检查点证据、评分和离线比较，接入B01–B08。
- 验收：现有单轮评测不回归；公共Runner不出现教学业务分支；代表性多轮、蓝图确认、讲义前置出题通过纯逻辑与真实文件／SQLite／HTTP工程检查。模型质量与全部业务真实执行另列，不能用本地检查替代。
- 范围：新增独立eval_core包、Hyperknow显式接入、CLI命令和版本化任务；保留旧CLI与旧验收格式。不更改产品Prompt／工具／业务事务，不清理作者数据、不动已有其他任务修改。
- 授权：用户已要求开始实施，本轮自主完成本地可逆编辑与检查；不启动收费业务、回答器或Grader调用，不读取或写入作者业务数据库，不发布或部署。
- 风险：重复收费、旧产物误作新执行、私有评分泄漏、检查点晚采和状态身份混用。通过调用前日志、未知状态阻塞、资源清单与来源校验、执行／评分分区及固定证据控制。

## 进度与决定

- [x] 固定schema、接入协议与迁移边界；验证严格输入及旧Case迁移。
- [x] 实现Case Pipeline及公共Runner；验证固定版本、有限交互、持久恢复、证据完整性。
- [x] 接入B01–B08，增加单轮、多轮、蓝图及前置题组等Case；逐项列真实依赖／前置材料缺口。
- [x] 统一规则／模型评分、离线报告／比较和CLI；验证重评不跑业务、比较不调用模型。
- [x] 运行相关Python及仓库必需检查，修复本轮问题，同步设计事实、README、history及必要学习记录。
- [ ] 后续真实验收：另行明确预算及真实fixture后，执行代表性和全业务模型任务、独立评分校准；本轮未授权、不执行。
- 2026-10-27：采用普通字典JSON契约＋显式Protocol，拒绝任意表达式、动态插件和通用DAG。新包不依赖hyperknow；接入层可复用旧ATIF出口与已有只读安全工具。
- 2026-10-27：保留旧prepare／run／grade／show行为；新schema和新入口显式区分。旧Case由纯函数转换成新版本，不覆盖原文件和首切片验收。
- 2026-10-27：observe返回统一state／outcome、actions、resources及checkpoints；所有写入仅通过先持久化的动作执行。prepare仅核对已有真实条件，不隐式创建课程或调用模型。
- 2026-10-27：health追加search.configured／verified非敏感状态，供造课／调研在付费前校验搜索配置；配置不等于真实连通，不披露密钥。其余产品生成、Prompt及事务不变。
- 2026-10-27：交互步骤使用固定action及input、when的state／action／checkpoint有限匹配，可声明optional；接入层绑定动态ID和expected_version，不从Case执行代码或读取私有checks。
- 2026-10-27：resume的preflight接受持久bindings，核对原环境与收据，而非要求运行后的数据库仍等于初始空库／fixture。执行、评分与ATIF导出共用.writer.lock。
- 2026-10-27：evidence_fields显式投影data顶层字段；先校验原始哈希，评分只读取实际发送字段，引文不能来自未提供材料。缺失字段不静默截断或调用模型补全。
- 2026-10-27：新资产库默认data/evals/v2/{cases,benchmarks,samples}，旧库及验收不改写；14个开发Case及固定Benchmark存evals/general。publish仅记录显式复核声明，不制造独立真人校准。
- 2026-10-27：含LLM的实验先固定全部公开评分配置，执行时在业务调用前核对定义哈希；比较按真实fixture摘要、Case、评分版本、环境策略和重复编号配对，不只比较成功子集。

## 验收与交接

- 当前状态：本轮实现、交付文档、工程检查及已发现问题修复完成；计划保留active等待真实模型质量验收，不将目标代码覆盖写成内容质量通过。后续已单独授权的三项小规模验收进展见末尾补充，不回写本计划原工程检查的授权范围。
- uv sync --frozen通过，无依赖或锁文件改动。
- 首轮完整npm.cmd run ci通过：477项Python、21项Node，包含模板分发／文档／仓库门禁；实际HTTP及SQLite检查覆盖动作、两轮执行、恢复、蓝图版本、课程与题组前置，不使用Mock／Fake provider。测试中的显式schema提交只是事务检查，不是模型生成证据。
- 最终npm.cmd run ci通过：482项Python、21项Node，包含后续取消收尾与实验身份回归；原始日志位于忽略的data/evals/local-validation-20261027/final-ci.log。本轮修改文档Markdown检查0问题，git diff --check通过。
- 独立只读评审发现两项P1，均已修复并添加回归：执行前重建整个固定实验的Case／subject／repetition／trial_id身份，部分篡改在创建接入前拒绝；混合任务集按Case是否含LLM检查选择评分配置，纯规则定义不混入全局模型配置。未发现隐式重发或写锁分裂。
- 实际离线资产闭环通过：发布14个Case、冻结开发Benchmark，生成两个unknown身份占位版本的28项计划任务并报告28项pending；没有业务或评分调用，不把占位版本当真实对比。私有证据索引为data/evals/local-validation-20261027/{acceptance,experiment,report}.json。
- 新CLI实际validate／migrate已离线执行，原Case未改写；旧命令帮助保留，新命令有独立入口。固定Benchmark包含14个开发Case，结构和哈希由测试核对。
- 文件入口：src/eval_core/{adapter,contracts,store,cases,runner,grading,reporting}.py；src/hyperknow/eval_{adapter,evidence,checks,cli,migration,trajectories}.py；scripts/run_eval.py；tests/test_eval_{core,adapter,core_grading,reporting,cli,trajectories}.py。
- 当前限制：有界模型回答器尚未实现，配置该模式会在业务前blocked；开放式问题仅按固定资料／明确映射回答或Case显式skip。独立候选提取目录尚未建设。源端无持久历史检查点，错过的版本和未记录异常调用不补造；后端未公开可信代码身份则unknown。
- 费用限制：max_model_calls是已报告事实的本地门禁，不保证在途远端取消或供应商硬上限；执行与评分错误、未知usage及安全收尾缺口均单列。
- 收费验收：本轮不执行。后续需单独明确代表性任务、真实前置材料、模型／回答器／评分器配置及预算。
- 原首切片预算复验及独立真人校准仍由[原计划](20261026-lightweight-backend-eval.md)保留，不因本次实现销项。
- 后续审查发现正式Case首步不匹配、预算计数未接通及旧评分证据绑定缺口，修复和新增回归见[可靠性修复计划](../completed/20261027-evaluation-reliability-fixes.md)。本计划的历史CI／28项pending事实保留，不代表这些缺陷当时已被覆盖；当前Case／Benchmark须使用修复后的新内容版本。
- 后续真实验收已获15元预算目标及三项任务授权：单轮deepseek-flash真实交付，4项程序规则通过；Kimi评分在90秒及显式180秒重评时分别超时／连接失败，质量结论undetermined，两轮与闪卡未启动。不能确认总费用或评分可信度，仍不构成全业务验收；详细证据、授权变更、源码边界及阻塞条件见[三项真实评测记录](20261027-three-case-real-evaluation.md)。
- 14:26追加：用户再次显式授权仅重试一次评分，第三次Kimi请求成功；单轮数学与针对性通过，因不够简短而指令遵循不通过，整体failed。教学证据未变，旧错误保留；其余两项未执行，任务集与真人校准未完成，不能将单次评分成功视为完整验收。
