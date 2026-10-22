# 设计文档索引

用这个目录集中管理架构设计、产品设计和其他长期有效的决策。入口见 [`AGENTS.md`](../../AGENTS.md)；顶层结构仍由 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) 维护。

建议约定：

- 一个主题一份文档。
- 每份文档写清当前状态（提议、生效、废弃）和简短摘要。
- 关联引入或修改它的 execution plan、spec 或 history。
- 计划中的决定完成后仍然有效时，回写这里的长期文档；计划只保留实施过程和证据。
- 计划归档或设计文档移动时，同步更新所有入链，避免只指向 `active/` 的临时路径。

## 初始文档

- [`core-beliefs.md`](core-beliefs.md) — 生效 — Agent-first 模板的长期原则。
