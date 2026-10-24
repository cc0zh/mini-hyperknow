## [2026-10-24 00:30] | Task: 图标系统、可折叠外壳与逐页视觉改造

### 🤖 Execution Context

- **Agent ID**: pi（本地 Agent 会话）
- **Base Model**: Claude（Anthropic）
- **Runtime**: pi coding agent，Windows 11，Node.js + Vite 7

### 📥 User Query

> 字体可以先不处理，你可以继续。把做完的结果截图保存。直接进行到第 5 批为止不需要我确认。

### 🛠 Changes Overview

**Scope:** `web/src/components/`、`web/src/pages/`、`web/src/styles/`、`web/src/lib/`、`web/index.html`

**Key Actions:**

- **图标系统**：新增 `components/icons.tsx`，统一 24 网格、1.7 描边、圆头端点、`currentColor`。替换掉 `⌂ ▤ ✳ ↗ → ← ✓ ★ ☆ ⌘` 共 40 余处 Unicode 符号；星形改用填充/描边两种 `IconStar`，因为 `★/☆` 在 Windows 与 macOS 字重、字宽都不同。
- **可折叠外壳**：侧栏 76px / 224px 两态，选择记入 `localStorage('hyperknow.sidebar')`，折叠态保留 `title` 与 `aria-label`；`aria-expanded` 反映真实状态。
- **吸顶毛玻璃顶栏**：`position: sticky` + `backdrop-filter`，用 `IntersectionObserver` 观察顶栏上方的 1px 哨兵元素切换 `.is-scrolled`，不监听 scroll 事件。
- **移动端底部 tab bar**：860px 以下隐藏侧栏、显示固定底部导航。此前把桌面侧栏压成横向条占掉手机首屏约 1/6。
- **Home**：主按钮去掉 `opacity: .5` 继承、改用真箭头图标；三步流程改为圆点 + 连线的序列（原先三条互不相关的横线）；新增"继续上次的进度"最近课程条（复用 `/courses`，但不用 `.course-card` 类，避免与库页断言冲突）。
- **Courses**：网格改为 `repeat(auto-fill, minmax(272px, 1fr))`；按 `course_id` 哈希生成确定性 SVG 星座封面，同一门课永远画出同一图形。
- **CourseRun**：两栏改三栏（需求 280–22% / 蓝图 / 资料 240–19%），调研与运行详情移入右栏；1100px 以下右栏隐藏，调研内容通过 `useMediaQuery` 回到左栏内联渲染，不重复 DOM。
- **Overview / Classroom / Quiz**：清除残留 `11px/12px/17px/22px` 硬编码字号；Quiz 进度条改为逐题分段，结果星级用 `IconStar` 并加错峰弹入。
- **收尾修复**：favicon 从旧蓝 `#4c6696` 改 sage；`theme-color` 拆成 light/dark 两条 media 查询；`--text-faint/--text-ghost` 各上移一级（12px 文字原先只有约 3:1，达不到 AA 的 4.5:1）；删除重复的 `@media (max-width: 1000px)` 与重复 `prefers-reduced-motion` 块。

### 🧠 Design Intent (Why)

上一批只统一了颜色与字号，真正让界面"不专业"的是三件与配色无关的事：图标在不同系统上长得不一样、手机上首屏被导航吃掉、以及首页在有课程之后变成死路。

图标问题无法靠 CSS 修，因为 Unicode 符号的形状由系统字体决定，只能换成自带路径的 SVG。移动端问题源于"把桌面布局压扁"这个旧策略，正确做法是给窄屏一套自己的导航形态。首页死路则是信息架构问题：课程已经存在时，用户最想做的事是继续上次的进度，而不是再描述一次目标。

三栏工作台是同一逻辑的延伸：参考资料是"依据"，不是"需求"，把它和偏好混在左栏会让真正的操作区被推到屏幕外。

### 📁 Files Modified

- `web/src/components/icons.tsx`（新增）
- `web/src/lib/use-media-query.ts`（新增）
- `web/src/components/ui.tsx`、`CourseStructure.tsx`、`BlueprintExplorer.tsx`、`RunResearch.tsx`
- `web/src/pages/Home.tsx`、`Courses.tsx`、`CourseOverview.tsx`、`CourseRun.tsx`、`Classroom.tsx`、`Quiz.tsx`
- `web/src/styles/app.css`、`tokens.css`、`workbench.css`、`course-overview.css`、`quiz.css`、`classroom.css`
- `web/index.html`

### ✅ Verification

- **Commands:**
  - `npx tsc --noEmit` → 通过
  - `npm test` → 70/70 通过
  - `npm run build` → `BUILD EXIT=0`
  - `npx playwright test`（真实后端 + 真实已保存课程，无请求拦截）→ 7 通过 / 4 跳过（跳过项需未配置模型或特定蓝图状态）
  - `npm run ci` → `CI EXIT=0`，242 项 Python 测试 + 21 项工具测试通过
- **截图:** `data/shots/v2/` 13 张，含 1440 桌面、900 平板、390 移动端与深色主题；抓取脚本报 `no page errors`。
- **Known risks or follow-up:** 小赖字体 22MB 仍未子集化（按用户要求本轮不处理）；`prefers-reduced-motion` 下星级动画已禁用；深色板书区保持纸白属于有意设计，不是遗漏。
