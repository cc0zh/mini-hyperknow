## [2026-10-26 10:24] | Task: 沉淀后端教学评测Pipeline设计

### Execution Context

- **Agent ID**: 当前会话主助手。
- **Base Model**: 会话未提供可核实的模型标识，不推测版本。
- **Runtime**: Enso／pi，Windows PowerShell。

### User Query

> 总结关于后端先行、业务分类、先跑通一个场景及Trajectory的讨论，写一份design-doc；后续确认固定版本ATIF、轻量Pipeline、明确Rubric位置，并使用LLM Grader；保留数据与业务两条Pipeline。

### Changes Overview

- 新增后端教学评测Pipeline设计草案，明确任务、Trajectory、最终业务结果与证据包的关系。
- 首轮拟限即时协助单轮纯文字概念解释，当前采用规则＋LLM Grader；人工核对Rubric并抽查校准，配对比较及其他业务后置。
- 记录隔离、幂等恢复、失败／待判保留和成本边界；不实现框架、不调用收费模型、不修改质量状态。
- 更新设计索引；保留工作区已有评测调研及相关未提交改动。
- 2026-10-26 10:48补充格式决定：锁定ATIF-v1.7，规范及参考实现固定Harbor提交`872da9479f4a2078142d22c49c9ffae0f09e2e63`；明确标准字段映射、业务证据外置及多版本校验器需要额外版本门禁，新增外部参考并更新索引。只做文档决定，未引入代码／依赖或安装采集器。
- 2026-10-26 11:09按后续讨论收敛为普通顺序脚本，不建通用编排／注册体系；Rubric与参考事实放在Case内，三项语义要求由一次无工具的LLM调用判定，规则独立检查状态／产物／轨迹。记录评分输入输出、失败不算通过、独立成本及最小人工校准，不新增评分平台或发起收费调用。
- 后续明确保留两条轻量流程：数据Pipeline确认候选、事实与Rubric并固定Case；业务Pipeline消费Case、调用现有后端并判定本次新结果。共用ATIF转换，不自动把低分变成黄金题或改写本次Rubric，不因轻量化而省略数据准备职责。

### Design Intent

先交付一个可追溯、可复核的后端闭环，而非全业务评测平台；从首轮保留真实轨迹，不把结构有效、工具成功或最终回答单独当成教学成功。

### Files Modified

- [后端教学评测Pipeline](../../design-docs/backend-evaluation-pipeline.md)
- [设计索引](../../design-docs/index.md)
- [ATIF固定版本参考](../../references/atif-trajectory-format.md)
- [参考资料索引](../../references/README.md)
- 本history。

### Verification

- `npm.cmd run check:docs`通过：仓库文档骨架与本地链接有效。
- 轻量Pipeline与LLM Grader修订后，`npm.cmd run check:docs`、本轮三份文档的`npx.cmd --yes markdownlint-cli2`（v0.24.0，0问题）及`git diff --check`通过；文档内Case示例JSON解析成功，三项Rubric身份唯一。
- 固定提交的RFC与参考代码已只读核对；未运行ATIF校验器，不宣称导出器或AgentLoop集成已验证。
- 未实施评测框架，未执行真实模型／浏览器验收，不据本文宣称业务质量改善。
