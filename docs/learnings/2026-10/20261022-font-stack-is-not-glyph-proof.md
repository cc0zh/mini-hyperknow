# 字体栈正确，不代表每个字形正确

## 问题

`font-family: Excalifont, Xiaolai, sans-serif` 只是浏览器的候选顺序。`getComputedStyle()` 返回声明的字体栈，不能证明中文实际由哪款字体绘制。`document.fonts.check()` 也不能单独证明某段文字没有回退。

## 怎么想

浏览器逐字形选字体：前面的字体缺字时，才到后面的候选中查找。这里用官方 Excalifont Latin 子集负责英文、数字和覆盖范围内的西文标点，小赖字体补充中文及中文标点；不用切割字符串或插入大量 span，HTML 和 SVG 可以共用同一字体栈。

但字体选择与布局必须分两步验证：

1. 显式加载两款 FontFace，全部成功后才把它们加入 FontFaceSet 并允许 Mermaid 测量。只等任意一款会让中文或英文测到回退字宽。
2. 对真实标题及 SVG 的文本叶子调用 Chromium CDP `CSS.getPlatformFontsForNode`，检查 `postScriptName`、`isCustomFont` 和 `glyphCount`，再看截图与节点边界。SVG 外层 text 可能返回空列表，应该检查含文本的 tspan。

代码和公式仍使用自己的字体；不要用统一的 `!important` 手写字体覆盖它们。

## 常见陷阱

- 字体资源成功下载但没有实际使用，不算通过。
- 用宽度差判断中文字形变化可能误判：两款等宽中文字体的 advance 相同，形状却不同。
- 字体变化会改变 Mermaid 自然尺寸；只检查 CSS 家族而不复查图形节点可能漏掉换行或截断。
- 在用户同时学习的运行库里，总调用数会因其他课时增加；验证本次只读行为应按稳定实体与原记录核对，不能回滚并行事实来凑“全库不变”。

本例实际方法及边界见[字体替换记录](../../histories/2026-10/20261022-1903-bilingual-whiteboard-fonts.md)。
