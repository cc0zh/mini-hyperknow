# 通用评测重构参考：阿里云、美团与Penguin

整理日期：2026-10-27。用途：为[评测重构设计](../design-docs/backend-evaluation-pipeline.md)提供方法参考，不作为已实现能力或实验效果证据。

## 阅读范围与限制

本轮读取了公开搜索服务返回的正文片段。阿里云GitHub／raw/API、知乎和Penguin部分页面直连返回403、超时或fetch失败，未完整读取三站全文、固定上游提交或审计Penguin实现。以下只整理已取得内容，不将搜索摘要冒充完整源码核验；方法采用是本项目决定。

## 来源及启发

| 来源 | 已取得的相关内容 | 对本项目的启发 | 不直接采用的部分 |
| --- | --- | --- | --- |
| [阿里云手册调优篇](https://github.com/aliyun/ai-agent-handbook/tree/main/05-optimization)，重点第19章Agent轨迹数据、第22章Agent优化：Badcase | 轨迹阅读与最终业务状态核对；候选样本进入数据集；历史评估、试评和新生成结果实验的区分 | 保留真实执行证据，区分暂存与提交；新版本效果必须用新执行结果验证；失败材料先复核再进入任务集 | 云端控制台、声明式Pipeline平台、自动自进化及训练链路 |
| [美团《Agent评测漫谈》](https://zhuanlan.zhihu.com/p/2068995699606295771) | 对完整任务系统评测；结果／过程／效率／风险；采集、清洗、评测、质检及归因；从核心场景和Good／Bad Case迭代 | 评测器也要校准，先让少量业务判据可信；业务失败与证据／评分问题分别归因 | 一开始铺设庞大指标树或以单一总分代表全部业务质量 |
| [Penguin Evaluation Center](https://penguin.ooo/docs/evaluation-center/) | Benchmark属于Project；Case包含任务材料与私有Rubric；按Case与runs运行并记录版本、费用、耗时 | 任务集独立于被测对象；公开输入与私有评分隔离；固定任务和版本进行比较 | 将100分和简单平均设为所有业务的统一衡量标准 |
| [Penguin Self-Improvement](https://penguin.ooo/docs/self-improvement/) | Builder／Target／Evaluator／Optimizer分工；每次运行新Session和独立Workspace；统一结果协议；基线与候选比较 | 固定执行契约与隔离环境，把变化放到任务、接入和评分；优化与评分职责分开 | 将Evaluator Agent、多Agent并行、分数严格上涨就自动接受设为本项目初版前提 |

## 适用边界

- Penguin统一了自家被测Agent的CLI启动、Session和Workspace；不能据此声称任意Hyperknow业务已能直接接入，HTTP与持久化状态仍需适配。
- “通用”是共享执行／证据／评分协议，各业务仍需明确前置条件、实际完成语义及判据。评估Agent能读取材料，不等于自动具备可靠的学科判断。
- 历史记录可用于挖掘Case与校准评分；它不能冒充新版本生成。冻结真实材料作为单阶段任务的公开输入，与回放模型响应替代真实依赖是不同用途。
- 本项目的单worker、SQLite权威数据、拒绝Mock、固定ATIF-v1.7和桌面验收边界，以本地设计及真实验收契约为准。
- 未比较参考系统与本项目的实测效果，不从外部产品能力推导本项目质量已经提高。

既有论文研究见[Agent／教学eval调研](agent-evaluation-research.md)，ATIF固定版本来源及本地出口边界见[ATIF参考](atif-trajectory-format.md)。
