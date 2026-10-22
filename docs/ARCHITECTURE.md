# 架构总览

这份文档用于描述仓库的顶层结构。下面这些内容是模板占位，等新项目真正落地后，应该尽快替换成真实架构。

## 预期的仓库结构

- `apps/`：可部署的应用、服务或入口。
- `packages/`：跨应用复用的库、契约和共享能力。
- `infra/`：部署、基础设施和环境定义。
- `scripts/`：仓库级自动化脚本，供人和 Agent 直接调用。
- `docs/`：仓库知识库，也是本地规则和上下文的正式来源。

文档边界由 [`docs/design-docs/index.md`](design-docs/index.md) 统一导航：本文件只维护顶层结构和模块边界，设计文档维护长期有效的架构、产品决策及其状态，execution plan 只维护一次任务的实施过程与验收。计划完成后，仍然有效的决定应回写设计文档，不要让已归档计划成为唯一来源。

## 边界建议

当前模板自动化由 `scripts/*.cjs` 实现，使用 Node.js 22+ 内置模块；`scripts/lib/` 共享路径、分发规则和检查逻辑，`tests/tooling.test.cjs` 提供回归测试。所有平台统一使用 Node.js/npm 入口。Git 用于初始化，系统 tar 用于 `.tgz` 打包。Windows 操作入口见 `docs/WINDOWS.md`。

`scripts/lib/scaffold.cjs` 定义新项目内容边界，初始化和打包共用顶层白名单与目录筛选规则。只有列出的根文件和 `docs/`、`scripts/`、`tests/`、`.github/` 可以分发，新增顶层内容需显式加入白名单。若存在 `.template/`，它为新项目提供干净的 README、质量表和发布记录；缺少某个覆盖文件时，脚手架回退到当前文档。生成内容不含该目录、宣传素材、旧任务记录、已写的学习笔记、演示页或可选外部沙箱扩展。源码仓库仍保留维护资料，新项目只继承目录与规则。

- 基础设施和运行编排要显式版本化，不要藏在手工操作里。
- 避免隐式跨包耦合；一旦仓库成形，就把允许的依赖方向写清楚。
- 只要架构有变化，就同步更新这份文档。

## Python Agent V0

```text
src/agent_core/
  types.py       # Context、消息、tool call/result 数据契约
  context.py     # 内存会话和 system prompt 组装
  tools/         # ToolDefinition、ToolManager，以及 read_file 示例工具
  llm/           # LLMService 协议、Mock provider 和 OpenAI provider
  engine.py      # LLM -> tool calls -> tool results 的执行循环
  agent.py       # 面向调用方的 Agent.run()/abort() 入口
```

依赖方向保持单向：`agent` 组装 `context`、`llm` 和 `tools`；`engine` 只依赖这些协议；具体 provider 和工具通过接口注入。执行循环每轮先把 assistant 消息写回上下文，再顺序执行 tool calls 并写入 tool result，直到模型不再返回调用。`ToolManager` 将工具异常转成可供模型理解的错误消息，并限制单次输出长度，避免 V0 工具结果无界膨胀。`OpenAIService` 通过官方 SDK 调用 Chat Completions，配置从构造参数、进程环境变量、项目根目录 `.env` 依次回退；SDK 客户端可注入以支持离线测试。`.env.example` 随脚手架分发，实际 `.env` 被忽略且不进入新项目和 release 制品。

## 新项目需要补齐的内容

- 核心产品面和运行拓扑。
- 包分层与依赖边界。
- 数据流与存储模型。
- 可观测性方案和本地开发模式。
