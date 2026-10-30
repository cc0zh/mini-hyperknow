# DeepTutor：借鉴学习任务，而非复制产品能力

核对日期：2026-10-29。用途：为本项目[学习任务评测](../design-docs/backend-evaluation-pipeline.md)提供一手方法参考，不是本项目教学效果或评分器可靠性证据。

## 读取范围与可核验来源

- [DeepTutor: Towards Agentic Personalized Tutoring，2604.26962v3](https://arxiv.org/html/2604.26962v3)：重点核对摘要、引言、框架，以及第4节TutorBench与第5节交互评测／人工对齐的目的和边界。论文网页分段读取，不声称复现了全部实验、数据构造或附录算法。
- [官方仓库固定提交](https://github.com/HKUDS/DeepTutor/tree/fa26e7e999ccc04e042dcc842b890da5d2d317f4)：核对 `deeptutor/services/rag/eval/` 的 `runner.py`、`dataset.py`、`metrics.py`、`diff.py`，不是只依赖README介绍。
- [固定runner源码](https://github.com/HKUDS/DeepTutor/blob/fa26e7e999ccc04e042dcc842b890da5d2d317f4/deeptutor/services/rag/eval/runner.py)：通过生产 `rag_search` 对检索结果和gold passage做匹配；实际实现为 **RAG检索评测，不是TutorBench实现**。不能将其指标或运行器冒称本地教学评测的直接复刻。
- [DeepSeek thinking mode官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)：核对reasoning与最终content的区别，用于解释真实评分在completion预算耗尽前没有最终JSON。没有据此暗中添加thinking参数、切换模型或修复返回内容。

论文作者报告的效果只属于论文中的任务、系统和实验条件；本项目未复现实验，不借用其提升百分比为本地结果背书。

## 采用与拒绝

| 一手资料中的目的／机制 | 本项目采用 | 不继承／尚未证明 |
| --- | --- | --- |
| 把学习者已有知识和细粒度知识缺口与具体学习任务相连 | Case明确背景、目标、误区、公开问题、参考理解和逐项判据；不只换八种API入口 | 17项只是作者开发集，未独立人工审核，不冒充TutorBench或留出集 |
| 第一人称学生模拟驱动多轮，观察持续困惑与教学适配 | 有界、无工具、看不到答案的学生角色；固定追问与模拟模式分开报告 | 模拟学生不是学习效果测量，不用自称“懂了”替代真人作答／前后测 |
| 正确理解保留给评判，避免直接暴露给被测导师 | 产品只收公开task；学生见learner与真实transcript，judge才见reference和rubric | 角色隔离不等于模型家族独立，也不保证自动判据没有偏差 |
| 多维评判与独立人类核查 | 工程、正确性、教学适配、多轮回应、来源支持分别报告；使用作者正负控制检验明显失灵 | 作者控制不等于独立人工校准、人类对齐或真实教学改善 |
| 在真实生产能力上检验，而非另写理想化执行器 | 实际HTTP、SQLite和已保存教学／来源证据，不回放模型响应 | 不复制其RAG／长期记忆／书籍／主动Agent，也不把检索质量等同教学质量 |

上游检索runner把执行失败与可评分指标区分；本项目同样区分执行与内容，但未执行／失败／不足仍保留在业务矩阵分母，不用成功交集掩盖缺口。具体比较契约是本项目决定，不照抄检索聚合方式。

## 本地证据的真实边界

实际实现、调用、预算失败与未完成项统一留在[重写验收计划](../exec-plans/completed/20261029-learning-evaluation-rewrite.md)。未经独立人工审核的任务与控制不能成为独立评分可信度证据；也未新增RAG、长期学习者记忆、产品Skill或搜索／开发工具权限。
