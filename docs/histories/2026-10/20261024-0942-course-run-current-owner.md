# 2026-10-24 09:42 | 修复重试成功后仍显示旧失败状态

## 执行上下文

- Runtime：pi coding harness；模型标识未提供，不推测。

## 用户诉求

课程已生成完成，但旧生成链接和外层课程库仍显示生成失败，需要手动点击最新生成状态。

## 改动与原因

- 运行是一次尝试，课程是跨尝试持久保存的对象，两者状态不能混为一谈。真实问题课程已保存 8 单元、36 小节，原运行 failed、重试运行 ready，课程 `creation_run_id` 正确；无需修改数据库。
- `web/src/lib/run-state.ts` 增加当前课程拥有者判断与待处理记录筛选。用课程身份和重试祖先链排除已被替代的失败，保留未完成的最新任务、尚无课程的失败与无关同名目标；课程／运行读取交错时保留已知后代。
- `web/src/pages/CourseRun.tsx` 将普通旧链接 replace 到当前拥有者；显式 `?history=1` 保留历史入口并标注身份。待确认命令优先处理，不自动跳走；旧拥有者没有重新生成／停止入口。
- `web/src/pages/Courses.tsx` 不再把所有未 ready 历史记录都当作待恢复的课程。
- 新增 `web/e2e/run-recovery.spec.ts` 和 6 项纯状态回归；既有 service／workbench 浏览器断言同步区分当前与历史。长期语义同步到 `docs/design-docs/learning-experience.md`。

## 验证

- 先运行新真实浏览器回归，确认旧链接停在失败运行，没有自动解析到当前任务；纯状态测试先因缺少实现失败。
- 前端 78 项单测、TypeScript 和 Vite 构建通过；保留既有大型 Mermaid／ELK chunk 警告。
- 使用用户提供的 5181 真实服务全量 Playwright：13 项中 10 通过、3 跳过；跳过为不存在的待确认蓝图状态、非缺配置服务及需显式 opt-in 的收费生成。
- 新回归实际验证旧链接自动转到正确 ready 运行、刷新保持、显示开始学习、无重试按钮、历史可追溯、课程库不再显示旧失败，无写 API 请求与 pageerror。旧记录仍返回原始状态。
- 本地截图：`data/shots/run-recovery/recovered-ready-workbench.png`、`data/shots/run-recovery/current-course-library.png`（忽略目录，不提交用户课程截图）。
- 未重新生成、删除或篡改课程；未调用付费模型；未提交、未部署。保留工作区前一任务改动。
