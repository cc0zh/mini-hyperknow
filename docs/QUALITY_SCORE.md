# 质量评分

状态：2026-10-22。只报告实际实现和验证，不把文档检查当业务质量达标；历史测试结论不能覆盖新的拒绝 Mock 要求。

| 区域 | 当前状态 | 依据／证据入口 | 下一步 |
| --- | --- | --- | --- |
| 产品与架构 | 造课／课程库首切片完成真实浏览器验收，课堂等后续切片未实施 | [设计索引](design-docs/index.md)、[实际实现与证据](exec-plans/completed/20261022-real-course-library.md) | 实施真实讲义与白板课堂 |
| Agent 内核 | 已用 deepseek-flash 完成真实澄清／造课，SDK 自动重试关闭 | [当前事实](ARCHITECTURE.md)、[调用依据](exec-plans/completed/20261022-real-course-library.md) | 后续教学场景与结构修复路径验收 |
| 业务验收 | 两组真实需求、回答／跳过、课程浏览、取消／重试及冷重启通过；V01–V12 未整体通过 | [真实验收](design-docs/real-validation.md)、[切片证据](exec-plans/completed/20261022-real-course-library.md) | 继续课堂、作答和成果切片，不夸大完成范围 |
| 测试入口 | Mock／Fake／patch 与 provider 注入替身已移除，uv 驱动真实检查 | [CI/CD](CICD.md) | 保持真实验收与本地检查分层 |
| 数据恢复 | 真实课程冷重启前后哈希一致，澄清与版本不变，调用未增加，浏览器 WS 重连 | [数据模型](design-docs/data-model.md)、[切片证据](exec-plans/completed/20261022-real-course-library.md) | 后续讲义／学习记录恢复 |
| 运行与基本卫生 | 本地服务、缺配置错误、真实模型与构建已验；未发布部署 | [运行底线](RELIABILITY.md)、[切片证据](exec-plans/completed/20261022-real-course-library.md) | 不扩成企业安全项目 |

本表只链接权威状态和验收证据，不复制过程日志。当前 `npm run ci` 的本地通过仍不代表真实成功模型或全部业务验收通过。
