# 明确动画请求不设置输出上限

## 用户诉求

动画不限制max。按前文动画输出Token上限理解，不移除超时、上下文、次数或HTML结构约束。

## 改动与边界

- assistance_generation.teaching_output_limit依据冻结的requested_artifacts/forbidden_artifacts选择：明确请求且未禁止动画返回None，其余使用原output_reserve。
- generate将结果传给OpenAIService；已有completion_parameters(None)返回空字典，不发送max_tokens或max_completion_tokens，不新增供应商适配。
- 上下文仍预留8192，不是输出上限；调用审计增加max_output_tokens，与output_reserve分开。普通教学默认8192，构造参数实验入口保留。未点名而模型自行选动画仍受普通轮次上限约束。
- 不更改提示、Skill、渲染器、供应商模型、时限、调用次数、HTML长度或保存门禁。不保证供应商默认更大或无限输出。

## 验证

uv run --frozen python -m unittest tests.test_assistance_domain tests.test_assistance_storage tests.test_assistance_http tests.test_agent_llm_v1 -v：69项通过，0失败/错误/跳过。dotenv禁用、密钥清空、uv离线；直接函数、临时真实SQLite和实际本地HTTP验证，无provider替身或付费调用。

新增两项检查：动画在8192/16384预留下均省略两类上限字段；普通/其他产物/明确拒绝动画保留原上限。未重新运行全量测试或真实动画，不把本地参数检查当作生成成功。原16384失败保留于[预算实验](../../exec-plans/completed/20261026-animation-output-budget.md)。

文档骨架检查、7份相关Markdown lint（0问题）及git diff --check通过。未提交、部署或修改既有生成数据。

## 后续真实复验

用户追问后已实际执行一轮不传max的隔离复验：输出21712 Token、完整动画参数已暂存，但收尾阶段被本地上下文门槛挡住，最终failed且0已提交产物；未重试，浏览器未执行。调用、候选与离线诊断证据统一见[复验完成计划](../../exec-plans/completed/20261026-animation-no-cap-validation.md)，不将上一节的当时“未真实复验”改写为已通过。
