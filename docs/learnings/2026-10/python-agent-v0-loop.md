# Python Agent V0：把执行循环保持在可替换边界内

本次 V0 内核把 Agent 拆成四个职责：`ContextManager` 维护消息，`LLMService` 只负责生成下一条 assistant 消息，`ToolManager` 负责工具声明与执行，`run_agent_loop` 负责把它们串起来。

## 为什么 LLM 只需要一个小接口

执行循环关心的不是供应商 SDK，而是一个稳定事实：给定当前上下文，模型返回文本或 tool calls。因此用 `complete(context) -> AssistantMessage` 作为协议，Mock provider 和真实 provider 可以共用同一套循环测试。provider 的消息转换、重试和流式细节可以留在接口实现内部，不污染 Agent 核心。

## 为什么工具结果必须统一

工具可能返回字符串、结构化数据或抛出异常。如果这些结果以不同形式进入上下文，模型就很难判断失败是否可恢复。`ToolManager` 统一生成 `ToolResultMessage`，并把异常转成明确的 `Tool error` 文本；同时对输出做硬截断，避免一个文件读取结果耗尽后续对话的上下文空间。

## V0 的边界

V0 的内存会话、顺序工具执行和固定最大轮数是教学与本地验证取舍，不是生产保证。需要跨进程恢复、权限审批、上下文压缩或并发工具时，应在这些具体信号出现后升级到 V1，而不是提前把复杂度塞进核心循环。
