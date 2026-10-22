# 白板字体资源与许可

白板普通文字使用 `Excalifont, Xiaolai, sans-serif` 字体栈：英文、数字和受支持的西文标点由 Excalifont 绘制，中文及中文标点由小赖字体绘制。代码与数学公式保持专用字体。两款字体均为上游原始文件，未修改、未转换格式；CSS 别名不改动字体内部名称。

## Excalifont

- 作者与版权：Copyright (c) 2024 by Excalidraw. All rights reserved.
- 制作说明：Your Own Font Foundry（Virgil）；Ján Filípek / DizajnDesign（Excalifont 修改）。
- 来源：[Excalidraw 官方字体目录](https://github.com/excalidraw/excalidraw/tree/1d4dc2c0e6e476911d0760e9c3cf3694f2d43384/packages/excalidraw/fonts/Excalifont)。
- 上游文件：Excalifont-Regular-a88b72a24fb54c9f94e3b5fdaa7481c9.woff2，官方 Latin 子集；本地文件 `Excalifont-Regular.woff2`，24,956 bytes。
- 元数据：Excalifont Regular，Version 1.000；上游 index.ts 包含字体元数据与完整 OFL 文本。
- SHA-256：`e4423b318e11432aff2e6e865e300b7ca270f92321a3f56632268fede01c1b48`。
- 许可：[Excalifont-OFL.txt](Excalifont-OFL.txt)，从同一上游 index.ts 的许可元数据提取完整正文并保留版权。

## 小赖字体 / Xiaolai

- 版权：Copyright 2020-2024 LXGW；Copyright 2014 Nozomi Seto。
- 来源：[官方仓库](https://github.com/lxgw/kose-font)、[v3.126 发布](https://github.com/lxgw/kose-font/releases/tag/v3.126)。
- 原始资源：[Xiaolai-Regular.ttf](https://github.com/lxgw/kose-font/releases/download/v3.126/Xiaolai-Regular.ttf)，22,220,806 bytes；使用比例版，不是 Mono 版或 Japanese 版。
- 已核对字体内部名称：小赖字体 / Xiaolai，版本 `Version 3.126;September 10, 2025`。
- SHA-256：`e2f68daf0e72777a8cf58bc83de1b98634b251e537ddbfca24b0ae50d1802da2`。
- 许可：[Xiaolai-OFL.txt](Xiaolai-OFL.txt)，原文来自上游提交 `172d9dbe94ade82b5316e0989e3aa286b7041baf` 的 OFL.txt，保留完整版权与正文。

## 使用与分发

两款字体均采用 SIL Open Font License 1.1，允许使用、嵌入及随软件再分发，须遵守各自完整许可证：保留版权和许可、不单独售卖字体、字体及其衍生版继续按 OFL 分发，并遵守保留名称等适用条款。字体不套用本仓库代码许可证；应用或用字体制作的文档不因此必须改用 OFL。

获取与核对日期：2026-10-22。字体只从本地静态资源加载，不使用运行时第三方 CDN 或系统字体代替验收。
