# 轻量后端评测

范围：一个单轮概念解释Case；两条普通Python流程，不是评测服务或调度平台。设计见[后端评测](../docs/design-docs/backend-evaluation-pipeline.md)，实施及真实验收见[计划](../docs/exec-plans/active/20261026-lightweight-backend-eval.md)。

## 数据Pipeline：准备与回流

[case.json](concept-explanation/case.json)是首轮输入、参考事实和三项Rubric的唯一可执行来源。要求一次解释、不向用户提问、不创建产物；Rubric不泄漏给被测Agent。

`concept-explanation`只是概念解释场景名，不选择或依赖同名Skill。Skill按需可用，默认快照为空；`skill_trace`只核对使用记录、实际`get_skills`加载和冻结快照一致，普通回复无需加载Skill。

```powershell
uv run --frozen python scripts/run_eval.py prepare
```

不调用模型。它校验并按内容哈希保存到忽略的`data/evals/cases/`。业务运行后自动将输出／轨迹引用、规则和Grader版本、判定关联到同一个Case；也可仅重收已有结果：

```powershell
uv run --frozen python scripts/run_eval.py prepare --from-result data/evals/runs/concept-001/result.json
```

同题多次执行只增加样本，显式重评保留独立grading_attempt_id；首次评分会替换同次运行的无评分占位。规则与语义均通过标good，确认失败标bad，测量证据缺失／评分故障标unresolved。自动标签带unreviewed状态，只用于开发，不生成标准答案、不自动加入留出集，也不提交原始会话到Git。

当前只收录显式提供完整Rubric的Case和本工具结果，不自动从任意线上会话生成可信新题；依赖上下文的样本不能强行裁成首轮无历史Case。

## 业务Pipeline：真实执行与判定

先在独立终端启动一个专用后端，不复用作者默认实例：

```powershell
$env:HK_DATA_DIR = "data/evals/backend-concept"
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8039
```

另一个终端执行。下例显式选择deepseek-flash，须替换为当前供应商可用且已授权的Grader模型：

```powershell
uv run --frozen python scripts/run_eval.py run --data-dir data/evals/backend-concept --output data/evals/runs/concept-001 --grader-model deepseek-flash --execute
```

此命令会收费：最多一个新教学run（沿用业务最多9次调用、360秒的本地门禁，请求每调用8192输出token），随后一次Grader请求（默认90秒、请求2048输出token）。同步在途请求不能保证远端及时停止，参数上限也不等于供应商实际执行；不自动重试、投票或修复评分JSON。数据准备／重出摘要不收费。

Grader模型由`--grader-model`或`HK_EVAL_GRADER_MODEL`明确提供，不默认选教学模型。凭据优先`HK_EVAL_GRADER_API_KEY`，否则沿用`OPENAI_API_KEY`；端点优先CLI、`HK_EVAL_GRADER_BASE_URL`、`OPENAI_BASE_URL`，最后为官方OpenAI端点。配置不完整在新增教学费用前阻塞；密钥不落盘，也不要放进命令行。

脚本在任何写请求前核对health.storage_id与指定数据库路径指纹，拒绝默认／本地.env配置的数据目录、已有课程及非本工具创建的会话。指纹用于防误连，不是认证或防恶意伪造。收集器仅以SQLite mode=ro读取，不构造会迁移数据库的业务Database。

输出目录必须位于忽略的data中或仓库外，包含：

- `result.json`：固定Case／Rubric、命令身份、业务快照与原始调用、规则、Grader请求／原始响应／分项结果和分开计量的usage。
- `trajectory.json`：固定ATIF-v1.7文字子集。无可表示调用或格式失败时不生成伪轨迹，错误仍在result中。完整性仅针对已供给记录，不能证明没有源端丢调用。

被测代码版本当前不由后端声明，结果保留unknown；ATIF agent.version明确表示实际Prompt／工具／Skill配置的内容哈希，不冒充Git提交。Grader不混入教学轨迹。首轮不使用外部网络工具、前端或课程依赖。

## 恢复、重评及摘要

等待超时不等于后端停止，不得换输出目录无意重跑。恢复仍使用原命令和run，不采用现有retry接口产生的替代run：

```powershell
uv run --frozen python scripts/run_eval.py run --data-dir data/evals/backend-concept --output data/evals/runs/concept-001 --resume --grader-model deepseek-flash --execute
uv run --frozen python scripts/run_eval.py show --output data/evals/runs/concept-001
```

提交结果未知且原回执缺失时保守阻塞，不重新POST收费请求；已知身份但数据库回滚也阻塞。已保存原始评分响应时只做本地解析；响应未知时不自动重发。原始证据已收齐时可离线重新导出与检查，不需要模型。

只有明确需要新评分时才执行下面命令，它另收一次Grader费用、不调用教学模型，并保留旧attempt：

```powershell
uv run --frozen python scripts/run_eval.py grade --output data/evals/runs/concept-001 --grader-model deepseek-flash --execute
```

单writer锁避免并发提交。进程异常退出若留下`.writer.lock`，先确认该进程不再运行再手动删除，不自动抢锁。退出码0表示完整自动检查通过（不代表教学质量保证），1为明确业务不合格或执行异常，2为阻塞、待判、评分异常或未完成。

首轮真实Grader虽请求2048，供应商报告6109 completion tokens。现有`show`会从原usage审计并显示exceeded，已确认的语义失败仍保存，但不能产生整体good或预算通过。官方api.deepseek.com现改用其文档支持的max_tokens，其余端点保持max_completion_tokens；新评分记录参数名，已生成的旧记录不追改为新协议。这个修复只经本地检查，未再次收费验证；未来预算异常也返回2，不为取得通过反复评分。

## 验证与限制

```powershell
uv run --frozen python -m unittest discover -s tests -p "test_eval*.py" -v
npm.cmd run ci
```

本地测试包含真实临时SQLite／HTTP及无凭据worker失败，不用Mock／Fake／录制响应替代真实执行。LLM是默认评分者，但同模型存在同源偏差，未校准结果保留unreviewed。首份实际评分需对照证据核查，不能用单题通过声称评分可靠或教学改善；具体本轮结果只在实施计划维护。
