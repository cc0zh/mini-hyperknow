# 质量评分

## 2026-10-23 造课工作台

紧凑造课外壳、全单元轻量结构图、稳定节点详情和常驻阶段操作已实现；70项前端／21项仓库Node、TypeScript／Vite及真实只读浏览器回归通过。新四单元主题真实完成澄清、资料、蓝图调整／刷新／一次批准，保存第一单元后被既有`context_too_large`预算拒绝，**未完成新主题整链ready验收**；完成态以此前真实保存课程只读验证，不以替身补成功。范围、证据与边界见[工作台完成计划](exec-plans/completed/20261023-course-creation-workbench.md)，预算问题列入[技术债](exec-plans/tech-debt-tracker.md)。

## 2026-10-23 蓝图确认与逐单元展开

已通过一个真实asyncio主题的研究、蓝图调整、全局确认、逐单元提交、在途取消／晚到拒绝／显式重试及等待／完成状态冷重启。新课程2单元／4课时、首课8步讲义，总13次实际模型调用；部分目录不冒充整门100%。自动回归为242项Python、21项仓库Node、61项前端检查，TypeScript／Vite构建通过。证据与未覆盖边界以[完成计划](exec-plans/completed/20261023-course-blueprint-workflow.md)为准，不宣称教学全部正确，不要求旧课兼容，项目提交仍暂缓。下方保留既有阶段记录。

状态：2026-10-22。只报告实际实现和验证，不把文档检查当业务质量达标；历史测试结论不能覆盖新的拒绝 Mock 要求。本阶段业务范围完成，最终CI、前端测试／构建、Markdown、差异与锁文件检查通过；完整产品场景仍按实际覆盖边界报告。

| 区域 | 当前状态 | 依据／证据入口 | 下一步 |
| --- | --- | --- | --- |
| 产品与架构 | 造课／课程库、手写白板课堂及练习／考核均完成各自切片范围的真实验收 | [设计索引](design-docs/index.md)、[练习／考核完成计划](exec-plans/completed/20261022-real-practice-exams.md) | 项目按用户决定暂缓；下一候选为思考题保存／反馈及不含项目的链路验证，不宣称首版整体完成 |
| Agent 内核 | deepseek-flash真实澄清／造课／讲义／问答／出题，SDK自动重试关闭；讲义曾一次结构修复成功，本阶段三次quiz均首次校验成功 | [当前事实](ARCHITECTURE.md)、[调用与usage](exec-plans/completed/20261022-real-practice-exams.md#真实模型与成本) | quiz真实失败修复、取消晚到收费及在途硬重启仍未覆盖，不以课堂证据替代 |
| 通用内核 V1 | 调度／逐次审批、原文存档、工作区工具、独立 JSONL／显式记忆、完整轮预算压缩和显式 tier 已实现；67 项直接内核检查及真实模型工具循环／摘要／重开通过 | [V1 契约](design-docs/agent-core-v1.md)、[升级验收](exec-plans/completed/20261022-agent-core-v1.md) | 保留同步网络不能远端取消、命令非 OS 沙箱、POSIX 与不同厂商 tier 未验边界；不改变课程工作流 |
| 网页调研 Agent | 独立research run、来源报告及恢复已实现；51项调研检查、213项Python／21项Node CI通过；用户补齐配置后真实7次模型调用、2次搜索、1次阅读和报告恢复通过 | [调研契约](design-docs/web-research-agent.md)、[完成与证据](exec-plans/completed/20261023-web-research-agent.md) | 下一步接入造课和全局蓝图；内容准确性、外网在途取消／硬重启和全部重定向故障仍非全覆盖 |
| 业务验收 | 两主题练习与一组单元考核已验三题型、反馈／显式提交／再练／旧结果，考核完成不等于通过；V01–V12未整体通过 | [真实验收](design-docs/real-validation.md)、[Q01–Q16矩阵](exec-plans/completed/20261022-real-practice-exams.md#本阶段验收矩阵) | 思考题、项目成果与完整V12仍未完成；全部跨标签及危险输入不据此盖章 |
| 测试入口 | 无Mock／Fake／patch及provider注入替身；内核升级后162项Python、21项Node通过，49项前端及TS／Vite构建通过，保留分包警告 | [V1最终门禁](exec-plans/completed/20261022-agent-core-v1.md)、[既有业务门禁](exec-plans/completed/20261022-real-practice-exams.md#证据落盘与最终门禁) | 本地规则、真实HTTP与模型／浏览器证据分层，不把通用内核检查当完整产品验收 |
| 数据恢复 | v2→v3备份迁移原八表哈希一致、新增三表；无在途生成冷重启十一表哈希一致、调用保持17，恢复两答案／起点与旧结果 | [数据模型](design-docs/data-model.md)、[迁移与冷重启](exec-plans/completed/20261022-real-practice-exams.md#迁移与冷重启) | 成果恢复与真实模型在途硬重启尚未覆盖；不回滚或清空用户并行学习数据 |
| 教学内容 | 题组来源／结构已校验；摄影q_plant_ab忠于讲义但“转动植物改变相机相对光线方向”概念待纠正 | [教学内容债务](exec-plans/tech-debt-tracker.md)、[人工核查边界](exec-plans/completed/20261022-real-practice-exams.md#内置浏览器事实) | 纠正内容机制及可追溯记录，不手改历史题组伪造教学全部正确 |
| 运行与基本卫生 | 实际500／断线恢复、6秒网络延迟下反馈及pending释放已有浏览器证据；本地单worker，未发布部署 | [运行底线](RELIABILITY.md)、[同步与审查边界](exec-plans/completed/20261022-real-practice-exams.md#内置浏览器事实) | 不扩成企业安全项目；精确跨页面迟到A／B时序浏览器未复现 |

本表只链接权威状态和验收证据，不复制过程日志。CI、本地检查、模型结构有效和教学准确性分别报告；最终两份本地汇总证据由主代理补存／核对。
