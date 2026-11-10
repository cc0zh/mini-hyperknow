# 外部参考资料

这个目录用于沉淀那些值得长期放进仓库、供 Agent 直接读取的外部参考材料。

适合放这里的内容包括：

- 团队会反复依赖的框架、部署或接入说明。
- 设计系统参考、API 使用约定。
- 对外标准、合作方协议或外部文档的简要整理版。

不要把大段供应商文档原样塞进来。这里应该是经过筛选和整理后的资料。

## 当前资料

- [Hyperknow课堂实际生成过程](hyperknow-classroom-process.md)：用户指定的复用入口。保存历史开场与获准实时续讲，直至原站本节完成；含有序事件、完整讲解、三次受控输入、板书变化和真实截图，以后直接读取，不重复获取原站。

- [Hyperknow课堂生成对照](hyperknow-classroom-generation.md)：核查当前教师回合制与原站公开协议，定位教学依据、短答案、节奏和白板切帧的待验假设；保存带哈希的离线摘录与当前资源片段，不构成实施授权或真实教学效果验收。

- [DeepTutor论文内核核查](deeptutor-paper-kernel-check.md)：论文 §2／§3／§5.4／附录 B 与固定 main 源码的定向核对；补上「两路上下文装配」与「画像三路（含教学反思）」两处内核遗漏，纠正消融比较对象，区分论文事实、仓库事实与不可推出。

- [DeepTutor产品内核调研](deeptutor-product-kernel-research.md)：中文文档及固定main／dev源码；区分能力证据、教学反馈、自主推进与复习，复核停轮／评分／模式的实现边界；对照当前反馈消费和追答断点，建议先验证可恢复的单课时教学回合，不构成实施授权。

- [DeepTutor学习任务评测参考](deeptutor-learning-evaluation.md)：论文阅读范围、固定官方源码核验、知识缺口／多轮／答案隔离的采用与产品扩权的拒绝；RAG eval不能冒称TutorBench实现。

- [设计文档组织方式参考](design-document-references.md)：用户指定的 ActSpace 文档阅读范围、借鉴方法和明确不继承的架构；Hyperknow 证据入口。
- [白板字体参考](whiteboard-font.md)：Excalifont 英文／数字与小赖 Xiaolai 中文的分工、原始资源、OFL 1.1 许可证及当前验收边界。
- [Agent／教学eval论文调研](agent-evaluation-research.md)：九篇论文的阅读范围与局限、DeepSeek Harness／Comet固定源码参考，以及面向当前项目的评测颗粒度、证据、校准和比较建议；尚未实施。
- [ATIF轨迹固定版本](atif-trajectory-format.md)：历史ATIF-v1.7来源与当时出口边界；2026-10-29已退役，不是现行CLI能力。
- [通用评测重构参考](evaluation-refactor-sources.md)：阿里云手册、美团文章及Penguin可检索正文片段的阅读范围、采用原则与不采用项；不是全文／源码审计或效果验证。

- [业务、AI契约与评测可优化性审计](business-ai-eval-audit.md)：2026-10-26 静态审计，2026-10-30 从设计目录移入。保留重构前源码快照与当时建议，**不是当前业务地图或契约**；现行定位查[架构](../ARCHITECTURE.md#10-现行业务与改动影响入口)。
