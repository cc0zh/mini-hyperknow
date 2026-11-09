# 网页调研 Agent

## 范围与事实

首阶段先实现独立后端research run，不是完整deep research产品；该端点本身不生成蓝图、讲次或讲义。随后[蓝图工作流](course-blueprint-workflow.md)已将相同研究能力接入造课：全局蓝图形成后确认一次，再自动逐单元展开，而非每个单元重复审批。独立研究验收不替代后续阶段证据。

造课内部联网调研与此前排除的资料上传、知识库、独立聊天／深度学习功能不同；本轮不恢复这些功能，也没有新增前端入口。基础实现与验证事实见[原完成计划](../exec-plans/completed/20261023-web-research-agent.md)；问题—主张—证据链、Exa/Tavily适配及下游课程接入见[证据驱动实施计划](../exec-plans/completed/20261109-evidence-driven-research.md)。

## 工具、输入与输出

- 输入：`goal`（2–4000 字符）和可选 `context`（最多6000字符），可携带已确认的背景和偏好。模型使用当前 OPENAI 配置，不引入独立厂商协议或隐式模型降级。
- 搜索：可配置 `TAVILY_API_KEY`、`EXA_API_KEY` 或两者；仅从后端本地读取，绝不进入浏览器。单一本地 Agent 按问题选择来源；Tavily支持basic/advanced，Exa Search返回query-relevant highlights。保留provider身份，不比较厂商分数；摘要／highlights只用于发现，不算已阅读证据。
- 阅读：`page` 读取公开HTTP／HTTPS HTML或纯文本；Exa Contents按query提取相关片段（适用于PDF、脚本页面等），但不是网页全文。两者都提供稳定`source_id`、最终URL、抓取时间、实际摘录SHA-256、provider与content_mode；所有高亮均标为非全文。不登录或绕过访问限制。
- 报告：按 `ResearchQuestion` 表示优先级和answered／partial／unresolved状态；每个 `ResearchFinding` 是带稳定claim_id的主张，关联问题并逐条保存原文quote和supports／contradicts关系。`source_ids`由服务器从evidence引用派生，保留在报告存储和API输出中。服务器确认引用逐字包含于本轮已保存来源摘录，派生字符偏移与evidence bundle。该检查不证明语义蕴含或来源可靠；模型自报关系不等于独立证明，仍须人工核查和语义评测。

复用 V1 `Agent`／`ToolManager`，每次运行独立上下文，仅注册 `web_search` 和 `read_webpage`。没有文件、命令、浏览器自动化或用户提供工具。结构输出失败允许一次无工具的报告修复，不能在修复中编造新来源。

## 预算与安全

- 每轮最多4次搜索、6次阅读、10轮 Agent 模型请求，另允许一次结构修复请求；无SDK自动网络重试。蓝图反馈会在同一run内开启新research round，旧工具过程和证据保留，新轮单独计工具预算。预算拒绝不会伪装成成功来源。
- 应用采用64,000估算Token窗口、8,192预留输出及输出cap，显式在100%阈值拒绝超限，不配置摘要模型；估算按UTF-8字节，既不是实际Token计费，也不是按模型名称推断的真实窗口。创建前用同一估算器校验输入并预留资料及报告空间；每次工具按剩余预算裁剪JSON／UTF-8负载（每次最多12,000字节、每页最多6,000字符），保留12,000估算Token报告余量。不足时不再读取，使用已有证据收尾。五分钟运行预算在后续调用边界检查，不保证强制中断在途模型请求或DNS。
- 网页输入与目标内容都是数据，不能覆盖系统指令。工具能力受限，不依据网页要求开放文件或命令。
- 抓取限制协议、端口、URL凭据、DNS与所有重定向目标，拒绝非公网地址；连接绑定已验证的IP，HTTPS仍使用原主机名SNI及证书校验，不依赖环境代理。限制响应字节、正文类型、重定向次数和超时；绝对deadline及watchdog在TCP／TLS交接后仍有效，提前EOF或超时正文不保存为成功来源。robots策略获取同样失败关闭，不跟随其重定向或绕过拒绝；仅接受identity编码，不解压未知内容。
- 网页／搜索失败明确保存状态，不用模型记忆冒充网页调研。实际模型返回用量才累计，未知用量不补造。

## 保存、取消与恢复

研究过程、已读来源、问题／主张报告及由精确引用派生的证据bundle存入 `runs.data.research`，输入在 `run.input`，每次模型请求保留提示、消息、工具定义及真实响应到 `model_calls`。沿用 SQLite v3 JSON扩展，不增加第二套业务事实或迁移既有数据；旧报告JSON仍可读取，但没有claim/evidence字段的历史记录不会伪造新证据契约。

任务使用同一个串行 worker，不与课程生成并行占用新的模型执行槽。运行沿用 queued → generating → ready／failed／cancelled／interrupted；不经过课程澄清。工具结果提交后提升run版本并发送现有通知；GET恢复读取快照，不重新检索或调用模型。

取消／停服后不再发起后续模型或工具请求，晚到结果不能提交ready或覆盖取消状态。在途同步网络请求不能保证远端取消，执行槽直到调用返回才释放。重启只标记未完成任务interrupted，不自动重复费用。蓝图反馈先把意见和有界旧报告／证据传回同一research Agent：纯教学表达调整可复用证据，新增事实范围或质疑需先判定缺口并定向补搜；之后仍需用户重新确认蓝图。

显式重试创建新run，继承原目标、context与模型，保留旧过程；本轮重新调研而非自动复用可能过时的网页，不承诺工具级断点续跑。对同一失败父run最多创建一次重试，命令幂等返回已有资源当前快照。

## 调用与验证

`POST /api/research-runs` 返回202，正文含 `client_command_id`、`goal`、可选 `context`。读取／订阅／取消／重试复用 `/api/runs/{id}`、`run:{id}` 及现有run命令；缺模型或搜索key返回503且不创建任务。密钥不要发送给浏览器或写入API正文。

本地函数、SQLite和实际HTTP检查不是成功搜索证据。本次Exa/Tavily适配与证据贯通通过离线测试验证，未执行真实搜索、提供商A/B或付费课程实验，因此不宣称Exa优于Tavily或已改善内容质量。若要进行真实验证，需单独授权后显式运行：

```powershell
uv run --frozen python scripts/verify_research.py
```

它在独立 `data/validation/research/` 中通过同一个worker执行实际搜索、读取及模型工具循环，产生真实服务费用；不接触用户课程数据库。缺凭据退出2（blocked），实际失败退出1。完成后仍须人工核对网页依据与结论，不把结构校验当内容准确验收。
