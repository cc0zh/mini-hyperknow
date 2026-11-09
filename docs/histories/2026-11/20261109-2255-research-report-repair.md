## 2026-11-09 22:55 | Task: 修复真实调研报告校验失败

### 详细分支

### 用户诉求

修复真实 Exa/Tavily 调研运行中，报告因来源引用不一致而进入修复请求，随后因输出长度限制失败的问题。

### 主要改动

- 以 `ResearchFinding.evidence` 作为来源引用的唯一事实来源。
- 从 evidence 按首次出现顺序派生 `source_ids`，继续保留报告存储和 API 输出字段。
- 从 finding 的 `question_ids` 派生问题的 `claim_ids`，避免模型重复维护反向关系。
- 更新调研和修复提示，要求模型提供 evidence 与 finding 问题关联。
- 增加回归测试，覆盖不一致的冗余 ID 被规范化以及保存格式继续输出派生字段。

### 设计动机

模型输入同时维护正向和反向关系会产生可合法解析但互相矛盾的报告。服务器已有 evidence 和 finding 关系，派生重复字段可以消除这类矛盾，并保留下游已有读取格式。

### 受影响文件

- `src/hyperknow/research_domain.py`
- `src/hyperknow/prompts/research.py`
- `tests/test_research.py`
- `docs/design-docs/web-research-agent.md`

### 验证

- 修复前回归测试因 `claim source IDs must match its passage references` 失败。
- 修复后 `test_research.py` 的 25 项测试通过。
- `test_research_runtime.py` 的 11 项测试通过。
- 已保存的真实失败运行草稿现在通过报告和逐字证据校验，包含 7 条 finding 和 19 条 evidence。
- 第二次真实重跑以模型输出长度结束，证明 4,096 输出 token 预算仍不足。
- 研究输出预算已提升到 8,192 token，但第三次真实重跑仍发现供应商调用处硬编码为 4,096 token。
- 为保留原有最大中文输入边界，输入预检移除与报告余量重复的额外安全余量；报告余量仍为 12,000 token。
- 提示要求证据覆盖后停止工具，并限制最终报告为最多 6 个问题、6 个主张和每个主张最多 2 条证据，避免合法报告超过输出上限。
- 将供应商调用上限改为共享的 8,192 token 后，第四次真实重跑成功，保存报告含 6 个 finding、4 个 question 和 12 条 evidence。
