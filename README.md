# mini-hyperknow

面向 Agent-first 开发的基础模板，当前包含一个 Python Agent V0 内核和 OpenAI provider。

## Python Agent V0

内核位于 `src/agent_core/`，由四个可替换模块组成：内存上下文、LLM 服务协议、工具管理器和 Agent 执行循环。LLM 服务只需要实现 `complete(context) -> AssistantMessage`，因此可以先用 `MockLLMService` 验证工具调用链路，再使用 `OpenAIService` 接入 OpenAI 或 OpenAI-compatible endpoint。

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_agent_core.py" -v
```

使用 OpenAI：先复制示例配置并填写模型凭据。`.env` 已被 Git 忽略，不要提交真实密钥。

```powershell
Copy-Item .env.example .env
```

在 `.env` 中设置 `OPENAI_API_KEY` 和可选的 `OPENAI_MODEL`；OpenAI-compatible 服务还可设置 `OPENAI_BASE_URL`。显式构造参数优先于进程环境变量，进程环境变量优先于 `.env`，最后才使用默认模型名。

```python
from agent_core import Agent, OpenAIService, ToolManager
from agent_core.tools.read_file import read_file_tool

llm = OpenAIService()
agent = Agent(llm, tools=ToolManager([read_file_tool]))
result = agent.run("Read README.md and summarize it.")
print(result.response.content)
```

安装 Python 依赖（包含 OpenAI SDK 和 `.env` 加载器）：

```powershell
python -m pip install -e .
```

V0 有意保持简单：会话只保存在内存中，工具按顺序执行，工具输出做硬截断；持久化、上下文压缩、权限审批和调度属于后续 V1 范围。

## 开发准备

仓库工具需要 Node.js 22+、Git；完整测试与打包还需要 tar，无需安装 npm 依赖。

```powershell
npm.cmd run ci
npm.cmd run release-package
```

macOS/Linux 使用 `npm`。Windows 环境问题见 [使用说明](docs/WINDOWS.md)。

## 项目约定

- 从 [AGENTS.md](AGENTS.md) 查阅相关规则。
- 补齐 [架构](docs/ARCHITECTURE.md)、[产品目标](docs/PRODUCT_SENSE.md) 和 CODEOWNERS。
- 将模板检查与打包流程替换或扩展为实际业务流程，见 [CI/CD](docs/CICD.md)。
- 新增的计划、history 和学习记录只记本项目的事实。
