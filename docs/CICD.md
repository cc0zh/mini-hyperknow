# CI/CD 说明

## 当前业务检查

Python 包由 uv.lock 锁定，统一 uv sync／uv run；前端使用 web/package-lock.json。2026-10-22 首个切片已移除 Mock provider、SDK 注入替身和 Mock／patch 测试入口。

从根目录执行：

```powershell
uv sync --frozen
npm.cmd --prefix web ci
npm.cmd run ci
npm.cmd --prefix web test
npm.cmd run build
```

npm run ci 执行文档／仓库／Action 检查、Node 工具检查与真实 Python 函数、磁盘 SQLite、实际 Uvicorn HTTP／WS 检查。HTTP 测试刻意清空自身子进程的模型密钥，只验证缺配置的真实错误路径，不以假响应或 TestClient 替代服务器，也不修改作者数据库。

ci.yml 在 Windows、Ubuntu、macOS 使用 Python 3.13、固定 uv 0.8.13 和 frozen 依赖运行检查，并构建和测试前端；Markdown lint 在 Ubuntu 执行。Actions 仍固定 commit SHA，本轮不新增企业治理平台。

## 真实模型与浏览器

公共 CI 无凭据，只能证明静态／本地检查通过。真实模型、浏览器成功课程和重启恢复单独按[真实验收](design-docs/real-validation.md)执行并报告，未执行或 blocked 不能写成通过。

显式执行 uv run --frozen python scripts/verify_model.py 将通过运行中的真实后端产生收费调用；缺配置返回 blocked（退出码 2），无课程模板降级。它保存切片证据，不覆盖全部 V01–V12。

## 保留的模板工具

create-project.cjs 与 release-package.cjs 仍保留，不是产品部署流程。分发清单已包含业务代码、前端、uv.lock 与 .python-version；排除本地数据、环境凭据、缓存和依赖目录。被保留文档链接的历史／计划一并保留，避免精简后出现断链；未引用的维护记录仍排除。

npm run release-package 生成 repo-metadata.tgz 和 release-manifest.json，而不是前端生产托管／可安装产品。原 release.yml、供应链与 provenance 流程暂存，本轮未运行发布、外部写入或部署。今后发布需先确定实际产品包装，不把 metadata 打包成功当成交付。
