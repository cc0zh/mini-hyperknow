# 设计文档索引

状态：2026-10-22 建立产品与架构设计基线。用户已确认产品范围；目标实现尚未交付，设计完整不等于业务验收通过。

## 阅读路线

1. [产品设计](product-design.md)：定位、首版 R01–R11、排除项与完成定义。
2. [页面与学习体验](learning-experience.md)：导航、生成／播放状态、活动和恢复语义。
3. [架构总览](../ARCHITECTURE.md)：当前事实、目标技术栈、目录职责、依赖及运行拓扑。
4. [模型工作流与上下文](agent-workflows.md)：场景输入输出、真实调用、内容校验和有限修复。
5. [领域对象与持久化](data-model.md)：SQLite 权威数据、状态、计分、事务及恢复。
6. [API 与事件](api-and-events.md)：REST 命令／查询、WS 通知与客户端同步。
7. [真实验证](real-validation.md)：拒绝 Mock、当前测试债、V01–V12 及证据要求。
8. [参考证据与缺口](reference-and-gaps.md)：用户确认、原站局部证据、Clone 事实和必要补齐。

## 状态与维护边界

- 上述文档为首版实施基线；产品裁剪来自用户确认，工程决定由本项目采用，不冒充原站技术方案。
- 实现状态在架构“当前事实”和[质量状态](../QUALITY_SCORE.md)说明，验收证据留计划／执行记录，各专题不得把目标写成已实现。
- 一主题一文档；当前数量较少采用平铺，不复制 ActSpace 全部专题及复杂度。
- 产品原则见[PRODUCT_SENSE](../PRODUCT_SENSE.md)，协作原则见[core-beliefs](core-beliefs.md)。
- 外部阅读入口见[参考资料](../references/design-document-references.md)，本轮记录见[history](../histories/2026-10/20261022-1456-product-architecture-baseline.md)。
- 设计回答是什么、为什么、边界是什么；实施步骤放 exec-plans，验证事实留计划或 exec-runs，外部资料放 references。不重复维护互相冲突的状态表。
