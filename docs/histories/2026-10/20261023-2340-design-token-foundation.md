## [2026-10-23 23:40] | Task: 建立设计令牌层并移除前端最小宽度限制

### 🤖 Execution Context

- **Agent ID**: pi（本地 Agent 会话）
- **Base Model**: Claude（Anthropic）
- **Runtime**: pi coding agent，Windows 11，Node.js + Vite 7

### 📥 User Query

> 你尽全力优化前端，先给出优化方案。不要被当前所限制，大胆一点，重点是美观。
>
> （方案第 1 批，选定配色方向：保留鼠尾草绿为主 + 淡紫辅助，蓝色全部退役。）

### 🛠 Changes Overview

**Scope:** `web/src/styles/`、`web/src/main.tsx`、`web/tests/board-fonts.test.ts`

**Key Actions:**

- **新增令牌层**：`styles/tokens.css` 提供纸面色阶、墨色阶、sage / lavender / sand / signal / slate 五组原始色板、语义别名、8 级字阶、4px 间距、圆角、动效曲线与四级阴影，并同时给出 `prefers-color-scheme` 与 `[data-theme]` 两套深色覆盖。
- **六份路由样式表迁移**：`app.css`、`workbench.css`、`blueprint-explorer.css`、`course-overview.css`、`course-path.css`、`classroom.css`、`quiz.css` 中的写死 hex 与 `font-size: 7px/8px/9px/10px` 全部替换为令牌与 `--fs-*`。
- **蓝色退役**：`#385d85`、`#294c74`、`#6d8daf`、`#8ea9cb`、`#f0f5fc` 等 20 余处蓝色一次性改为主色 sage；`var(--blue)` 保留为指向 `--sage-700` 的兼容别名，避免打断其余引用。
- **移除 `body { min-width: 780px }`**：改为 860px / 640px 两档真实响应式，Shell 在窄屏折叠成顶部栏 + 横向导航，并删除 `course-overview.css` 中针对该路由重复实现的 780px / 560px 外壳补丁。
- **板书区独立配色**：新增 `--slate-*` 固定浅色板与 `--slate-chrome-*`、`--slate-mark-*`、`--slate-notice-*` 一组板书专用色，使深色模式下板书、页栏、高亮与错误提示仍保持纸张质感。
- **可读性修正**：`.button.primary:disabled` 不再依赖 `opacity: .5` 变灰，改为实心 `--sage-400` + 白字；`.empty-state` 虚线边框改 sage；`.model-note` 提到 `--text-muted`。
- **新增动效**：页面进入 `page-in`、卡片 hover 位移与 `--shadow-3`、按钮按下 `scale(.985)`、播放状态点呼吸环、反馈卡片弹入、星星缩放进入，全部受既有 `prefers-reduced-motion` 保护。

### 🧠 Design Intent (Why)

界面原本的问题不是"不够花"，而是缺少设计系统：同一产品里 sage 纸感与工作台蓝色两套色系并存，约 300 个写死 hex 散落在 7 个文件，字号一路下探到 7px，`min-width: 780px` 让除课程总览外的所有路由在手机上横向滚动。

先建立令牌层，再让各页面消费令牌，之后每一批视觉改造（图标、画廊、三栏工作台、板书进度环、深色主题）都只需要改变量与局部规则，而不必再次逐个文件找颜色。同时把深色模式做成"换 ramp"而不是"重写样式"，板书区刻意不跟随：课堂应该像一张真的纸。

### 📁 Files Modified

- `web/src/styles/tokens.css`（新增）
- `web/src/styles/app.css`
- `web/src/styles/workbench.css`
- `web/src/styles/blueprint-explorer.css`
- `web/src/styles/course-overview.css`
- `web/src/styles/course-path.css`
- `web/src/styles/classroom.css`
- `web/src/styles/quiz.css`
- `web/src/main.tsx`
- `web/tests/board-fonts.test.ts`

### ✅ Verification

- **Commands:**
  - `npm.cmd --prefix web run typecheck` → 通过
  - `npm.cmd --prefix web test` → 70 项全部通过
  - `npm.cmd --prefix web run build` → 成功（仅保留既有 mermaid chunk 体积告警）
  - 真实后端 + Vite 开发服务器下用 Playwright 截图 Home / Courses / Overview / Workbench / Classroom / Quiz / 深色 Courses / 深色 Classroom / 390px 移动端 Courses，均为真实已保存课程数据
- **Checks:** 全仓 `#[0-9a-f]{3,8}` 扫描后仅剩 4 处有意保留的半透明叠加值；`font-size` 扫描无低于 12px 的规则；移动端 `scrollWidth` 不再溢出。
- **Known risks or follow-up:** 小赖字体 22MB 尚未子集化；SVG 图标替换、Courses 画廊化、工作台三栏与板书进度环属于后续批次；e2e 未在本轮执行付费真实验收场景。
