# 已检查的用户流程

由 `scripts/render_statecharts.mjs` 从实际 statechart 工件生成。

有界安全性质通过不等于整个产品正确。故障目录中的反例属于主动注入的故障，不是当前产品缺陷。

## 从学习目标到可学习的课程

![从学习目标到可学习的课程](charts/course-flow/chart.svg)

```mermaid
---
title: "从学习目标到可学习的课程"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: done
    lg1: input
    lg2: stop
    lg3: work
  }
  class lg0 teal
  class lg1 yellow
  class lg2 orange
  class lg3 blue
  s0: 目标已提交
  s1: 任务已停止#65292;需显式重试
  s2: 分析学习需求
  s3: 等待必要澄清
  s4: 搜索并阅读资料
  s5: 生成全局蓝图
  s6: 等待你确认蓝图
  s7: 逐单元展开并保存
  s8: 课程结构就绪
  [*] --> s0
  s0 --> s1: 任务停止或用户取消
  s0 --> s2: 提交学习目标
  s2 --> s1: 任务停止或用户取消
  s2 --> s3: 需要补充信息
  s2 --> s4: 无需澄清#65292;直接调研
  s3 --> s1: 任务停止或用户取消
  s3 --> s4: 提交澄清答案
  s4 --> s1: 任务停止或用户取消
  s4 --> s5: 调研报告已保存
  s5 --> s1: 任务停止或用户取消
  s5 --> s6: 保存蓝图草案
  s6 --> s1: 任务停止或用户取消
  s6 --> s4: 反馈调整#65292;补充调研
  s6 --> s7: 明确批准蓝图
  s7 --> s1: 任务停止或用户取消
  s7 --> s8: 保存单元#65292;全部完成后就绪
  class s0 blue
  class s1 orange
  class s2 blue
  class s3 yellow
  class s4 blue
  class s5 blue
  class s6 yellow
  class s7 blue
  class s8 teal
```

[基线报告](charts/course-flow/report.md) · [主动故障见证](charts/course-flow/mutation/report.md)

## 保留的脚本式课堂播放ﬂ°°12289¶ß提问与完成

![保留的脚本式课堂播放ﬂ°°12289¶ß提问与完成](charts/classroom-flow/chart.svg)

```mermaid
---
title: "保留的脚本式课堂播放ﬂ°°12289¶ß提问与完成"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: done
    lg1: input
    lg2: stop
    lg3: work
  }
  class lg0 teal
  class lg1 yellow
  class lg2 orange
  class lg3 blue
  s0: 进入课堂#65292;只读已有状态
  s1: 正在准备讲义
  s2: 讲义任务已停止#65292;等待重试
  s3: 暂停#65292;可回看
  s4: 提问中#65292;固定教学位置
  s5: 正在讲解
  s6: 已确认最后总结
  s7: 你已手动完成本课
  [*] --> s0
  s0 --> s1: 明确准备本课
  s1 --> s2: 任务停止或用户取消
  s2 --> s1: 明确重试讲义生成
  s1 --> s3: 保存讲义#65292;初始暂停
  s3 --> s4: 提交问题并暂停
  s3 --> s5: 明确播放
  s4 --> s3: 回答结束#65292;等待明确继续
  s5 --> s3: 暂停 or 刷新后本地暂停 or 逐步确认#65292;检查点自动暂停
  s5 --> s4: 提交问题并暂停
  s3 --> s6: 逐步确认#65292;检查点自动暂停
  s6 --> s4: 提交问题并暂停
  s6 --> s7: 明确完成本课
  s5 --> s6: 逐步确认#65292;检查点自动暂停
  s4 --> s6: 回答结束#65292;等待明确继续
  class s0 blue
  class s1 blue
  class s2 orange
  class s3 blue
  class s4 yellow
  class s5 blue
  class s6 blue
  class s7 teal
```

[基线报告](charts/classroom-flow/report.md) · [主动故障见证](charts/classroom-flow/mutation/report.md)

## 逐题作答与显式提交和结果保存

![逐题作答与显式提交和结果保存](charts/quiz-flow/chart.svg)

```mermaid
---
title: "逐题作答与显式提交和结果保存"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: done
    lg1: input
    lg2: stop
    lg3: work
  }
  class lg0 teal
  class lg1 yellow
  class lg2 orange
  class lg3 blue
  s0: 进入练习或考核#65292;只读
  s1: 正在准备题组
  s2: 出题已停止#65292;等待重试
  s3: 题组已保存#65292;等待开始
  s4: 回答第一题
  s5: 本题反馈#65292;等待下一题
  s6: 回答第二题
  s7: 末题反馈#65292;等待你提交
  s8: 结果与完成记录已保存
  [*] --> s0
  s0 --> s1: 明确准备题组
  s1 --> s2: 任务停止或用户取消
  s2 --> s1: 明确重试出题
  s1 --> s3: 保存不可变题组
  s3 --> s4: 明确开始作答
  s4 --> s5: 保存答案或跳过#65292;停留反馈
  s5 --> s6: 明确进入下一题
  s6 --> s7: 保存答案或跳过#65292;停留反馈
  s7 --> s8: 明确看结果#65292;事务计分并保存
  class s0 blue
  class s1 blue
  class s2 orange
  class s3 blue
  class s4 yellow
  class s5 yellow
  class s6 yellow
  class s7 yellow
  class s8 teal
```

[基线报告](charts/quiz-flow/report.md) · [主动故障见证](charts/quiz-flow/mutation/report.md)

## 独立即时协助与可选产物

![独立即时协助与可选产物](charts/assistance-flow/chart.svg)

```mermaid
---
title: "独立即时协助与可选产物"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: done
    lg1: stop
    lg2: work
  }
  class lg0 teal
  class lg1 orange
  class lg2 blue
  s0: 独立会话#65292;可直接提问
  s1: 教学轮次排队
  s2: 已取消#65292;未保存本轮回复
  s3: 正在教学#65292;产物尚未提交
  s4: 重启后本轮已中断
  s5: 本轮失败#65292;未提交产物
  s6: 回复已保存#65292;无需产物
  s7: 回复与一个产物同时保存
  [*] --> s0
  s0 --> s1: 发送问题或明确继续
  s1 --> s2: 显式取消
  s1 --> s3: 开始教学
  s1 --> s4: 服务重启
  s2 --> s1: 显式重试当前失败轮次
  s3 --> s2: 显式取消
  s3 --> s4: 服务重启
  s3 --> s5: 生成或校验失败
  s4 --> s1: 显式重试当前失败轮次
  s5 --> s1: 显式重试当前失败轮次
  s3 --> s6: 校验并原子保存回复和可选产物
  s3 --> s7: 校验并原子保存回复和可选产物
  s6 --> s1: 发送问题或明确继续
  s7 --> s1: 发送问题或明确继续
  class s0 blue
  class s1 blue
  class s2 orange
  class s3 blue
  class s4 orange
  class s5 orange
  class s6 teal
  class s7 teal
```

[基线报告](charts/assistance-flow/report.md) · [主动故障见证](charts/assistance-flow/mutation/report.md)

## 有预算的网页调研

![有预算的网页调研](charts/research-flow/chart.svg)

```mermaid
---
title: "有预算的网页调研"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: done
    lg1: stop
    lg2: work
  }
  class lg0 teal
  class lg1 orange
  class lg2 blue
  s0: 调研排队
  s1: 调研已停止
  s2: 等待有效搜索结果
  s3: 已有原文#65292;仍需有效搜索
  s4: 找到候选来源#65292;等待读取
  s5: 已搜索并读取原文#65292;可生成报告
  s6: 报告与证据已保存
  [*] --> s0
  s0 --> s1: 任务停止或用户取消
  s0 --> s2: 开始调研
  s2 --> s1: 任务停止或用户取消
  s2 --> s3: 成功读取并保存原文
  s2 --> s4: 搜索找到候选来源
  s3 --> s1: 任务停止或用户取消
  s3 --> s5: 搜索找到候选来源
  s4 --> s1: 任务停止或用户取消
  s4 --> s5: 成功读取并保存原文
  s5 --> s1: 任务停止或用户取消
  s5 --> s6: 合法报告通过校验后保存
  class s0 blue
  class s1 orange
  class s2 blue
  class s3 blue
  class s4 blue
  class s5 blue
  class s6 teal
```

[基线报告](charts/research-flow/report.md) · [主动故障见证](charts/research-flow/mutation/report.md)

## 任务命令与取消和显式重试

![任务命令与取消和显式重试](charts/run-lifecycle/chart.svg)

```mermaid
---
title: "任务命令与取消和显式重试"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: normal
    lg1: attention
  }
  class lg0 blue
  class lg1 orange
  s0: 尚未提交
  s1: 任务排队
  s2: 已取消
  s3: 正在生成
  s4: 重启后已中断
  s5: 生成失败
  s6: 结果已保存
  [*] --> s0
  s0 --> s1: 提交命令
  s1 --> s2: 显式取消
  s1 --> s3: 开始实际调用
  s1 --> s4: 服务重启
  s2 --> s1: 显式重试#65292;新建任务
  s3 --> s2: 显式取消
  s3 --> s4: 服务重启
  s3 --> s5: 生成失败
  s3 --> s6: 事务保存结果
  s4 --> s1: 显式重试#65292;新建任务
  s5 --> s1: 显式重试#65292;新建任务
  class s0 blue
  class s1 blue
  class s2 orange
  class s3 blue
  class s4 orange
  class s5 orange
  class s6 blue
```

[基线报告](charts/run-lifecycle/report.md) · [主动故障见证](charts/run-lifecycle/mutation/report.md)
