# Hyperknow 课堂实际生成过程留存

用户目标是保存 Hyperknow 实际生成课堂的内容和过程，供后续直接对照，避免重复获取。这里保存真实课时大纲、教师讲解、板书、提问、回答及结束信号，不是以静态协议分析代替生成过程。

## 已完成的样本

主题为“Vibe Coding 与 AI 辅助开发”。历史开场产生于 2026-10-21。本机 2026-11-10 在用户允许使用现有积分后，继续同一已有课时，实时记录到原站显示“本节完成”。没有购买或充值积分，也没有进入下一节。

| 记录 | 实际内容 | 覆盖边界 |
| --- | --- | --- |
| [历史开场](evidence/2026-11-10-hyperknow-classroom/session-001/process.md) | 真实大纲、四条原始动作、旁白与板书 group、恢复载荷 | 历史保存内容，不冒称本轮实时生成 |
| [实时续讲全文](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/transcript.md) | 继续讲解、开放问题、误解回答、纠正与饮水追踪器例子、追问、流程对比、应用题、总结 | 从继续请求到本节完成的连续录制 |
| [最终清单](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/recording-manifest.json) | 173 条实际事件、3 次输入、17 份板书状态快照 | 原站在事件 172 返回 session=true、is_complete=true |

这是一节已有课堂的完整可见教学样本，由历史开场与本轮完整实时续讲组合。不是从课程创建重新录起，也不包括隐藏的后端模型 Prompt 或内部推理。

## 以后直接读取这些文件

1. 阅读 [逐段记录](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/transcript.md)，看实际讲解与提问如何展开。
2. 核对 [原始有序事件](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/events.jsonl)，看 group、板书、高亮、问答、动作确认和结束的顺序。该文件是唯一权威实时事件流。
3. 对照 [采集代理输入](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/operator-inputs.json)，看什么输入引出了哪段回应。
4. 查看 [板书变化](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/board-evolution.json)与[最后板书](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/final-board.json)。完整对象在 JSON 中，不依赖原站重取。
5. 查看 [原站总结时的白板截图](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/board-during-summary.png)和[结束后的可见文字](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/final-view.md)。截图裁剪掉账号及对话姓名区域，只覆盖当时可见的一部分画布。
6. 读取 [原站生成的动画原文](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/animation-artifacts.json)。实际 HTML 已存为惰性 JSON，不只有一个临时地址，不在本轮执行它。

所有文件都在仓库内，可以离线读取。无需再次登录原站取得本次已记录的文字、动作和板书。checkpoint-001 至 checkpoint-005 是录制中的累积备份，不能首尾拼接成新事件流，否则会重复计数。

## 实际录到了什么

- 恢复续讲后，原站解释 Vibe Coding，并提出角色变化的开放问题。
- 采集代理输入“AI 全自动做好，不用我检查”的误解并要求例子。原站随后给出纠正、两种模式对比、饮水追踪器示例与动画，再追问按钮失效时应如何处理。
- 采集代理回答应自己验证，并要求补讲流程区别。原站实际返回开发流程对比表、高亮和新的应用题。
- 采集代理给出应用回答并请求总结。原站给出奖励、总结、行动建议及下一节说明，最后明确返回本节完成。

这些是这一次样本中实际发生的顺序，不是对原站所有课堂策略的推断。原站奖励和“掌握”措辞保留为原文，不作为用户真实学习效果证据。

## 来源与使用边界

学生输入是采集代理为对照录制而写，不是用户真实回答。姓名已替换，UUID 一致匿名化。播放通过原站界面静音；没有归档音频字节或音频资源地址。记录顺序是客户端观察回调与发送顺序，不冒称服务端原始发出时间。

原始课时背景在 [input-context.json](evidence/2026-11-10-hyperknow-classroom/session-001/input-context.json)。隐藏后台输入、生成之前的课程澄清和内部模型调用过程没有取得，不做补写。源码和协议分析只作[辅助资料](hyperknow-classroom-generation.md)，不能替代本页的实际课堂样本。

本次按 Prove It Works 原则核对原始事件与本节完成信号。没有修改本地产品代码、Prompt、测试、配置或依赖。完整性结果见 [录制校验](evidence/2026-11-10-hyperknow-classroom/session-001/live-continuation/verification.json)。
