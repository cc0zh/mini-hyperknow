# 轻量后端评测首切片

状态：本轮实现、一次授权实验及本地门禁已交付；真实实验并非质量／预算全部通过。计划保留active，等待后续单独授权的限额复验与独立真人校准，不自动追加收费。

## 目标、范围与风险

- 目标：用一个概念解释Case跑通数据准备与业务实验两条流程，保留真实HTTP执行、ATIF-v1.7、规则与LLM分项判定及自动样本回流。
- 验收：可校验并固定Case／Rubric；真实业务身份与独立SQLite对应；轨迹符合固定文字子集；Grader无工具、单次请求、错误不通过；同Case好坏运行不重复造题；恢复／重评不重跑原教学。
- 范围：新增普通Python评测模块和单个CLI入口，复用现有provider和业务契约。保持Skill、Prompt、教学命令与事务不变；health追加防误连指纹，provider修复已发现的官方DeepSeek限额参数兼容。不建插件、调度、前端、评测数据库或自动优化平台。
- 风险：收费重复、评错对象、泄露Rubric、未知状态误通过、自动标签冒充人工确认。通过显式执行开关、持久化幂等身份、HTTP／只读SQLite交叉核对、分项Schema和版本化记录控制。
- 授权：用户已要求本地实施与检查，后续明确授权一次真实闭环：deepseek-flash教学run最多9次调用／360秒，随后同模型Grader一次、2048输出token／90秒，无自动重试或重评。不以本地检查替代付费验收，不覆盖.env，不得读取／修改作者默认数据库或发布数据。
- 设计：[后端教学评测](../../design-docs/backend-evaluation-pipeline.md)、[ATIF固定来源](../../references/atif-trajectory-format.md)、[即时协助](../../design-docs/instant-assistance.md)。

## 进度与决定

- [x] 核对编码／计划约束及已有架构，限定为平面普通模块，不修改业务教学策略。
- [x] 数据准备：Case／Rubric校验、内容寻址和运行样本回流；验证重复运行只增加样本、不改变标准答案。
- [x] 业务执行：真实HTTP、独立数据身份校验、命令恢复及证据快照；验证不配置模型时安全阻塞和本地真实HTTP路径。
- [x] ATIF：基于既有调用快照导出固定v1.7文字子集；验证工具反馈、格式修复、缺失证据、版本／引用拒绝。
- [x] 评分：独立配置的一次LLM Grader请求、严格结果校验、规则检查与失败／未知保留；纯函数验证不使用Mock／Fake provider。
- [x] 检查：uv冻结环境、完整Python与仓库必需检查通过；修复本轮引起的模板分发断链及已发现的参数兼容问题。
- [x] 一次真实实验：在隔离后端完成教学与Grader调用，核对轨迹、提交、恢复无新增调用及样本关联；教学为bad、预算异常另列，不写成全部质量通过。
- [x] 文档、学习与history：补充实际入口、格式和边界，保留既有未提交调研；索引见[history](../../histories/2026-10/20261026-1137-lightweight-backend-eval.md)，学习见[配置与事实分离](../../learnings/2026-10/20261026-evaluation-facts-not-promises.md)。
- [ ] 后续限额复验：另获明确预算后验证max_tokens在真实DeepSeek端生效，本轮不再请求。
- [ ] 后续评分校准：独立真人核查首份及好／坏／边界样本；助手复核不冒充真人标注，不自动采用为留出基准。

### 2026-10-26 实施决定

- 首轮Case明确要求一次直接解释、不向学习者提问、不创建产物，避免把“不需要先提问”误解为禁止所有结尾检查而让Rubric收紧原意；这是评测输入澄清，不修改业务契约。
- 数据Pipeline输出固定Case并关联带来源的good／bad／unresolved运行样本；自动标签不成为黄金答案，默认只用于开发，基准／留出集不自动变化。
- 已新增eval_cases、eval_atif、eval_grading、evaluation及scripts/run_eval.py，均为普通函数，无框架基类。CLI为prepare／run／grade／show。
- 使用已有Pydantic与标准库构造项目ATIF-v1.7文字出口约束，不安装整个Harbor；来源固定，不声称实现全部版本／多模态。规范兼容需对照固定上游来源与实际导出核查。
- 验证只使用纯数据逻辑、真实文件／SQLite与实际本地服务；不注入SDK替身或编造成功执行。Grader网络行为只由授权的真实调用验证。
- 现有health无存储身份，唯一产品接口变更是追加非敏感路径指纹；在任何写请求前比对，不改教学接口／Prompt／Skill／事务。其用途为防误连，不是认证。
- 审查后补强：已知／未知提交回执丢失时不再POST；原turn指向retry派生run时拒绝采用；首次评分替换未评分占位，不重复计入同次运行样本。对应42项本地测试已通过。
- 一次真实调用发现Grader报告输出超过请求上限；查阅2026-10-26官方[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion)确认max_tokens字段，修复已知官方hostname映射，未知端点保留原协议。添加usage超限审计、输出参数记录及中文CLI UTF-8检查；没有再次付费验证，未擅自关闭thinking或采集隐藏推理。
- 完整CI首次发现新evals未被模板分发清单携带，造成生成项目文档断链；已将脱敏evals加入源码清单并断言私有data不随包分发。没有发布制品或改变部署流程。

## 验收与交接

### 本地检查

- uv sync --frozen通过，无新依赖、uv.lock未变。
- 最终npm.cmd run ci通过：339项Python、21项Node，包含真实临时HTTP／SQLite、SDK纯参数构造、恢复与数据回流。完整日志在忽略的data/evals/acceptance-20261026-1203/final-ci.log，另有UTF-8副本final-ci.utf8.log。
- Markdown检查通过：markdownlint-cli2 v0.24.0，本轮14份文档0问题；git diff --check通过。最终计划文档变动后另补文档检查，不重复收费实验。
- 没有前端改动、未运行浏览器验收；无Mock／Fake／patch provider，不把无凭据worker失败写成真实生成成功。

### 一次真实闭环

执行器与原始证据均位于忽略的data/evals/acceptance-20261026-1203/：verify.py、acceptance.json、run/result.json、run/trajectory.json、cases/及local_review.json。它们只在本地，不进入Git或源码分发，后端已由验收器停止。

| 项目 | 实际事实 |
| --- | --- |
| Case | concept-chain-rule-001，显式一次解释／不提问／不产物，Rubric三项 |
| 业务run | run_5fb76d3f756c467298fad9e9ef0532fc，真实HTTP及SQLite ready |
| 被测调用 | deepseek-flash共2次，实际get_skills加载concept-explanation，回复原子保存，无产物／问题／等待 |
| 轨迹 | ATIF-v1.7通过本地文字子集校验，已知工具反馈／调用完整；不声称已运行完整Harbor校验器 |
| 教学usage | prompt 8390、completion 1544、total 9934，两个调用均有usage |
| Grader | 同模型一次，分项correctness=fail、addresses_confusion=pass、instruction_following=pass |
| Grader usage／预算 | prompt 1779、completion 6109、total 7888；请求输出2048被超过，已记exceeded，**预算验收不通过**，没有再请求 |
| 恢复 | --resume后仍为1个run、2条教学调用、2条业务回执，grading attempt仍1个；未新增收费 |
| 自动回流 | 1个Case、1个bad样本；重复收集未新增样本，不生成黄金答案 |

助手对照数学核查：回复将x=3处导数约-5.4668当作x从3到4时的有限变化；实际sin(16)-sin(9)约-0.7000，确认该处失败。对“简短要求”的pass存在疑问，已留校准候选；没有覆盖原始Grader判定，calibration_status仍为unreviewed。

首次真实实验先于限额参数修复；修复后只运行本地检查和离线摘要／回流，没有第二次教学或Grader。金额未核算：缺完整价格／缓存口径，不编造费用，也不推测completion token内部如何分布。

### 未完成项

上述两项后续复验／真人校准及教学策略纠正均未完成，见[技术债](../tech-debt-tracker.md)。不将本次bad样本包装为质量提升；源端可能未记录的异常、全部业务、模型／版本统计比较也未覆盖。后端未声明代码版本，保留unknown；agent.version仅标识实际Prompt／工具／Skill配置哈希。

长期约束已写回设计、入口、安全及质量状态；未提交或发布。等待后续授权再推进剩余项，归档时更新全部入链。
