# 动画取消请求上限的真实复验

## 范围与授权

用户追问是否测试，继续前述动画生成验证：仅一次独立执行，不传max_tokens/max_completion_tokens，保留timeout、调用次数及64000上下文保护，不重试失败、不调用Grader、不修改历史失败。采用原模型、原8轮冻结历史及相同提示/工具；生成器边界复验，不冒充HTTP历史重建。

## 进度

- [x] 预检请求一致性、独立身份、确认不传max并执行一次。
- [x] 核对暂存候选、最终失败及usage；无已提交成品，产品浏览器未执行。
- [x] 记录结论与边界并归档；本次未启动前后端服务。

## 证据

证据目录data/validation/animation-no-cap-20261026-232023/；测试不写作者默认数据库，先写started标记与命令身份，禁止重复启动。session.json保存新身份与请求预检，result.json/calls.json/run.json/conversation.json保存本次真实结果；原失败输入与调用记录逻辑哈希不变。

## 结果与诊断

**实际测试完成，但业务仍失败。** deepseek-flash，timeout=120、上下文64000、预留8192不变；首请求input/model/system_prompt/messages/tools均与原样本相等。max_output_tokens=null且token_limit_parameters={}，未传两个供应商Token上限字段。

- 新run_c68de827b42b42cbb74b333470346a42；仅1次真实请求，约83.3秒，整个生成约84.1秒。prompt_tokens=12695、completion_tokens=21712、total_tokens=34407，usage未知0次，不推算货币费用。无自动重试、无Grader。
- 本次首响应规范化stop_reason=tool_use、无供应商适配错误，create_animation参数完整解析，HTML为11844字符/12109 UTF-8字节，ArtifactDraft校验通过，真实run步骤中create_animation已ready。这里ready仅为暂存，不是最终产物提交。
- 最终run/turn为failed，业务错误assistance_generation_failed；SQLite为1个run、1次调用、0课程、0已提交产物，无后续付费请求。原子保存没有把失败轮次变成假成功。
- 离线用本次真实首响应、真实ToolManager及临时SQLite重建后续上下文，得到输入估算56608+预留8192=64800，超过64000门槛；ContextManager.prepare确定性复现ContextBudgetExceeded: Context token threshold reached without a configured compressor。因此已定位可复现的收尾阻断路径，不是本次工具JSON截断。实际引擎终止原文未在业务记录中保留，不将离线诊断冒充新模型返回。
- calls.json保留本次完整工具参数；candidate-animation.html只是从真实响应提取的候选，不是修复后保存的业务产物。context-diagnostic.json说明离线重建的方法及估算；诊断不调用模型，也不回写真实实验数据库。

## 覆盖与后续

取消max已真实产生超过8192/16384的可解析动画工具参数；这不证明无限输出或后续样本稳定。当前失败是带8轮历史的产物回填挤满本地保守预算，需后续针对收尾上下文处理，不能继续把问题归为输出max，也不应直接取消所有上下文保护。

没有最终保存的产物，因此交互、数值更新、重置和390px产品浏览器检查均未执行，browser.json显式保留未执行状态；不拿官网或候选页面代替产品成功。未新增业务改动、未启动服务、无待清理进程、未提交或部署。69项本地检查仍是上一轮取消上限策略的结果，本轮未声称重新全量测试。

文档骨架与git diff --check通过；本次5份相关Markdown lint在移除末尾多余空行后复核。

后续用户要求继续，收尾上下文投影已完成旧失败响应离线复放及一次新真实保存；手机默认预览仍遮挡，不回写本计划失败为成功，见[后续修复](20261026-animation-followup-context.md)。
