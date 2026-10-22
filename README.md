# mini-hyperknow

基于 Hyperknow 核心课程体验重建的个人简历项目，以 hyperknow-clone2 为只读规格参考。不使用 Mock、假课程、模板降级或虚假进度。

## 当前能力与边界

首个切片已实现：文字目标、真实模型澄清与目录生成的接线、课程 schema 校验、SQLite 保存、课程运行恢复、取消／手动重试，以及首页、创建／澄清、我的课程和课程总览。模型调用使用已有 Python provider，后端默认串行执行。

**验收边界：已用内置浏览器和真实 deepseek-flash 完成两组澄清／造课、目录浏览、刷新、取消／重试和课程冷重启恢复。** 这只代表首个造课／课程库切片，不是完整学习链路通过。课堂白板、问答、练习／考核执行、项目提交和学习进度尚未实现；目录不提供假学习按钮。

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

GET /api/health 区分数据库正常、模型已配置与尚未验证；不会因检测到密钥就宣称连通。缺配置时创建返回明确错误，不生成假课程。运行历史可在“我的课程”继续；重启把在途任务标为 interrupted，等待澄清与已保存课程保留，不自动重新收费。

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
- [实施计划与验收边界](docs/exec-plans/completed/20261022-real-course-library.md)、[真实验证](docs/design-docs/real-validation.md)和[质量状态](docs/QUALITY_SCORE.md)。
- [CI/CD](docs/CICD.md)、[Windows](docs/WINDOWS.md)和协作入口 [AGENTS.md](AGENTS.md)。

保留的模板制品脚本不代表部署产物，本轮不发布、不提交 Git，也不修改只读参考仓库。
