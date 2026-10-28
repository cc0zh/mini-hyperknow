# 后端评测

## 唯一入口

日常只打开 `data/evals/index.html`，或某次输出目录内的 `report.html`。新 Trial 的原始结果和轨迹自动收进 `details/`；旧目录不强制迁移。布局与常用命令见[单目录说明](general/README.md#日常只看一个文件)。

统一使用 `scripts/run_eval.py` 的通用命令；详细配置与完整示例见[通用评测说明](general/README.md)，方法和边界见[评测设计](../docs/design-docs/backend-evaluation-pipeline.md)。

| 想做什么 | 命令 | 模型调用 |
| --- | --- | --- |
| 校验／发布题目 | validate／publish | 无 |
| 显式迁移旧Case | migrate | 无，不迁移历史执行结果 |
| 固定试卷／安排实验 | benchmark／experiment | 无，只准备资产与计划 |
| 导出真实前置材料清单 | fixture | 无，只读已隔离数据 |
| 实际执行／恢复原任务 | execute／resume | 可能收费，需明确授权 |
| 对原证据重新评分 | regrade | 涉及模型时收费，不重跑教学 |
| 查看／比较／整理报告目录 | report／compare／review | 无，只读取已保存结果 |

```powershell
uv run --frozen python scripts/run_eval.py --help
uv run --frozen python scripts/run_eval.py validate --case evals/general/concept-chain-rule/case.json
```

## 隔离后端

在独立终端启动专用后端，不复用作者默认实例：

```powershell
$env:HK_DATA_DIR = "data/evals/runs/trial-001/details/backend"
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8039
```

只在启动隔离后端的终端设置这个 HK_DATA_DIR；执行测评 CLI 的终端保留作者原配置，不要把它设成同一隔离目录，以免触发作者目录保护。execute不是服务启动器。执行与恢复需要`--execute`；先核对后端与资源身份，有LLM检查时先校验Grader配置。密钥仅由既有本地环境注入，不写入命令、资产或结果。前置材料不足时明确blocked，不自动建课或换题。

教学、准备和评分用量分别记录。已发送但结果未知的请求不自动重发，超时不表示远端已停止，不保证硬费用封顶。详细执行、fixture和预算边界见[通用说明](general/README.md)。

## 历史记录

旧命令`prepare/run/grade/show`及其专用执行、评分和样本写入实现已移除；不保留隐式别名。旧Case源文件保留，可用migrate显式生成新版Case；已有新版概念解释任务位于`general/concept-chain-rule/case.json`。

旧回答、评分、轨迹、用量与真实验收目录原样保留。schema-v1结果通过同一入口只读查看：

```powershell
uv run --frozen python scripts/run_eval.py report --result data/evals/acceptance-20261026-1203/run
```

历史读取输出JSON，标记`legacy_read_only`，保留原评分状态与预算事实；不请求后端或模型、不重解析在途评分、不写回原文件、不自动收录v2报告目录。不能对旧结果resume、regrade、compare、绑定新版experiment或转换新版HTML；已有HTML快照仍可直接打开。新评测使用固定新版Case新建Trial，不把旧回答当新执行。

历史事实见[首切片记录](../docs/exec-plans/active/20261026-lightweight-backend-eval.md)，清理范围与验证见[命令收敛计划](../docs/exec-plans/completed/20261027-evaluation-cli-consolidation.md)。

## 验证与限制

```powershell
uv run --frozen python -m unittest discover -s tests -p "test_eval*.py" -v
npm.cmd run ci
```

当前Case仍是development／uncalibrated。工程检查通过、真实模型内容合格、浏览器交互和真人学习效果是不同事实；不因统一命令宣称这些验收已完成。

2026-10-27已执行[三任务基线与候选对照](../docs/exec-plans/completed/20261027-evaluation-small-loop.md)。候选虽自动3项通过，仍因助手复核发现数学错误而拒绝；原评分与预算异常保留。应先用真实反例校准Grader，不把自动通过当作版本接受或真人学习改善。
