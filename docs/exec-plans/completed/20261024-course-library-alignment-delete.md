# 课程卡片对齐与安全删除

## 目标、范围与风险

- 目标：同排课程封面、标题区、进度、票根及操作区对齐；长文本不挤出布局；提供真实课程删除与明确二次确认。
- 包含：课程库卡片布局、删除弹窗、API／事务与隔离测试、浏览器验收截图。
- 不包含：封面换色、字体处理、批量删除或回收站。
- 风险：删除不可逆、活动任务晚到结果、响应丢失重试。通过命令幂等、版本检查、运行状态门禁、事务清理及明确影响说明控制风险。
- 授权：实施本地功能及测试；不删除现有用户数据，不触发收费生成。破坏性测试仅在独立临时数据库运行。
- 关联：[接口](../../design-docs/api-and-events.md)、[数据模型](../../design-docs/data-model.md)。

## 进度与决定

- [x] 定位：自然高度卡片、不同标题／帮助文字行数、卡外继续按钮导致错位；当前无课程删除端点。
- [x] 统一卡片分区，动作移入卡内，按钮不嵌入链接。
- [x] 删除命令与事务、关联数据清理、拒绝活动生成、幂等及真实隔离测试。
- [x] 二次确认弹窗，取消优先聚焦，待确认重试、冲突和错误反馈。
- [x] 构建、测试、真实浏览器验证及截图。
- 2026-10-24：沿用 POST 命令风格，实现 `POST /api/courses/{course_id}/delete`，携带 client_command_id 与 expected_version。保留命令回执而非课程内容，旧创建命令重放返回 404，删除命令相同输入重试返回成功。
- 卡片改为 article，主体链接与底部继续／删除按钮独立；预留标题、简介和进度说明高度。短进度说明仍明确不代表掌握度。颜色及字体不变。
- 删除结果未知时保留完整命令，禁止开始其他删除；允许关闭弹窗但文案为“稍后确认”，明确关闭不会撤销请求。刷新后从课程库恢复面板显式重试。过期版本、活动任务或输入拒绝要求刷新重新确认，不自动修改版本重发。
- 审查修复：旧页面回包只可清理自身命令，不能清除后来页面的新命令；成功删除后的焦点在弹窗关闭后移至持久标题，取消时回到原按钮。

## 关键文件

- `web/src/components/ui.tsx`、`web/src/styles/app.css`、`web/src/styles/quiz.css`：卡片分区与对齐。
- `web/src/components/CourseDeleteDialog.tsx`、`web/src/pages/Courses.tsx`：确认、错误、恢复和焦点。
- `web/src/lib/commands.ts`、`web/src/lib/use-command.ts`、`web/src/lib/api.ts`：命令所有权及明确的 404 拒绝。
- `src/hyperknow/main.py`、`src/hyperknow/runtime.py`、`src/hyperknow/storage.py`：端点、提交通知、事务清理及迟到写入保护。
- `tests/test_course_deletion.py`、`web/tests/course-deletion-command.test.ts`、`web/e2e/course-library.spec.ts`：隔离数据库、真实 HTTP、纯命令和只读浏览器回归。

## 验收与交接

- `npm run ci`：退出 0，252 项 Python、21 项仓库 Node 检查及文档／仓库门禁通过。其中新增 10 项删除测试，覆盖关联数据隔离、版本、活动状态、重放、重新打开、事务回滚和并发，以及真实 Uvicorn HTTP。
- `npm --prefix web test`：72 项通过；TypeScript 与 `npm --prefix web run build` 通过。仍有既有大型 Mermaid／ELK chunk 警告，不在本次范围拆包。
- `npm --prefix web run test:browser`：12 项中 8 通过、4 跳过。跳过因现有数据无对应课程状态、模型配置状态或真实生成需要 opt-in；未触发收费生成。
- 新增只读浏览器用真实 API 数据在 1440／1024／768／390／320px 检查无水平溢出，同排标题、进度、票根、操作区及卡高差不超过 1px；检查无按钮嵌套链接、弹窗取消与焦点恢复，无写请求及 pageerror。
- 额外破坏性浏览器验收：SQLite 只读 backup 复制现有数据库到系统临时目录，用独立 8016 回环 Uvicorn 服务和本次构建静态文件；Settings 显式不含模型／搜索密钥，不拦截 API。实际删除两门副本课程，验证 404、列表消失、刷新持久化、同命令成功回放；浏览器真实离线后刷新恢复待确认请求，再上线按完全相同路径／版本／命令 ID 重试成功。默认用户课程完整快照前后相同。
- 截图保存在本地忽略目录 `data/shots/course-library/`：`gallery.png`、`desktop.png`、`mobile.png`、`dark.png`、`delete-confirm.png`、`delete-confirm-mobile.png`、`delete-recovery.png`、`after-delete-isolated-copy.png`；`acceptance.json` 保存副本验收结论，无浏览器 pageerror。
- 独立只读审查发现的未知结果措辞与成功焦点时序已修正并补验。不向默认用户数据库发送删除或造课请求，未提交、未部署。
- 收尾：隔离服务已停止，临时数据库副本已清理。默认开发后端原进程不自动重载；确认没有 queued／clarifying／generating 请求后按原启动参数重启，health=ok，OpenAPI 包含删除端点，重启前后完整课程快照一致，原有三门课程保留。
- 边界：删除没有回收站；SQLite 记录删除不是磁盘安全擦除；必要幂等回执保留。课程外独立调研、其他课程及字体资源不受影响。未宣称新增付费生成或教学内容准确性验收。
