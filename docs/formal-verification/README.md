# 检查子系统状态机

每个现有业务子系统有一个开发助手技能。TLA+ 描述有限状态与事件次序，TLC 穷举指定范围内的可达状态。原产品代码没有改动。

## 查看用户流程

打开[离线流程浏览页](index.html)，或查看[全部 Mermaid 文本和 SVG](flows.md)。优先流程为造课、白板课堂、练习与考核。独立即时协助、调研和共享任务另有各自的图。

图表合并同标签状态，没有主动删除动作。标签不变的内部步骤不画箭头。停止原因在部分图中合并显示，不代表取消、失败和重启的代码相同。造课图的重试另见共享任务图，不暗示必须从头重建已提交单元。

| 技能 | 唯一形式检查性质 | 模型边界 | 基线可达状态 |
| --- | --- | --- | --- |
| [verify-run-lifecycle](../../.agents/skills/verify-run-lifecycle/SKILL.md) | 同命令标识不能接受不同内容 | 一个原命令、两种指纹、一次重试 | 25 |
| [verify-course-flow](../../.agents/skills/verify-course-flow/SKILL.md) | 全部单元保存后才 ready | 一个课程、两个单元、一次反馈 | 31 |
| [verify-research-flow](../../.agents/skills/verify-research-flow/SKILL.md) | 每轮最多保存十个工具步骤 | 一个 run、一个调研轮次 | 170 |
| [verify-classroom-flow](../../.agents/skills/verify-classroom-flow/SKILL.md) | 确认最后总结后才能完成 | 一个脚本、三步、一个在途问题 | 18 |
| [verify-quiz-flow](../../.agents/skills/verify-quiz-flow/SKILL.md) | 全部回答或跳过后才能提交 | 一个题组、一个尝试、两题 | 12 |
| [verify-assistance-flow](../../.agents/skills/verify-assistance-flow/SKILL.md) | 一个教学轮次最多保存一个产物 | 一个会话、两次请求、最多两个候选产物 | 39 |

这些是六个产品业务边界，不等于仓库每个 Python 模块。通用 agent_core 与研发 eval 没有在本次单独形式化。六个性质不构成对所有状态机不变量的完整证明。

## 配置验证工具

需要本项目锁定的 Python 环境和 Java 11 以上。已执行环境为 Java 25.0.1。模型检查固定使用 TLA+ tools 发行包 1.7.4，其内 TLC 报告版本为 2.19。JAR 不进入仓库。

```powershell
$toolDir = Join-Path $env:LOCALAPPDATA 'hyperknow-formal-tools'
New-Item -ItemType Directory -Force $toolDir | Out-Null
$env:TLA2TOOLS = Join-Path $toolDir 'tla2tools-1.7.4.jar'
Invoke-WebRequest 'https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar' -OutFile $env:TLA2TOOLS
(Get-FileHash $env:TLA2TOOLS -Algorithm SHA256).Hash.ToLower()
```

摘要必须为 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`。检查入口会再次验证，拒绝不同版本或损坏文件。已有正确 JAR 时只设置 `TLA2TOOLS`，不要重复下载。

## 执行检查

从仓库根目录运行。

```powershell
uv run --frozen python scripts/verify_state_machines.py --mutants --code-mutations
```

命令创建新的临时输出目录，并打印路径。需要固定目录时，用 `--out` 指定尚不存在的目录。用 `--system course-flow` 只检查一个子系统。用 `--validate-only` 检查技能格式、代码摘要、覆盖符号和故障锚点。

每个子系统的检查依次执行以下步骤。

1. 检查已记录代码摘要。漂移时停止，要求重新核对模型，不自动更新摘要。
2. 检查正常模型。TLC 必须穷举完成，不能把退出码零但缺少完成标记当成成功。
3. 将模型的 `Broken` 设为 TRUE。必须违反预定性质，解析错误和工具崩溃不算成功发现反例。
4. 把当前 src 和 tests 复制到隔离临时目录。运行原测试，通过后修改真实源代码守卫。测试必须出现断言失败而不是导入错误。恢复隔离副本后再次通过。

源代码故障实验不会覆盖工作区文件，也不读取本地 .env，不调用收费模型。代码测试是回归见证，不是对 Python 实现的形式证明。完整命令退出码零表示全部预期结果符合要求，其中主动故障必然产生预期失败。

## 重新生成图表

模型检查结果必须使用当前安装版本的 `/statechart` 阅读。该技能的执行入口不硬编码到项目技能或脚本中。

按本机 `/statechart` 规则设置 `STATECHART_ENTRY` 后，可用以下命令重建一个图。输入复制到仓库外临时目录，输出目录必须是新的。

```powershell
$id = 'course-flow'
$skill = Join-Path (Get-Location) ".agents/skills/verify-$id"
$coverage = Get-Content -Raw "$skill/references/coverage.json" | ConvertFrom-Json
$scratch = Join-Path $env:TEMP ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $scratch | Out-Null
Copy-Item "$skill/assets/*" $scratch
node $env:STATECHART_ENTRY "$scratch/$(Split-Path $coverage.spec -Leaf)" --config "$scratch/$(Split-Path $coverage.config -Leaf)" --view "$scratch/view.mjs" --out "$scratch/chart-output"
```

将实际生成的 `chart.mmd` 和 `report.md` 放到 `charts/<id>/`。将 `Broken = TRUE` 的独立配置生成结果放到 `charts/<id>/mutation/`。故障图是门禁有效性的见证，不代表当前产品存在该故障。

SVG 固定使用 `/statechart` 指定的 Pele 1.9.0，在仓库外安装。

```powershell
$env:PELE_ROOT = Join-Path $env:LOCALAPPDATA 'hyperknow-formal-tools/pele'
npm.cmd install --prefix $env:PELE_ROOT --ignore-scripts --no-audit --no-fund --save-exact pele@1.9.0
node scripts/render_statecharts.mjs
```

渲染器写出所有基线与故障 SVG、离线 HTML 和完整 Mermaid 文本。渲染失败不会退回手绘替代图。

## 阅读故障见证

当前六个正常模型均通过相应性质与死锁检查。下表中的失败由主动修改守卫产生。

| 故障 | 违反的规则 | statechart 最短路径 |
| --- | --- | --- |
| 关闭命令指纹冲突检查 | `NoConflictingReplay`，相同标识不得接受不同内容 | [步骤 0 到 2](charts/run-lifecycle/mutation/report.md)，提交后改内容重发 |
| 把全部单元就绪改为任一单元就绪 | `ReadyRequiresAllUnits`，课程不得过早 ready | [步骤 0 到 7](charts/course-flow/mutation/report.md)，只提交第一个单元 |
| 允许第十一步工具结果保存 | `ToolBudgetRespected`，每轮不得超过十步 | [步骤 0 到 12](charts/research-flow/mutation/report.md)，开始后执行十一次工具步骤 |
| 移除最后总结门禁 | `CompletionRequiresSummary`，未确认总结不得完成 | [步骤 0 到 4](charts/classroom-flow/mutation/report.md)，讲义刚保存就完成 |
| 移除全部作答门禁 | `SubmissionRequiresAllAnswers`，未答完不得提交 | [步骤 0 到 5](charts/quiz-flow/mutation/report.md)，刚开始就提交 |
| 允许一轮保存两个产物 | `AtMostOneArtifactPerTurn`，一轮最多一个产物 | [步骤 0 到 4](charts/assistance-flow/mutation/report.md)，双产物候选被提交 |

最短路径长度来自 statechart 以单 worker 执行的广度优先检查。正常模型不检查公平性或最终一定成功，允许用户不操作或网络长期无返回。

## 维护范围

覆盖记录保存基准提交、当前工作区是否有未提交内容、源文件 SHA256 和符号。初次核对基准为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`，不能用该 HEAD 代替当时脏工作区内容。

用 `/maintain-formal-verification-skill` 复核变动。确认动作仍对应真实事务、性质没有被削弱、故障注入仍能失败后，才推进同步提交和摘要。项目技能格式已静态验证，不宣称聊天界面的 slash-command 注册和派发已验证。

不覆盖模型生成内容的事实正确性、教学收益、所有并发执行顺序、数据库实现正确性、生产性能或部署环境。各技能另列局部假设。
