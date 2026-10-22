# 白板切换 Excalifont 与小赖字体

## 用户诉求

白板英文使用 Excalifont，中文使用小赖字体，并删除旧字体的全部资源、说明与引用。保留已经实现的课堂业务与用户课程数据。

## 改动与动机

- 使用官方未修改的 Excalifont Latin WOFF2 与 Xiaolai v3.126 比例版 TTF，本地保存各自完整 OFL 1.1 版权／许可；来源、版本、体积和 SHA-256 见[字体 NOTICE](../../../web/public/fonts/NOTICE.md)。
- `board-fonts.ts` 集中定义字体栈与资源；两款 FontFace 均成功后才就绪。普通板书、SVG 和 Mermaid 测量共用 `Excalifont, Xiaolai, sans-serif`；代码、公式、旁白和界面字体隔离。
- 删除旧 TTF、授权声明图、来源 ZIP／元数据及无入链的旧专属 history。清除源码、README、设计、参考与原课堂计划中的旧字体说明；原业务验收事实保留，不冒充新字体验收。
- 忽略目录内原浏览器报告仅移除字体专属证据并附清理说明，保留真实课程／播放／问答观察；重新构建产物不再携带旧字体。
- 新增 `web/tests/board-fonts.test.ts`，检查字体栈、代码／公式隔离、真实二进制签名／哈希、许可及资源目录；运行代码主要在 `use-board-font.ts`、`Board.tsx`、`Classroom.tsx`、`classroom.css`。

## 验证与交接

- 前端 37 项检查、TypeScript 与 Vite 生产构建通过；文档骨架、Markdown lint 和差异检查通过。既有 Mermaid／ELK 大分包提示未放宽阈值。
- 内置浏览器复用已有 asyncio 真实讲义。标题实际命中 Excalifont 的 27 个字形及 Xiaolai 的 10 个字形；Mermaid 的中文标签命中 Xiaolai，英文标签命中 Excalifont，均为 custom font，不仅检查 CSS 字体名。已查看中英混排及图形截图。
- 两款资源实际加载 24,956／22,220,806 bytes；刷新后均 loaded，无字体错误。代码计算字体为 monospace；公式沿用原 KaTeX 隔离及真实渲染函数检查，本次没有另造数学课做浏览器公式验收。图形自然尺寸约 217.4 × 909.8px，910px 视口下页面 scrollWidth 为 894px。
- 字体验收只做已有讲义读取、刷新与独立回看，没有发起 prepare、question、progress 或 complete 命令。原两门课程及基线八表记录内容哈希保持一致；期间其他课时出现新增讲义／问答记录，因此**不宣称全库或总调用数不变**，也不回滚并行学习数据。
- 本地忽略证据：`data/validation/20261022-font-replacement-browser.json`、`20261022-font-replacement-row-audit.json` 与前后快照。截图已实际查看并留在工具会话中，不虚构落盘 PNG 路径。
- 未改 `.env`、后端或数据库，未停 Clone 服务，未提交／push／发布。小赖原始 TTF 约 22.2 MB，后续按实际指标优化；字体字形来源验证方法见[学习记录](../../learnings/2026-10/20261022-font-stack-is-not-glyph-proof.md)。
