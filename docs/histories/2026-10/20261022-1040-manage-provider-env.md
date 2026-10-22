## [2026-10-22 10:40] | Task: 使用 .env 管理 provider 配置

### 🤖 Execution Context

- **Agent ID**: `codex`
- **Base Model**: `GPT-5`
- **Runtime**: `pi`

### 📥 User Query

> 使用 env 管理 OpenAI 配置。

### 🛠 Changes Overview

**Scope:** OpenAI provider 配置、Python 依赖、模板分发和使用文档。

**Key Actions:**

- **配置加载**：使用 `python-dotenv` 从项目根目录 `.env` 加载 API key、model 和可选 base URL。
- **配置优先级**：构造参数 > 已有进程环境变量 > `.env` > 默认值。
- **密钥保护**：增加可分发的 `.env.example`，保持 `.env` 忽略规则，并测试初始化不复制真实配置。

### 🧠 Design Intent (Why)

开发凭据应与代码分离，同时部署环境仍可通过平台环境变量注入。`load_dotenv(override=False)` 让本地 `.env` 易用且不会覆盖部署环境已经设置的变量。

### 📁 Files Modified

- `src/agent_core/llm/openai.py`
- `pyproject.toml`
- `.env.example`
- `scripts/lib/scaffold.cjs`
- `tests/test_agent_core.py`
- `tests/tooling.test.cjs`
- `README.md`
- `docs/ARCHITECTURE.md`

### ✅ Verification

- **Commands or checks:** `npm run test:python`（10 tests）；`npm run check:docs`；`npm run check:repo`；`npm run check:actions`。
- **Known risks or follow-up:** `.env` 从进程当前工作目录读取，启动 Agent 时应从项目根目录运行。
