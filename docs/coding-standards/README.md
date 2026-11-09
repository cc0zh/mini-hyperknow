# 编码规范与 Skill 推荐

仓库的编码规范入口。通用规范用 skill，团队私有约定放 `team/`。

## 已安装 Skill

只登记已实际安装并适用于本项目工作流的 Skill；没有条目时不要求安装。

项目本地形式验证技能见[验证入口](../formal-verification/README.md)。每个技能有独立模型、覆盖映射和真实源码故障见证。

- [verify-run-lifecycle](../../.agents/skills/verify-run-lifecycle/SKILL.md) 检查命令标识冲突与共享任务生命周期。
- [verify-course-flow](../../.agents/skills/verify-course-flow/SKILL.md) 检查蓝图确认与全部单元提交后就绪。
- [verify-research-flow](../../.agents/skills/verify-research-flow/SKILL.md) 检查每轮调研工具预算。
- [verify-classroom-flow](../../.agents/skills/verify-classroom-flow/SKILL.md) 检查最后总结与手动完成。
- [verify-quiz-flow](../../.agents/skills/verify-quiz-flow/SKILL.md) 检查全部作答后的显式提交。
- [verify-assistance-flow](../../.agents/skills/verify-assistance-flow/SKILL.md) 检查一轮最多保存一个产物。

## Skill 推荐清单

需要记录选型依据时使用 [`skill-catalog.md`](skill-catalog.md)，不预填未采用的工具。

## 团队自定义规范

Skill 覆盖不到的团队约定，放在 [`team/`](team/README.md) 子目录，命名格式：`{领域}-conventions.md`。
