# 把网页来源变成可验证的课程证据

## 是什么

联网搜索结果首先只是候选出处；被保存的网页摘录也不自动证明模型的课程结论。更可靠的边界是把“要回答的问题、课程事实主张、原文证据”建成显式关系，再让每个下游生成阶段只能选择上游批准的主张。

```text
ResearchQuestion
    └── Claim (claim_id, question_ids, summary)
          └── Evidence (source_id, exact quote, supports/contradicts)
                └── URL + provider + content mode + content hash + offsets

Blueprint unit → session → lesson step / exam → quiz question
```

## 为什么分层

`source_id`只说明某个来源被读取；它不能说明具体哪句话支持哪个课程判断。把引用契约收敛到`claim_id`和连续逐字`quote`后，服务端可以检查quote确实存在于本轮保存的摘录、计算字符偏移并绑定URL与内容hash。搜索供应商只负责召回或提取；不能把Exa与Tavily的分数混排，也不能把检索highlights当作整页。

这条链还需要跨生成阶段的授权边界：蓝图单元选择课程claim，单元展开只能从该集合中给session和exam分配claim，讲义步骤和测验题再校验其引用没有越过范围。否则，最初正确的证据仍可能在很长的课程生成上下文中被误用或丢失。

## 怎么做

1. **先建立证据，再总结。** 每条finding必须关联具体研究问题及至少一个真实已读来源；quote必须逐字出现在保存的原文摘录中。
2. **把来源内容模式说清楚。** 普通页面摘录与Exa query highlights不是同一种覆盖。即使高亮没有超过字符上限，也应明确它不是全文。
3. **按教学目标装配，而不是按网页顺序切前缀。** 蓝图先选择相关claim；lesson和quiz只接收被分配的claim及其原文片段，而不是把所有网页开头拼成上下文。
4. **把可验证性和真实性分开。** 字符串匹配可以证明“引文真的在保存文本里”，不能证明“引文语义上蕴含主张”或“来源可靠”。支持关系仍要用独立语义评测和人工核验。
5. **让修改走证据缺口。** 纯措辞或教学顺序调整可复用原证据；增加新的事实主题或挑战已有事实时，检查现有claim覆盖，再定向补搜，并保留未解决状态。

## 常见陷阱

- **URL很多不等于证据强。** 多个搜索引擎可能返回同一原始出处或转载，不能按命中数量制造独立支持。
- **quote存在不等于quote支持。** 模型可能摘录真实但无关的句子；结构校验只应作为最低门槛。
- **检索摘录不等于全文。** Exa highlights能帮助定向提取，但输出必须标示其内容模式和非全文边界。
- **只在最上游校验不够。** 证据可以在蓝图、单元、讲义、考核和测验间逐步脱落；每一跳都要检查claim选择是否属于父级允许集合。
- **变化后静默复用可能过时。** 对反馈重用原证据前，先比较事实范围；需要补研时仍由同一个本地Agent调度，避免供应商Deep Research形成第二个控制器。

## 自检

1. 这个quote支持的是哪个claim，claim回答哪个question？
2. 当前lesson或quiz是否只收到了分配给它的claim，而不是所有检索结果？
3. 校验只能证明引文存在时，怎样独立检查语义支持与教学适配？

本模式用于本仓库的[网页调研Agent](../../design-docs/web-research-agent.md)与[蓝图工作流](../../design-docs/course-blueprint-workflow.md)；结构与离线测试不代表Exa优于Tavily，也不证明真实课程质量改善。

本次实践记录见[history](../../histories/2026-11/20261109-2300-evidence-driven-research.md)，实施与验证清单见[execution plan](../../exec-plans/completed/20261109-evidence-driven-research.md)。
