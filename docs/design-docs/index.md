# 设计文档索引

状态：2026-10-22 产品范围已确认；造课／课程库、课堂与练习／考核已完成各自切片范围的真实验收。思考题、项目成果及完整V01–V12仍未完成，设计完整不等于首版整体交付；当前证据与最终门禁见[练习／考核完成计划](../exec-plans/completed/20261022-real-practice-exams.md)。

## 阅读路线

1. [产品设计](product-design.md)：定位、首版 R01–R11、排除项与完成定义。
2. [页面与学习体验](learning-experience.md)：导航、生成／播放状态、活动和恢复语义。
3. [架构总览](../ARCHITECTURE.md)：当前事实、目标技术栈、目录职责、依赖及运行拓扑。
4. [模型工作流与上下文](agent-workflows.md)：场景输入输出、真实调用、内容校验和有限修复。
5. [领域对象与持久化](data-model.md)：SQLite 权威数据、状态、计分、事务及恢复。
6. [API 与事件](api-and-events.md)：REST 命令／查询、WS 通知与客户端同步。
7. [真实验证](real-validation.md)：拒绝 Mock、当前测试债、V01–V12 及证据要求。
8. [参考证据与缺口](reference-and-gaps.md)：用户确认、原站局部证据、Clone 事实和必要补齐。
9. [网页调研 Agent](web-research-agent.md)：独立调研、真实搜索／阅读、来源与预算；新造课接入及验收由蓝图工作流承接。
10. [蓝图确认与单元展开](course-blueprint-workflow.md)：当前阶段将调研接入造课、一次全局确认和逐单元局部保存；实施与验收状态见其计划。
11. [Agent 内核 V1](agent-core-v1.md)：通用内核调度、权限、会话、记忆、预算压缩和模型分层；与课程显式业务工作流隔离，不代表产品已接入文件或命令工具。
12. [即时协助与 Skill](instant-assistance.md)：2026-10-24授权新增的独立教学会话、闪卡、即时测验、白板、结构图和HTML动画；产物种类由模型判断而非学习者选项，正文支持四种封闭块类型与产物反馈；不做资料、检索或课程关联，实施／验收状态见关联计划。

## 状态与维护边界

- 上述文档为首版实施基线；产品裁剪来自用户确认，工程决定由本项目采用，不冒充原站技术方案。
- 实现状态在架构“当前事实”和[质量状态](../QUALITY_SCORE.md)说明，验收证据留计划／执行记录，各专题不得把目标写成已实现。
- 一主题一文档；当前数量较少采用平铺，不复制 ActSpace 全部专题及复杂度。
- 产品原则见[PRODUCT_SENSE](../PRODUCT_SENSE.md)，协作原则见[core-beliefs](core-beliefs.md)。
- 外部阅读入口见[参考资料](../references/design-document-references.md)，本轮记录见[history](../histories/2026-10/20261022-1456-product-architecture-baseline.md)。
- 设计回答是什么、为什么、边界是什么；实施步骤放 exec-plans，验证事实留计划或 exec-runs，外部资料放 references。不重复维护互相冲突的状态表。
