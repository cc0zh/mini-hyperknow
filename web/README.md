# Hyperknow Web · 第一切片

桌面中文、单用户 React + TypeScript + Vite 前端。仅实现首页、课程创建与澄清、我的课程、课程目录总览；不提供未实现的学习活动入口。

## 本地运行

在仓库根目录启动真实后端（`127.0.0.1:8000`）后：

```powershell
cd web
npm.cmd ci
npm.cmd run dev
```

打开 `http://127.0.0.1:5173`。Vite 将 `/api`（含 WebSocket）代理给后端。模型与密钥只在后端配置，不使用任何前端环境变量保存密钥。

## 验证

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

启动真实后端后，`npm.cmd run test:browser` 使用本机 Edge（非 Windows 默认 Chromium）验证首页／课程库、无模型的真实 503 和跨刷新命令编号复用、资源不存在的真实错误。非 Windows 可先执行 `npx playwright install chromium`。这些测试不创建假课程、不模拟 HTTP 或模型；模型已配置时，仅“不配置模型”专属场景明确跳过，不能作为成功造课验收。

若默认端口被其他项目占用，验证可设置 `$env:HYPERKNOW_WEB_PORT='5174'` 后运行浏览器测试，不改变默认 Vite 端口 5173。测试截图保存在被 Git 忽略的 `test-results/`。

测试只验证纯状态逻辑：澄清选择、版本单调合并、命令身份与请求内容复用。没有 Mock API、录制响应、示例课程，也不以纯函数测试代替真实模型验收。

## 恢复与错误

- `/course-runs/:runId` 先等待 WS 订阅确认，再读取 Run 快照；断线重连重复此过程。通知仅触发读取，旧版本不会覆盖新快照。
- WS 不可用或消息遗漏时，以真实 GET 定期补充同步，不制造阶段百分比或 Token 数。
- `/courses` 同时读取已保存课程与最近 30 条运行里的未就绪记录，可重新打开澄清／中断等运行。
- 写命令在 `sessionStorage` 保存相同 body 与 `client_command_id`；失败时锁住编辑，手动重试相同命令。明确的 HTTP 409 允许重新同步后重新操作。
- 无模型、网络或服务错误直接呈现，不降级成伪课程。真实成功生成、澄清、取消、重试和刷新恢复仍需可用后端模型验证。
