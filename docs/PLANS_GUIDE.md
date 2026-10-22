# Execution Plan 使用说明

跨多轮、复杂或高风险的任务建立计划；简单改动直接实现并记录验证结果。

## 一份计划记录完整任务

- 进行中：[`docs/exec-plans/active/`](exec-plans/active/)；完成后移到 [`completed/`](exec-plans/completed/)。
- 模板：[`docs/exec-plans/templates/execution-plan.md`](exec-plans/templates/execution-plan.md)。
- 在同一文件维护目标、范围、进度、关键决定和最终验收，不重复创建过程和摘要。
- 完成后按 [`docs/HISTORY_GUIDE.md`](HISTORY_GUIDE.md) 留一条索引；已有计划包含的细节只链接，不重复抄写。
- 暂缓事项记入 [`docs/exec-plans/tech-debt-tracker.md`](exec-plans/tech-debt-tracker.md)。
- 归档前搜索仓库内对该计划的引用并更新路径；计划中的长期决定回写 [`docs/design-docs/index.md`](design-docs/index.md) 指向的设计文档，质量状态变化时更新 [`docs/QUALITY_SCORE.md`](QUALITY_SCORE.md)。

## 协作与权限

人在线时，在已授权范围内连续推进；关键需求不明确或操作超出授权时才确认，无需逐步审批。

无人值守任务应先明确范围、验收和沙箱权限。权限不足时记录阻塞，不能通过关闭沙箱继续。Windows 操作见 [`docs/WINDOWS.md`](WINDOWS.md)；其他平台的外部沙箱是可选扩展，只有在确认其官方来源、隔离范围和项目适配文档后才手动引入，不随新项目默认分发。

## 何时拆分记录

只有长期执行、日志很多或交接需要独立验收材料时，才使用 [`docs/exec-runs/`](exec-runs/)。可以仅拆过程或验收中的一项；计划链接详细记录，各处只维护一份事实。规则与模板见 [`docs/exec-runs/README.md`](exec-runs/README.md)。计划归档时，执行记录和其他入链都必须改为计划的当前路径。
