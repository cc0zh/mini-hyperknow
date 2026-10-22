## [2026-10-22 10:34] | Task: 接入 OpenAI provider

### 🤖 Execution Context

- **Agent ID**: `codex`
- **Base Model**: `GPT-5`
- **Runtime**: `pi`

### 📥 User Query

> 为 Python Agent V0 内核接入 OpenAI。

### 🛠 Changes Overview

**Scope:** `src/agent_core/llm/` provider、Python 依赖、测试和使用文档。

**Key Actions:**

- **Provider**：新增 `OpenAIService`，通过官方 `openai` SDK 调用 Chat Completions。
- **消息转换**：支持 system/user/assistant/tool 消息、工具定义、tool calls、usage 和 provider 错误映射。
- **安全与测试**：从环境变量读取 API 配置，支持注入 fake client，新增 8 条离线 Python 测试。

### 🧠 Design Intent (Why)

OpenAI provider 只实现现有 `LLMService` 契约，避免把 SDK 类型和网络调用扩散到 Agent 执行循环。客户端注入使消息转换和错误处理可以无 key、无网络验证。

### 📁 Files Modified

- `src/agent_core/llm/openai.py`
- `src/agent_core/llm/__init__.py`
- `src/agent_core/__init__.py`
- `pyproject.toml`
- `tests/test_agent_core.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SECURITY.md`

### ✅ Verification

- **Commands or checks:** `npm run test:python`（8 tests）；`python -m compileall -q src tests`；`npm run check:docs`；`npm run check:repo`；`npm run check:actions`。
- **Known risks or follow-up:** 真实 API 调用需要执行 `python -m pip install -e .` 并配置 `OPENAI_API_KEY`；当前仍是同步 Chat Completions V0 实现。
