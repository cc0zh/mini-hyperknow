## [YYYY-MM-DD HH:mm] | Task: <简短的任务动词>

> 二选一：已有完整 execution plan 时使用“索引分支”；没有计划时使用“详细分支”。不要把同一事实同时维护在 history 和 plan 中。

### 索引分支（已有完整 execution plan）

- **User Query:** {用户诉求的脱敏摘要}
- **Result:** {完成、部分完成或失败，以及对用户/仓库的结果}
- **Execution Plan path:** `docs/exec-plans/<active-or-completed>/<plan-slug>.md`（填写计划当前路径）

<!-- 计划归档后，将上面的链接更新为 completed/ 下的当前路径。 -->

### 详细分支（没有 execution plan）

### 🤖 Execution Context

- **Agent ID**: `如实填写`
- **Base Model**: `如实填写`
- **Runtime**: `如实填写`

### 📥 User Query

> {用户Query原文，或者压缩后的脱敏版本}

### 🛠 Changes Overview

**Scope:** (标注受影响的包)

**Key Actions:**

- **[Action 1]**: 简洁说明改动点 (e.g., 实现xxx)
- **[Action 2]**: (e.g., 优化了xxx消息转换逻辑)

### 🧠 Design Intent (Why)

*简洁直击要点的说明为什么要这么改？*

### 📁 Files Modified

- `path/to/src/core/file.ts`
- `path/to/src/pages/index.tsx`

### ✅ Verification

- **Commands or checks:** {命令和结果}
- **Known risks or follow-up:** {没有则填写“无”}
