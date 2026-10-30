## [2026-10-29 22:13] | Task: 梳理产品内核文档并直接回应原始疑惑

### 🤖 Execution Context

- **Agent ID**: pi coding agent
- **Base Model**: GPT-5.6（当前会话声明）
- **Runtime**: 本地 pi harness，Windows

### 📥 User Query

> 梳理当前的文档内容；用户被产品内核搞得有点晕，希望能解答已经记录在文档中的疑惑。

### 🛠 Changes Overview

**Scope:** 仅文档整理，不改产品代码、不启动收费模型调用、不形成新的产品决定或实施授权。

- 在既有内核专题新增 §0.6，直接回答模型与产品贡献、提示词与机制、四层方案地位、学习过程示例及评测／消融对象；明确方向已确认、机制待验证。
- 为索引和产品设计补充阅读边界，区分原实施基线、新方向与前轮复议材料，保留原路径、历史方案及实验记录。
- 同步产品原则中已过期的排除项：掌握度／重排／门槛已解除范围限制，独立即时协助已另行加入；不改变当前计分、推进或验收状态。
- 核对已有 DeepTutor 调研与同证据探针的结论边界，不把源码参考、局部动作差异或未建立增益写成有效／无效的确定结论。

### 🧠 Design Intent (Why)

用户疑惑涉及产品责任与模型能力，而非再增加一组技术名词。文档同时承载原还原式产品基线、通用 Agent 基础设施、旧教学判断假说与新的主动教学方向；需要明确层级及时间边界，避免将它们拼成一套已确认方案。候选机制的产品增量与真人教学收益继续分别论证。

### 📁 Files Modified

- `docs/design-docs/kernel-teaching-judgment.md`
- `docs/design-docs/index.md`
- `docs/design-docs/product-design.md`
- `docs/PRODUCT_SENSE.md`
- `docs/histories/2026-10/20261029-2213-kernel-clarification.md`

### ✅ Verification

- **Commands or checks:** `node scripts/check-docs.cjs` 与受影响已跟踪文件的 `git diff --check` 均通过（退出0）；定向检查五份文档的61处本地链接、新增引用锚点及空白格式，无问题（退出0）。已回读新增疑惑回应、索引及产品边界。上述检查只证明文档一致性，不是教学机制或业务验收。
- **Known risks or follow-up:** 本轮只回答及整理概念，不证明具体机制有增益，不审计全部运行实现。基本教学单位、目标修订、调整／停止边界和公平对照仍待设计与真实验证；旧材料保留为复议而非新规格。工作区原有大量未提交修改，未回退或提交它们。
