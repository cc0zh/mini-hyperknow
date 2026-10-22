# OpenAI provider：把 SDK 细节隔离在 LLM 边界内

OpenAI 接入没有改动 Agent 执行循环。`OpenAIService` 实现现有的 `complete(context) -> AssistantMessage` 协议，外部 provider 的请求格式、响应字段和异常都在 `src/agent_core/llm/openai.py` 内转换。

## 关键取舍

- **客户端注入**：生产环境不传 `client` 时由官方 SDK 创建，测试传入 fake client。这样不会为了测试发真实请求，也不会把 API key 写入 fixture。
- **协议转换集中处理**：`to_openai_messages()` 负责 assistant tool calls 与 tool result 的配对格式，`from_openai_response()` 负责 finish reason、usage 和 JSON arguments 转换。
- **错误进入上下文**：网络异常和无效 tool arguments 转成 `AssistantMessage(stop_reason="error")`，执行引擎可以统一停止并保留错误信息，而不是依赖每个 provider 调用方单独 try/except。

## 常见陷阱

OpenAI Chat Completions 的 assistant tool call 后必须紧跟对应的 `tool` 消息；只保存调用而丢掉结果会导致下一次 API 请求被拒绝。另一个风险是工具参数是 JSON 字符串，不是 Python 字典，必须在 provider 边界解析并对非法 JSON 给出明确错误。
