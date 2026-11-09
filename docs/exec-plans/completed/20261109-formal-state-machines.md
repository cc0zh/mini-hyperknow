# 子系统形式验证技能与用户流程图

## 目标

使用 create-formal-verification-skill 为现有业务状态机建立独立项目技能。使用 statechart 检查并可视化重要用户流程。

## 范围

- 以当前工作区代码为准，覆盖共享任务生命周期、造课、调研、课堂、题组作答和即时协助六个子系统。
- 项目技能保存到 `.agents/skills/`。模型、覆盖映射和重跑入口保存在仓库中。
- 优先可视化造课、课堂和测验。即时协助保留独立图。
- 不改产品代码，不调用收费模型，不部署，不提交或创建 PR。
- 保护任务开始时已有的全部未提交改动。

## 验收

1. 每个子系统有包含 frontmatter、代码覆盖记录、同步基准和单命令检查的技能。
2. 模型原子动作对应真实事务或同步操作。区分模型检查与真实代码验证。
3. 检查明确报告边界、假设和未覆盖情况。不能用通过的小模型声称整个产品正确。
4. 每个核心性质有可失败的故障变体。至少通过真实代码的临时变更确认检查能够抓住回归，并恢复临时变更。
5. statechart 生成实际 TLC 报告与 Mermaid 图。保留可重跑命令和用户可读说明。
6. 验证技能结构、引用、相关测试及仓库文档检查。

## 进度

- [x] 已加载本机技能与执行规范，确认已有工作区改动。
- [x] 已完成代码状态机覆盖映射。
- [x] 已建立独立技能、模型与重跑工具。
- [x] 已执行基线、故障变体和真实代码验证。
- [x] 已生成并检查重要用户流程图。
- [x] 已完成文档、history 与最终检查。

## 决定

- 2026-11-09。使用有限状态模型检查事件顺序与保存屏障。模型不验证模型生成内容的事实正确性。
- 2026-11-09。当前基准提交为 `c7a05d71dce441f1ddad8c8be2651f3c3cb39450`。任务开始时工作区不干净，覆盖文件另记录内容摘要，不能将 HEAD 当作全部工作区内容。
- 2026-11-09。本机缺少 skill-creator。按 Agent Skills 格式编写并验证，不宣称已调用不存在的技能。
- 2026-11-09。工具后台任务返回空日志且没有工件，不视为执行成功。改为短批前台执行并核对实际输出。
- 2026-11-09。采用 Model the Domain，按六个真实业务边界拆分技能，不按 Python 文件数或模型调用次数拆分。
- 2026-11-09。采用 Build the Lever，保留统一检查器和固定版本 SVG 渲染器。没有自造状态 DSL 或模型检查框架。
- 2026-11-09。采用 Prove It Works，所有性质同时执行模型故障变体和隔离真实源码故障实验。修改副本，不覆盖用户工作区。
- 2026-11-09。选择 TLA+ 与 TLC，而非只画图或用自写 BFS。问题是有限状态转换和门禁；该工具可给出可达状态与最短反例，且能通过固定发行包与摘要重跑。
- 2026-11-09。statechart 对标题中的顿号产生异常编码。改用等义连接词，重新生成受影响图；未修改全局技能工具代码。

## 吞吐检查点

先建立一个可执行模型和真实失败证据，再按同一命令约定扩展其余子系统。批量检查只返回状态数、性质、最短反例与产物路径。避免人工复制检查步骤。

## 验证证据

### 工件

- 六个项目技能位于 `.agents/skills/verify-*/`，各含 SKILL、TLA+、配置、视图和独立覆盖记录。
- [使用入口](../../formal-verification/README.md)记录性质、边界、依赖与命令。
- [机器可读结果](../../formal-verification/verification-summary.json)保存本次真实检查的结果。
- [离线流程页](../../formal-verification/index.html)和[全部 Mermaid 文本](../../formal-verification/flows.md)供用户查看。
- 每个图目录同时保留基线和主动故障的 Mermaid、SVG 与 statechart 报告，共十二张 SVG。

### 已执行

1. `uv run --frozen python scripts/verify_state_machines.py --mutants --code-mutations --out data/formal-verification/20261109-verified` 退出零。
   - 六个正常模型共 295 个可达状态，各自安全性质通过。
   - 六个 `Broken = TRUE` 变体分别违反预定性质，工具错误不算成功发现反例。
   - 六处真实源代码守卫在隔离副本中分别得到 baseline=0、mutant=1、restored=0。故障均为测试断言失败，不是导入错误。
2. 按已安装 `/statechart` 执行六个正常模型与六个故障模型。正常性质及 NoDeadlock 均通过，故障模型给出最短路径。标题修正后重跑受影响图。
3. `node scripts/render_statecharts.mjs` 使用 Pele 1.9.0 成功渲染十二张 SVG，生成 HTML 和 Mermaid 汇总。
4. `uv run --frozen python -m unittest test_course test_blueprint test_research test_lesson test_lesson_structure test_quiz test_assistance_storage test_formal_verification -q` 在 tests 加入 PYTHONPATH 后运行，171 项测试通过。
5. `uv run --frozen python scripts/verify_state_machines.py --validate-only` 验证六个技能、源码摘要、符号和故障锚点通过。
6. `npm.cmd run check:docs`、`npm.cmd run check:repo` 和 `git diff --check` 通过。
7. 通过限时回环 HTTP 在真实浏览器加载最终 HTML。DOM 验收确认六个 SVG、六个正确标题、无外部资源、无页面横向溢出、无越出 SVG 边界的文字。预览服务在计时结束后关闭。

原始 TLC 和代码测试日志在 `data/formal-verification/20261109-verified/`，该目录不进入版本控制。图与可读报告保存在公开文档目录。直接 TLC 在首个违规状态停止，statechart 继续探索，所以故障模型的状态数可能不同。

### 限制

- 六个性质只覆盖各自有限模型，不证明整个产品、Python 实现的全部输入、教学质量、所有并发次序或数据库实现。
- 未调用收费模型或真实搜索，没有宣称新的产品端到端或生产验收通过。
- agent_core 与研发 eval 不是本次六个业务状态机的独立验证对象。
- 项目技能格式与文件发现路径已核对，聊天界面的 slash-command 注册与派发未验证。
- 本机缺少 skill-creator，采用 Agent Skills 格式并执行实际结构检查。
- 没有产品行为或质量结论变化，不更新 QUALITY_SCORE。没有提交、推送、部署或创建 PR。

### 归档检查

历史与学习记录直接指向 completed 路径。归档前搜索确认无其他 active 入链。长期使用规则写入形式验证入口，技能目录登记在 coding-standards 索引。
