# Agent评测论文调研留痕

## 用户诉求

用户要求以多个子Agent调研近期相关论文，结合mini-hyperknow定位给出eval建议；随后授权“可以进行留痕”。

## 变更与意图

- 将调研结论整理为[Agent／教学eval参考](../../references/agent-evaluation-research.md)，记录九篇论文的来源、阅读范围、方法局限与工程建议，以及DeepSeek Harness、Comet的固定源码版本。
- 明确被测对象、任务运行单位和检查项判定单位的区别；保留产品目标确定覆盖、真实样本校准判据的候选方向。
- 关联仓库现有契约、执行与存储代码和真实失败证据；更新[外部资料索引](../../references/README.md)。
- 本次授权范围是记录研究，不将候选建议升级为已批准规格，不修改业务代码、质量状态或历史生成内容。

## 关键文件

- [调研记录](../../references/agent-evaluation-research.md)。
- [外部资料索引](../../references/README.md)。

## 验证与边界

- `npm.cmd run check:docs`通过：文档骨架及仓库内相对链接／锚点检查通过。
- `npx.cmd --yes markdownlint-cli2`检查本次三个文档通过，零问题；`git diff --check`通过。
- 八篇取得正文；Harness-Aware仅核对作者项目页与仓库，全文受阻。未复现实验，未运行付费模型或产品验收。
- 论文可迁移性与样本数量建议均有边界说明，不宣称已经改善教学质量或测得真实学习增益。
