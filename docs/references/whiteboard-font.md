# 白板字体：Excalifont 与小赖字体

## 当前选择

白板普通文字使用 **Excalifont + 小赖字体（Xiaolai）**。字体栈按 `Excalifont, Xiaolai, sans-serif` 排列；Excalifont 为官方 Latin 子集，不含汉字，因此英文与数字优先使用 Excalifont，中文及中文标点回退到小赖字体。具体范围见[白板手写体](../design-docs/learning-experience.md#白板手写体)。

代码保持等宽及原缩进，公式保持 KaTeX 数学字体。导航、按钮、文字旁白和课堂问答继续使用界面字体，不全站替换。

## 来源与许可

- [Excalidraw 官方 Excalifont](https://github.com/excalidraw/excalidraw/tree/1d4dc2c0e6e476911d0760e9c3cf3694f2d43384/packages/excalidraw/fonts/Excalifont)：采用上游原始 Latin WOFF2，内部 Excalifont Regular，版本 1.000。
- [小赖字体官方仓库](https://github.com/lxgw/kose-font)及[v3.126 发布](https://github.com/lxgw/kose-font/releases/tag/v3.126)：采用比例版 Xiaolai-Regular.ttf，已直接读取字体内部名称与版本，不使用名称近似的日文版。
- 两者均为 OFL 1.1。本地保留两份完整版权／许可；原始文件未转换、合并或改字形。路径、版本、哈希、体积和许可全文入口统一见[字体 NOTICE](../../web/public/fonts/NOTICE.md)。

## 加载与验证

FontFace 显式请求两款本地资源，全部成功后才标记 ready，并允许 Mermaid 测量中文／英文混排；任一失败都显示指定字体未能加载，不能把系统回退当作成功。HTML、SVG 与 Mermaid 使用相同字体栈。

验证覆盖真实字体文件哈希及签名、浏览器实际字形来源、中英混排、中文标点、代码／公式隔离、Mermaid 标签测量和刷新。只检查 CSS 字体名或 document.fonts.check 不足以证明每种文字使用正确字体。

本次字体变更只重新排版已有讲义，不请求新模型、不修改讲义内容、脚本版本、教学游标或完成记录。

## 当前验收

内置浏览器已在已有真实 asyncio 讲义中确认标题同时命中 Excalifont／Xiaolai，Mermaid 中文／英文标签分别命中对应 custom font；双资源加载、混排截图、代码隔离、独立回看及刷新已检查。具体字形来源、尺寸、数据核对与未覆盖边界见[本次交付记录](../histories/2026-10/20261022-1903-bilingual-whiteboard-fonts.md)。原课堂验收不替代此次双字体验收。
