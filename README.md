# mini-hyperknow

基于 Hyperknow 核心课程体验重建的个人简历项目，以 hyperknow-clone2 为只读规格参考。不使用 Mock、假课程、模板降级或虚假进度。

**适配范围：仅桌面浏览器。** 不再维护移动端／平板专用适配或手机视口验收；已有响应式布局只作为桌面窗口缩放降级保留，不代表移动支持承诺。范围变更不追改历史测试结果。

## 当前能力与边界

2026-10-23新增[调研→全局蓝图确认→逐单元展开](docs/exec-plans/completed/20261023-course-blueprint-workflow.md)，已用一个真实asyncio主题验通调整、确认、局部取消／重试及等待／完成状态冷重启；不要求旧课兼容，不清空用户库。内容核查限制见完成计划，不据此宣称完整产品验收。

已实现文字目标、真实模型澄清／目录生成、SQLite 课程库及运行恢复，以及按课时生成并缓存讲义、无语音手写白板、课堂插话、位置恢复和手动完成。真实练习／单元考核本阶段范围已完成：三题型出题、逐题保存与反馈、显式提交、服务端计分、结果停留／再练及恢复。页面使用真实 API，课程、讲义、问答与出题共用一个串行 worker；证据与未覆盖项见[完成计划](docs/exec-plans/completed/20261022-real-practice-exams.md)，最终CI门禁待主代理填写。

**验收边界：已用内置浏览器与真实 deepseek-flash 验收两组造课、asyncio／摄影两课课堂，以及两组练习和一组单元考核；已保存作答与结果可刷新／冷重启恢复。** 普通板书按本地 Excalifont（英文／数字／西文标点）与小赖 Xiaolai（中文／中文标点）分工；代码保持等宽，公式使用 KaTeX 专用字体。原课堂字体配置已由后续替换任务取代，当前资源与验收见[字体参考](docs/references/whiteboard-font.md)。课时可手动完成，本阶段新增练习提交完成课时、考核提交记为完成，不表示掌握或通过。目录／课程库共用服务端进度与继续入口。思考题作答与项目提交仍未实现，不提供假执行按钮，也不宣称完整学习链路或V01–V12整体通过。摄影题目虽忠于讲义，人工核查仍发现光线方向概念待纠正，结构校验通过不等于教学全部正确，见[内容债务](docs/exec-plans/tech-debt-tracker.md)。

创建流程：文字目标 → 按需澄清（信息充分可无问题） → 真实网页调研 → 全局蓝图确认一次 → 自动逐单元展开 → 课程路径 → 按需讲义与白板课堂。练习／考核已有真实结果；项目只生成阶段要求，成果提交仍暂缓。不做语音、上传、知识库、独立深度学习、社区、支付或企业级权限平台。

2026-10-24起新增与造课并列的[即时协助](docs/design-docs/instant-assistance.md)：`/assistance`独立会话，基本教学直接执行，专门Skill保留按需加载能力，当前无内置Skill，支持澄清、继续、闪卡、轻量选择题、独立文字白板、结构图和自包含HTML动画。产物种类由模型按教学内容判断，不是学习者要选的操作；点名的产物仍必须产出，明确拒绝的不得产出，每轮最多一个产物。无课程归属、资料、搜索／RAG或长期记忆；只需模型配置，不要求Tavily。生成内容保存到SQLite，闪卡浏览／测验选择／动画运行状态不持久化，白板位置保存且恢复暂停。动画为不可信宿主隔离预览，不是严格网络或CPU／内存沙箱。真实验收与内容限制见[完成计划](docs/exec-plans/completed/20261024-instant-assistance.md)，产物选择与感知层补强见[后续计划](docs/exec-plans/completed/20261024-instant-assistance-perception.md)。

## 本地安装

需要 uv、Python（仓库固定 3.13）、Node.js 22.12+（推荐 24）和 Git；完整仓库工具测试还使用系统 tar。Python 依赖只使用 uv 管理，前端使用 npm 和独立锁文件。

```powershell
uv sync --frozen
npm.cmd --prefix web ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本仓库本地.env设置OPENAI_API_KEY及造课调研必需的TAVILY_API_KEY，可选OPENAI_MODEL、OPENAI_BASE_URL。不要覆盖已有配置、把密钥放入web或发到聊天。HK_DATA_DIR默认data，数据库为data/hyperknow.sqlite3；HK_MODEL_TIMEOUT_SECONDS默认120。修改配置后重启后端。

## 启动

从仓库根目录分别在两个终端运行：

```powershell
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd --prefix web run dev
```

前端默认 `http://127.0.0.1:5173`，开发代理将 /api 和 WebSocket 转发至 8000。若 5173 已被其他项目使用，不停止未知进程，改用 npm.cmd --prefix web run dev -- --port 5174。非 Windows 平台把 npm.cmd 换为 npm。

独立验收后端使用其他端口时，可在启动前端的终端设置`HYPERKNOW_API_ORIGIN=http://127.0.0.1:8037`，只改变Vite开发代理；不要将真实模型地址或凭据配置给浏览器。

GET /api/health 区分数据库正常、模型已配置与尚未验证；不会因检测到密钥就宣称连通。缺配置时创建返回明确错误，不生成假课程。重启把在途任务标为 interrupted；读取已保存讲义不收费，恢复播放器默认暂停，失败／取消／中断只显式重试。

数据库本阶段升为 v3：首次打开旧 v1／v2 库先自动 SQLite backup 再事务迁移，不清空旧课程；额外迁移前备份说明见[数据模型](docs/design-docs/data-model.md)。两款白板字体使用未修改的官方资源，均以 OFL 1.1 授权，随资源保留各自版权及完整许可证；来源、版本与资源核验见[字体参考](docs/references/whiteboard-font.md)。本阶段不发布。

## 验证

```powershell
npm.cmd run ci
npm.cmd --prefix web test
npm.cmd run build
```

这些入口已移除历史 Mock／Fake／patch。检查包括真实文件、纯逻辑、临时磁盘 SQLite 和实际 Uvicorn HTTP／WS；公共 CI 不冒充真实模型验收。

配置真实模型、启动后端后，可显式执行以下验收命令；它会产生实际模型费用：

```powershell
uv run --frozen python scripts/verify_model.py
```

即时协助有独立的付费验收入口：先将`HK_DATA_DIR`设为独立验收目录并在8037端口启动后端，再运行`uv run --frozen python scripts/verify_assistance.py --execute`。它验证独立教学、多轮继续和五种真实产物（含结构图），不要求加载Skill，产物断言使用自然语言而不是操作枚举，不接入搜索；可加`--resume`读取上次保存的run ID，重启验收脚本不重复创建已有轮次。证据默认写入忽略的`data/verification/instant-assistance/`；这不是普通CI命令。

概念解释另有[轻量评测入口](evals/README.md)：数据Pipeline准备Case／Rubric，业务Pipeline执行真实HTTP、导出固定ATIF-v1.7、进行规则＋单次LLM评分，并自动关联开发库样本。`uv run --frozen python scripts/run_eval.py prepare`不调用模型；`run`／`grade`必须显式`--execute`并指定Grader模型。运行前校验独立后端存储指纹，不使用作者默认数据；`show`只读结果，恢复和重评不重跑原教学。教学与Grader费用分开，自动标签不是黄金答案，真实验收与限制见[实施计划](docs/exec-plans/active/20261026-lightweight-backend-eval.md)。

当前造课分为澄清、网页调研、全局蓝图、确认后逐单元展开，需同时配置本地 `TAVILY_API_KEY`。上述脚本默认停在蓝图等待确认；明确自动验收时使用 `uv run --frozen python scripts/verify_model.py --approve-blueprint`，否则在创建页审阅后点击确认。不要求旧课兼容，不主动清空已有本地数据；契约及当前验收边界见[蓝图工作流](docs/design-docs/course-blueprint-workflow.md)。

脚本走真实HTTP，默认回答每题首选项，完成真实研究后停在蓝图；只有显式--approve-blueprint才确认并连续展开。可加--data-dir指定本次后端数据目录，额外核对model_calls实际收到研究报告／摘录及预算。证据写入忽略的data/validation/；缺配置或等待确认退出2，实际失败退出1。只验证模型／API切片，不代替浏览器、第二组需求或重启验收。

## 设计与交接

独立网页调研Agent提供后端`POST /api/research-runs`，复用串行worker与SQLite，支持真实Tavily搜索、公开网页阅读、来源报告和取消／重试／恢复；造课接入与前端展示由[蓝图工作流](docs/design-docs/course-blueprint-workflow.md)承接。显式运行`uv run --frozen python scripts/verify_research.py`仅验证独立搜索＋模型，会产生费用；缺配置退出2。独立验收边界见[调研契约](docs/design-docs/web-research-agent.md)，不能替代新造课链路验收。

通用 Python 内核已升级 V1：工具调度／逐次审批、有界输出与原文存档、显式工作区工具、JSONL 会话恢复、调用者维护的长期记忆、Token 预算压缩和 high／medium／low 模型分层。课程业务仍沿用 SQLite 与既有同步生成，不向浏览器开放文件／命令工具；同步网络取消不等于远端中止。接口、配置与安全边界见[内核 V1](docs/design-docs/agent-core-v1.md)。

可显式执行 `uv run --frozen python scripts/verify_agent_v1.py` 验证真实模型工具循环、实际摘要及会话重开；会产生费用，证据保存在忽略的 `data/validation/agent-v1/`，不接触课程数据库。缺凭据返回 2，不冒充通过。

- [设计索引](docs/design-docs/index.md)、[产品范围](docs/design-docs/product-design.md)和[架构](docs/ARCHITECTURE.md)。
- [造课计划](docs/exec-plans/completed/20261022-real-course-library.md)、[课堂计划与验收边界](docs/exec-plans/completed/20261022-real-whiteboard-classroom.md)、[练习／考核完成计划](docs/exec-plans/completed/20261022-real-practice-exams.md)、[真实验证](docs/design-docs/real-validation.md)和[质量状态](docs/QUALITY_SCORE.md)。
- [CI/CD](docs/CICD.md)、[Windows](docs/WINDOWS.md)和协作入口 [AGENTS.md](AGENTS.md)。

保留的模板制品脚本不代表部署产物；不修改只读参考仓库。调研与蓝图阶段按用户授权分别提交，验收与边界见各自计划，本轮不发布。
