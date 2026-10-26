# 动画输出预算的单样本复验

## 目标与授权

用户同意只提高预算的一轮动画复验。沿用原失败样本的模型、冻结输入、提示与工具，不新增Skill、生成器或渲染架构。输出上限与上下文预留同步从8192调至16384；普通教学默认不变。

## 范围与边界

- 独立新数据目录、新执行身份，只执行一轮Agent流程，不重试失败run，不购买Grader。
- 沿用现有每轮调用数、时限、一次格式修复规则；记录所有实际请求和usage，不用一次成功证明稳定性。
- 不写作者默认数据库，不修改原失败证据，不输出密钥，不提交或部署。
- 先实现最小预算注入并本地测试，再运行真实生成；完成后检查控件、数值、重置和390px窄屏，失败也如实交付。

## 进度

- [x] 预算入口与本地回归，验证默认仍8192、实验各处均16384。
- [x] 原冻结输入的新身份隔离复验，记录usage、耗时和结束原因。
- [x] 核对无产物、浏览器未执行及证据归档；本次未启动前后端服务。

## 验收记录

增加AssistantGenerator的仅构造参数output_reserve，默认8192；供应商max_output_tokens、Agent上下文预留、逐请求上下文门禁和审计均使用该实例值，未新增用户接口或环境配置。54项即时协助规则、真实SQLite及HTTP检查通过；新增默认不变、参数合法性和付费前上下文门禁2项测试。实验脚本语法检查及目标差异空白检查通过。

真实实验使用原冻结输入的生成器边界，非全新会话端到端历史重建；首请求必须逐字段核对system_prompt/messages/tools/model/input与原记录一致，否则不调用模型。原失败证据见[教学重构真实验收](../completed/20261026-real-teaching-refactor-validation.md)。

### 实际执行与结果

**实验完成，生成失败，不启用更高产品默认预算。** 2026-10-26使用deepseek-flash、官方原端点、原timeout=120，保留原8轮历史及空Skill快照；input/model/system_prompt/messages/tools五项均与原记录相等。仅改变实例输出上限与上下文预留至16384；64000上下文限额、工具提示、业务提示、模型和执行规则未变。

- 新身份run_9ac4ad81a92d42ef9bcc7bc78dc612a9；独立数据目录data/validation/animation-budget-20261026/。原run_2ec49abb47904886b98e0e3f3792cf1f及其调用记录的逻辑哈希核对不变。
- 1次模型调用，prompt_tokens=12695、completion_tokens=16384、total_tokens=29079；usage未知调用0次。请求约71.7秒，整个生成约72.4秒。不推算账单金额，无Grader、无失败重试。
- 模型规范化stop_reason=error，适配层错误为OpenAI returned invalid tool arguments: Unterminated string starting at: line 1 column 55 (char 54)。业务错误assistance_generation_failed。
- SQLite最终1个failed run、1个failed turn、1次调用、0课程、0产物、0工具步骤，active_run=null。没有截断HTML冒充成品。
- 提高上限后实际用满16384且JSON未闭合，说明仅将8192翻倍并未让该样本成功；模型有随机性，不能据两次非确定输出断言预算是唯一原因，亦不说明必须新增Skill或重写架构。

### 诊断与浏览器边界

当前OpenAI适配层先解析tool arguments，再处理finish_reason；解析失败返回只含错误/usage的AssistantMessage，原始参数和供应商finish_reason未保留。因此本次能确认使用量达到请求上限、JSON字符串未闭合，但不能直接声称记录到了远端finish_reason=length，也无法复原HTML、检查重复膨胀或分析输出各部分Token。没有重新调用模型来补证据。

无成品，浏览器渲染、控件、数值、重置及390px检查均**未执行**，不记为通过；没有启动前后端、没有服务待清理。后台启动器首次报告exit 0但无日志、started标记或数据库；确认未执行后才前台启动，真实计数来自最终SQLite而非空任务回执。

证据：session.json记录隔离存储身份及预检；command.json在执行前保存命令；started.json防止重复启动；calls.json/run.json/conversation.json/result.json保存实际记录；browser.json显式标未执行，local-regression.json保留54项本地结论。原始失败和本轮失败互不覆盖。

### 后续决定

保留仅构造参数作为有界实验入口，运行服务仍默认8192；不新增环境变量/API、不提高全局预算、不改提示或Skill。下一步优先补充脱敏/限长的原始工具参数及finish_reason失败诊断，再按输出证据决定是否收敛制作范围或调整生成方式；这是待办，不在本轮扩大实现或付费授权。

后续用户要求动画不限制max，当前明确动画轮次已取消请求上限；这是独立的本地策略改动，不改写上述16384实验结果，也未追加付费调用。当前行为见[即时协助契约](../../design-docs/instant-assistance.md#模型与产物)。
