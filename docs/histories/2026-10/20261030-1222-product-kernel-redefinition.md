## [2026-10-30 12:22] | Task: 重定义产品内核并清理文档矛盾与冗余

### 🤖 Execution Context

- **Agent ID**: pi coding agent
- **Base Model**: 运行环境未暴露具体版本，仅确认为 Claude（Anthropic）
- **Runtime**: 本地 pi harness，Windows

### 📥 User Query

> 需求是重新定义产品内核，之前混乱了；用户认为内核应是「类似 DeepTutor 的产品机制、不依赖大模型 + 提示词、独属于产品本身的东西」，长期这么称呼，问有没有影响。要求再去 DeepTutor 论文和源码核查有没有遗漏更重要的内核内容，确认后「可以」，授权落文档。

### 🛠 Changes Overview

**Scope:** 仅文档。无产品代码、无模型调用、不改变任何已实现能力或验收状态。

**Key Actions:**

- **新增内核权威页** `docs/design-docs/product-kernel.md`：把内核定义为「两路上下文的持有与装配 + 结果结算」——课程内容上下文与学习者状态分开持有、分开装配；学习者状态分表现证据、困难清单、教法尝试记录三路；待答事项有独立生命周期；给出四条区分机制与提示词的硬测试，并列出必须单独证明增量、不得写进内核定义的能力。
- **补做论文核查** `docs/references/deeptutor-paper-kernel-check.md`：读取 arXiv 2604.26962v3 的 §1／§2／§3／§5.4／§5.5／Limitations／附录 B.1–B.2／C.3 及固定提交 `1ea7df1` 的 `services/memory/` 源码。补上先前调研遗漏的两处：内核是 SKG＋DPM 两路装配而非单一学习者状态；画像含独立的教学反思通道。纠正一处易抄错的结论：§5.4 消融比较的是「有记忆 vs 无记忆」，不是「结构化状态 vs 完整原始历史」，不能用来为同证据探针翻案。区分论文事实（多分辨率可语义检索的痕迹树）与仓库事实（三层文件式记忆、交互期召回只读时间戳与标签）。
- **删除「还原式」定位**：改写 `product-design.md` 定位与阅读边界、`PRODUCT_SENSE.md` 产品定位、`core-beliefs.md` 产品约束，删掉「重新实现 Hyperknow…不是重新定义学习产品」的自相矛盾表述；交互与视觉的证据沿用降级为参考来源，仍保留在 `product-design.md §5`。
- **归档旧内核稿**：`kernel-teaching-judgment.md` 加 ARCHIVED 横幅，说明 §0 已并入新内核页、§3.3 的最小形态进 §2.2 教法尝试记录，§1–§7 降为复议材料。
- **移出过时审计**：`business-ai-eval-audit.md` 从设计目录移入 `references/`（`git mv`），重写其相对链接与状态行，同步 `ARCHITECTURE.md`、`references/README.md`、两份 exec-plan 的引用。
- **统一术语**：`agent-core-v1.md` 改题「Agent 运行时 V1」并声明不是教学策略；`backend-evaluation-pipeline.md` 在索引中标明是评测工具；索引新增「只保留一个内核」的维护边界。
- **状态去重**：`index / api-and-events / agent-workflows / data-model / learning-experience / real-validation / PRODUCT_SENSE` 中重复的「哪个切片验收完成」散文改为指向 `QUALITY_SCORE.md`，本页不再复述。
- **阅读路线重排**：`index.md` 依次为 产品内核 → 产品设计 → 体验 → 架构 → …；「困惑内核」直接指内核页。

### 🧠 Design Intent (Why)

用户真正的诉求不是再写一版定义，而是让「内核」这个词在仓库里只有一个含义，并且能被执行。原文档同时承载还原式交付基线、通用 Agent 基础设施、旧四层假说和新方向讨论，读者必须自己拼装；`index.md` 甚至要求读者先读一节「为什么这里像有多个内核」。这次把定义从「模型做不出的判断」（排他轴，会随模型变强而失效）改为「产品持有并负责什么」（归属轴，可用删提示词、重启、重复提交等反例检验），并把 Agent 运行时与教学评测明确排除在「内核」之外。

### 📁 Files Modified

- `docs/design-docs/product-kernel.md`（新增）
- `docs/references/deeptutor-paper-kernel-check.md`（新增）
- `docs/design-docs/kernel-teaching-judgment.md`（归档横幅）
- `docs/design-docs/product-design.md`、`index.md`、`core-beliefs.md`、`agent-core-v1.md`、`api-and-events.md`、`agent-workflows.md`、`data-model.md`、`learning-experience.md`、`real-validation.md`
- `docs/references/business-ai-eval-audit.md`（`git mv` 自 `docs/design-docs/`）、`docs/references/README.md`
- `docs/PRODUCT_SENSE.md`、`docs/ARCHITECTURE.md`
- `docs/exec-plans/completed/20261026-business-ai-eval-audit.md`、`20261026-teaching-boundaries-refactor.md`
- `docs/learnings/2026-10/20261030-ownership-not-exclusivity.md`（新增）

### ✅ Verification

- **Commands or checks:** `node scripts/check-docs.cjs` 通过（退出 0，覆盖全部本地链接与锚点）；`git diff --check -- docs` 无空白错误（退出 0，仅余 CRLF→LF 提示，已统一为 LF）；移动后的审计文件 46 个相对链接逐条核对目标存在。
- **Known risks or follow-up:** 本轮只定义与整理文档，**不实施内核**：两路状态、待答事项、教法尝试记录、§4 四条硬测试均未在代码中兑现，`lesson_domain.py` 与 `quiz_storage.py` 之间仍无共享状态。旧内核稿 §3.3 迁入内核页只是定义，未排期。论文核查是静态阅读，未运行上游服务或复现实验。工作区原有大量未提交改动保持原样，未回退或提交。
