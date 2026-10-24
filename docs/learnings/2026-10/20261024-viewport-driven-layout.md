# 同一份内容，两种布局：别用 CSS 硬撑

从 [图标系统与外壳改造](../../histories/2026-10/20261024-0030-shell-icons-and-gallery.md) 提炼。

## 是什么

「响应式」常被理解成"用媒体查询改一套样式"。但当**同一个内容在两套布局里要出现在不同容器中**时，CSS 改不出来——那已经不是样式差异，是结构差异。

本项目里课程设计工作台的「参考资料」区块就是这种情况：宽屏它应该在右栏独立成列，窄屏右栏被隐藏，它得回到左栏内联显示。

## 为什么需要

第一反应通常是把 DOM 写两遍，靠 CSS 各藏一个：

```tsx
<aside className="wb-rail"><RunResearch /></aside>       {/* 宽屏显示 */}
<div className="wb-research-inline"><RunResearch /></div> {/* 窄屏显示 */}
```

```css
.wb-research-inline { display: none; }
@media (max-width: 1100px) { .wb-rail { display: none; } .wb-research-inline { display: block; } }
```

能跑，但代价是隐形的：

- 两棵子树都被 React 渲染，`RunResearch` 里若有 `useEffect`、订阅或请求，会**执行两次**。
- 两个 DOM 有相同的文本，屏幕阅读器在展开/收起边界状态时可能读到重复内容。
- e2e 里 `.wb-research-disclosure > summary` 这类选择器会命中两个元素，Playwright 直接抛 strict mode violation——**本项目就是在这一步踩到的**。

## 怎么用

让渲染结构跟着视口走，一处渲染：

```ts
// lib/use-media-query.ts
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches)

  useEffect(() => {
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener('change', update)
    return () => list.removeEventListener('change', update)
  }, [query])

  return matches
}
```

```tsx
const narrowRail = useMediaQuery('(max-width: 1100px)')

{!narrowRail && <aside className="wb-rail"><RunResearch /></aside>}
{narrowRail && <div className="wb-research-inline"><RunResearch /></div>}
```

注意 `useState` 用惰性初始化而不是 `useEffect` 里置初值——后者会在首帧先渲染错误分支再切换，窄屏上闪一下。

## 核心要点

1. **判断标准**：内容在两个断点下的**容器归属**是否变化。只是尺寸、间距、列数变化 → 纯 CSS。换了父容器 → 用视口驱动渲染。
2. `matchMedia` 比 `window.innerWidth` + resize 监听好：它是浏览器原生优化的事件源，且能直接表达 `prefers-reduced-motion`、`(hover: hover)` 这类能力查询，不必为此再造一套机制。
3. 断点数值要和 CSS 里的一致。本项目右栏在 `@media (max-width: 1100px)` 隐藏，JS 就必须问 `1100px`，否则会出现"两个都没渲染"或"两个都渲染"的空窗。

## 常见陷阱

**把 `useMediaQuery` 当成万能布局工具。** 一旦开始用它决定大部分结构，CSS 就退化成了附带的配色表，而且首帧一定会有一次抖动。它只该用在"DOM 结构真的不同"的少数地方，本仓库目前只有这一处。

**忘记 SSR/无 `window` 环境。** 惰性初始化里要判 `typeof window === 'undefined'`。哪怕当前是纯客户端 Vite 项目，测试与未来预渲染都会撞上。

**在 `useEffect` 里 `addEventListener('resize')` 自己算宽度。** 能用，但会漏掉浏览器缩放、方向切换、以及 devtools 的设备模拟；`matchMedia` 把这些都覆盖了。
