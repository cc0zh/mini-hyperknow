# Agent 内核 V1

## 范围与接入边界

V1 在既有 Python 内核中增强工具、上下文及执行循环，保留同步 `LLMService.complete(context)`。它不是产品版本号，也不是新增的课程功能。课程／讲义／问答／题组继续使用显式工作流及 SQLite，不注册文件或命令工具，不把课程事实迁移到内核 JSONL。

通用内核能力以调用者显式装配为边界：旧 `Agent(llm, tools=...)` 保持可用；持久化需提供 `SessionStore`，压缩需预算与摘要服务，写入需真实审批通道。未配置的能力明确不可用，不以假摘要、空历史或模板响应降级。

## 模型与执行循环

- `LLMConfig`／`create_llm_service` 复用现有 OpenAI-compatible provider，不为同协议厂商复制实现类。SDK 网络自动重试默认关闭。
- `LLMServiceRegistry` 显式管理 high／medium／low；缺 tier 报错，不静默回退。`from_env()` 的 high 使用 `AGENT_HIGH_MODEL` 或既有 `OPENAI_MODEL`，medium／low 分别需要 `AGENT_MEDIUM_MODEL`／`AGENT_LOW_MODEL`。
- `AGENT_<TIER>_MAX_OUTPUT_TOKENS` 可限制对应服务输出；from_env 的 low 默认 1024。同步 OpenAI-compatible 请求使用 `max_completion_tokens`，供应商不支持时明确报错，不静默重试另一个协议。
- tier 只是用途，不保证价格或能力；可显式把多个 tier 配成相同模型，不宣称因此节省成本。配置共用既有凭据及 endpoint，不在日志输出密钥。
- `Agent` 可使用直接 service 或 registry，不能同时提供。registry 的主 tier 默认为 high，压缩使用显式配置的 low。调用者提供 context 时，其压缩服务及统计回调也由调用者装配。
- 每次主模型调用前（包括工具后续轮）执行上下文预算检查；取消后不发起摘要、主调用或新工具。已发出同步网络请求不能保证远端取消，晚到工具调用不执行。
- 单个 Agent 禁止并发 `run`；不同 Agent 使用独立 context。`max_turns` 保留默认 20 的兼容安全阀，可设 None 并提供 `should_stop_after_turn`。停止后不自动重试或接续执行副作用。
- 生命周期覆盖 agent／turn／assistant／tool 及审批事件；这些内核对象不直接成为产品 WebSocket 协议。事件是深拷贝观察快照，观察者不能修改已保存调用；失败观察回调不会吞掉执行结果。工具结果按完成顺序即时持久化、通过调用 ID 配对，调度器返回列表保留原请求顺序；provider 边界闭合中断的工具组，绝不重新执行工具补历史。

## 工具与权限

`ToolManager` 负责注册、定义、参数校验与结果格式；`ToolScheduler` 负责生命周期、审批与调度。连续只读调用可并行；写入和命令形成串行屏障。未知工具、无效参数、拒绝、审批超时及取消均返回明确工具错误。

`ApprovalStore` 允许宿主在另一线程查询 pending 并按审批 ID 决定，不能根据工具名批准未来所有调用。没有审批通道时，需审批操作拒绝。创建工具不代表批准写文件或执行命令，直接调用 manager 也不能绕过新工具的审批要求。

`expires_at` 使用单调时钟，表示本次执行授权的有效期，而不是“已经批准就永久有效”。即使 resolve 在到期前成功，实际执行门禁检查时已过期仍保守拒绝；宿主应重新展示具体调用，而不是延长旧授权。

`execute_batch(..., on_result=...)` 的结果提交回调是持久化屏障，不是可忽略的 UI 事件。提交失败立即停止后续写入；已执行副作用可能发生，未记录调用在会话重开时只能标记 unknown。它不承诺副作用与 JSONL 是同一事务或 exactly-once。

`create_workspace_tools(root, output_dir=...)` 显式注册 read_file、list_files、grep、glob、edit_file、write_file 和 bash。新文件工具限制在 root，解析真实路径并拒绝越界／符号链接逃逸。保留旧 `read_file_tool` 仅为兼容，它不带工作区边界，不能作为受限工具包使用。

- read_file 分页且有界；搜索通过系统 rg，缺 rg 显式失败，不切换假结果。
- edit_file 使用精确匹配及已读摘要，拒绝歧义和读后内容变更；文件写入采用原子替换。摘要检查不能代替操作系统强隔离，宿主其他进程仍可能在检查后修改文件。
- bash 在 Windows／POSIX 选择对应 shell，使用受控进程 runner、超时／取消和流式磁盘输出，不将完整进程输出堆在内存。
- 工作区路径规则只约束文件工具，**不是操作系统沙箱**。批准的命令能使用宿主用户的文件／网络权限，不应执行不可信内容；产品端不开放它。
- 输出裁剪严格限制回填长度；长输出保留本地完整文件与指针，不能把截断结果描述为全文。输出文件同样可能包含敏感内容，应由调用者选择私有目录、定期清理，不提交版本库。

## 会话、记忆与压缩

`SessionStore` 使用独立本地 JSONL，并约束同一会话单 writer。原始消息与 turn／压缩记录可追溯；模型只使用当前 active history。恢复不调用模型，不重新执行工具；中断工具结果标记为 outcome unknown，不能据此认定副作用没有发生。

只有尾部未完成记录允许按规则恢复，中间损坏明确报错。调用者负责关闭提供的 store，不能让多个 Agent 争写一个会话。产品业务恢复仍遵守 SQLite 中的 run 状态，不从通用会话推断课程完成。

`LongTermMemory` 是调用者显式维护的有界偏好／事实文件，支持更新和删除；不自动推断或偷偷积累用户画像。历史与记忆均以数据而非新系统授权注入。

`TokenEstimator` 覆盖系统提示、记忆、消息、工具 schema 和预留输出，使用保守估计而非固定轮数。`max_context_tokens` 应按实际模型窗口配置；reserve 仅为输入预算预留，需限制服务输出时另配置 `LLMConfig.max_output_tokens`。估计值不是计费用量，不是 tokenizer 的精确计数。

达到阈值时使用 low tier 摘要旧的完整 user turns，保留最近完整轮及 assistant／tool 配对。摘要成功且确实变小、最终预算可满足才提交 active checkpoint。摘要失败、空输出、取消或当前轮单独超限均明确停止；原始日志和压缩前 active history 不被清空，不循环收费重试。

摘要请求同样可能溢出，因此有独立的完整输入＋输出预留检查。`Agent.compression_max_context_tokens` 默认 32,000，`compression_reserve_output_tokens` 默认 1024；这只是保守应用预算，不是按模型名称推断的实际窗口。调用者须按真实 low 模型调整，并配置其服务输出 cap 不超过预留。需要不同摘要保留轮数时显式装配 `ContextCompressor` 和 `ContextManager`。

`TokenCounter` 仅累计 provider 实际返回的 usage，区分 completion／summary；缺 usage 保留未知，不用估算值补零冒充真实成本。`AgentRunResult.usage` 为该 Agent 生命周期累计统计，不是货币金额。

## 使用与验证

沿用旧 service 的最小接入无需改动。需要 V1 装配时，可显式构造：

```python
from pathlib import Path

from agent_core import Agent, LLMServiceRegistry, SessionStore, create_workspace_tools

root = Path("data/agent-workspace")
root.mkdir(parents=True, exist_ok=True)
with LLMServiceRegistry.from_env() as registry:
    with SessionStore("data/agent-sessions/local.jsonl") as session:
        agent = Agent(
            registry=registry,
            tools=create_workspace_tools(root, output_dir="data/agent-output"),
            session_store=session,
            # 按实际模型窗口设置；这只是应用预算示例，不是模型规格。
            max_context_tokens=16_000,
            reserve_output_tokens=2_000,
        )
        result = agent.run("读取工作区中的说明文件，说明项目入口。")
```

示例没有 ApprovalStore，因此写入／命令不会执行；只有设置 low tier 才有摘要服务，否则到达预算边界明确停止。长会话应在调用前配置适合模型的预算，不依赖默认无限内存上下文。

直接检查使用 `uv run --frozen python -m unittest discover -s tests -p 'test_agent*.py' -v`；真实模型验收另行显式执行，产生费用，不能由本地纯函数检查替代。实现、命令及真实结果以[升级计划](../exec-plans/completed/20261022-agent-core-v1.md)为准，不扩张为完整产品 V01–V12 验收。
