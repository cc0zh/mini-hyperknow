# mini-hyperknow

基于 Hyperknow 核心课程体验重建的个人简历项目，以 hyperknow-clone2 为只读规格参考。不使用 Mock、假课程、模板降级或虚假进度。

## 当前能力与边界

已实现文字目标、真实模型澄清／目录生成、SQLite 课程库及运行恢复，以及按课时生成并缓存讲义、无语音手写白板、课堂插话、位置恢复和手动完成。真实练习／单元考核本阶段范围已完成：三题型出题、逐题保存与反馈、显式提交、服务端计分、结果停留／再练及恢复。页面使用真实 API，课程、讲义、问答与出题共用一个串行 worker；证据与未覆盖项见[完成计划](docs/exec-plans/completed/20261022-real-practice-exams.md)，最终CI门禁待主代理填写。

**验收边界：已用内置浏览器与真实 deepseek-flash 验收两组造课、asyncio／摄影两课课堂，以及两组练习和一组单元考核；已保存作答与结果可刷新／冷重启恢复。** 普通板书按本地 Excalifont（英文／数字／西文标点）与小赖 Xiaolai（中文／中文标点）分工；代码保持等宽，公式使用 KaTeX 专用字体。原课堂字体配置已由后续替换任务取代，当前资源与验收见[字体参考](docs/references/whiteboard-font.md)。课时可手动完成，本阶段新增练习提交完成课时、考核提交记为完成，不表示掌握或通过。目录／课程库共用服务端进度与继续入口。思考题作答与项目提交仍未实现，不提供假执行按钮，也不宣称完整学习链路或V01–V12整体通过。摄影题目虽忠于讲义，人工核查仍发现光线方向概念待纠正，结构校验通过不等于教学全部正确，见[内容债务](docs/exec-plans/tech-debt-tracker.md)。

最终流程：文字目标 → 澄清 → 生成课程 → 课程路径 → 无语音白板与课堂问答 → 练习／考核／项目 → 保存并继续学习。不做语音、上传、知识库、独立聊天／深度学习、社区、支付或企业级权限平台。

## 本地安装

需要 uv、Python（仓库固定 3.13）、Node.js 22.12+（推荐 24）和 Git；完整仓库工具测试还使用系统 tar。Python 依赖只使用 uv 管理，前端使用 npm 和独立锁文件。

```powershell
uv sync --frozen
npm.cmd --prefix web ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本仓库本地 .env 设置 OPENAI_API_KEY，可选 OPENAI_MODEL、OPENAI_BASE_URL。不要覆盖已有配置、把密钥放入 web 或发到聊天。HK_DATA_DIR 默认 data，数据库为 data/hyperknow.sqlite3；HK_MODEL_TIMEOUT_SECONDS 默认 120。修改后端配置后重启后端。

## 启动

从仓库根目录分别在两个终端运行：

```powershell
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd --prefix web run dev
```

前端默认 `http://127.0.0.1:5173`，开发代理将 /api 和 WebSocket 转发至 8000。若 5173 已被其他项目使用，不停止未知进程，改用 npm.cmd --prefix web run dev -- --port 5174。非 Windows 平台把 npm.cmd 换为 npm。

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

脚本走真实 HTTP，默认回答每个澄清问题的第一个选项，再生成并读取课程，证据写入忽略的 data/validation/。缺配置退出码 2（blocked），失败退出码 1，不注入内容。它只验证模型／API 切片，不代替浏览器、第二组需求或重启验收。

## 设计与交接

- [设计索引](docs/design-docs/index.md)、[产品范围](docs/design-docs/product-design.md)和[架构](docs/ARCHITECTURE.md)。
- [造课计划](docs/exec-plans/completed/20261022-real-course-library.md)、[课堂计划与验收边界](docs/exec-plans/completed/20261022-real-whiteboard-classroom.md)、[练习／考核完成计划](docs/exec-plans/completed/20261022-real-practice-exams.md)、[真实验证](docs/design-docs/real-validation.md)和[质量状态](docs/QUALITY_SCORE.md)。
- [CI/CD](docs/CICD.md)、[Windows](docs/WINDOWS.md)和协作入口 [AGENTS.md](AGENTS.md)。

保留的模板制品脚本不代表部署产物，本轮不发布、不提交 Git，也不修改只读参考仓库。
