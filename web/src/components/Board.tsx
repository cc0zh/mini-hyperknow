import { useEffect, useId, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import katex from 'katex'
import { boardPrefix } from '../lib/lesson-state'
import { naturalSvgWidth } from '../lib/board-rendering'
import { boardFontFamily } from '../lib/board-fonts'
import type { BoardOperation, BoardScript } from '../lib/types'
import 'katex/dist/katex.min.css'

export function SafeText({ text }: { text: string }) {
  // React escapes all ordinary content. Only explicit HTTP(S) URLs become links.
  return <>{text.split(/(https?:\/\/[^\s<>"']+)/g).map((part, index) => /^https?:\/\//.test(part)
    ? <a key={index} href={part} target="_blank" rel="noopener noreferrer">{part}</a> : part)}</>
}

function RenderFailure({ message, retry }: { message: string; retry: () => void }) {
  return <div className="board-render-error" role="alert"><strong>板书渲染失败</strong><p>{message}</p><button type="button" onClick={retry}>重试渲染</button></div>
}

function Formula({ content }: { content: string }) {
  const [attempt, setAttempt] = useState(0)
  const target = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setError(null)
    try {
      if (target.current) katex.render(content, target.current, { displayMode: true, throwOnError: true, trust: false, strict: 'error', maxExpand: 500, maxSize: 20 })
    } catch (cause) { setError(cause instanceof Error ? cause.message : '公式无法排版。') }
  }, [content, attempt])
  return <>{error && <RenderFailure message={error} retry={() => setAttempt(value => value + 1)} />}<div className="board-formula" ref={target} hidden={!!error} /></>
}

const safeSvgProperties = new Set(['color', 'fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-dashoffset', 'fill-opacity', 'stroke-opacity', 'opacity', 'font-family', 'font-size', 'font-weight', 'font-style', 'text-anchor', 'dominant-baseline', 'visibility', 'display', 'rx', 'ry', 'background-color', 'line-height', 'paint-order', 'stroke-linecap', 'stroke-linejoin', 'vector-effect'])
function safeDeclarations(style: CSSStyleDeclaration): string {
  return [...style].flatMap(property => {
    if (!safeSvgProperties.has(property)) return []
    const value = style.getPropertyValue(property).trim()
    if (/\\|@|expression|javascript|data:|var\(/i.test(value)) return []
    if (/url\(/i.test(value) && !/^url\(["']?#[\w:.-]+["']?\)$/i.test(value)) return []
    return [`${property}:${property === 'font-family' ? boardFontFamily : value}`]
  }).join(';')
}

function cleanSvg(svg: string): string {
  const cleaned = DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true },
    FORBID_TAGS: ['foreignObject', 'script', 'iframe', 'image', 'use', 'animate', 'set'],
    FORBID_ATTR: ['onload', 'onclick', 'onerror'],
  })
  const document = new DOMParser().parseFromString(cleaned, 'image/svg+xml')
  if (document.querySelector('parsererror') || document.documentElement.localName !== 'svg') throw new Error('服务器图形未得到有效 SVG。')
  for (const element of document.querySelectorAll('*')) {
    // Keep the real chart's safe paints and typography, rather than turning
    // pie/sequence/class diagrams into undifferentiated black shapes.
    if (element.localName === 'style') {
      const sheet = new CSSStyleSheet()
      sheet.replaceSync(element.textContent || '')
      element.textContent = [...sheet.cssRules].flatMap(rule => {
        if (!(rule instanceof CSSStyleRule)) return []
        const declaration = safeDeclarations(rule.style)
        return declaration ? [`${rule.selectorText}{${declaration}}`] : []
      }).join('\n')
    }
    if (element.hasAttribute('style')) {
      const declaration = new Option().style
      declaration.cssText = element.getAttribute('style') || ''
      element.setAttribute('style', safeDeclarations(declaration))
    }
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase()
      const value = attribute.value.trim()
      if (name.startsWith('on') || ((name === 'href' || name === 'xlink:href') && !value.startsWith('#') && !/^https?:\/\//i.test(value)) ||
        (/url\(/i.test(value) && !/^url\(["']?#[\w:.-]+["']?\)$/i.test(value))) element.removeAttribute(attribute.name)
    }
    if (element.localName === 'a') { element.setAttribute('target', '_blank'); element.setAttribute('rel', 'noopener noreferrer') }
  }
  // Mermaid's natural max-width is stripped with untrusted layout CSS. Keep
  // the numeric viewBox width instead of stretching a narrow flowchart to
  // width="100%" and multiplying its height. CSS still shrinks wide charts.
  const root = document.documentElement
  const naturalWidth = naturalSvgWidth(root.getAttribute('viewBox'))
  if (naturalWidth !== null) root.setAttribute('width', String(naturalWidth))
  return new XMLSerializer().serializeToString(root)
}

let mermaidQueue: Promise<unknown> = Promise.resolve()
export function Mermaid({ content, fontReady }: { content: string; fontReady: boolean }) {
  const id = `board-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const [attempt, setAttempt] = useState(0)
  const [svg, setSvg] = useState('')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let stopped = false
    setSvg('')
    setError(null)
    if (!fontReady) return
    const render = async () => {
      if (stopped) return
      const { default: mermaid } = await import('mermaid')
      mermaid.initialize({
        startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true,
        fontFamily: boardFontFamily, htmlLabels: false,
        themeVariables: { fontFamily: boardFontFamily, fontSize: '22px' },
        flowchart: { htmlLabels: false, useMaxWidth: true },
        maxTextSize: 30_000, maxEdges: 150,
      })
      // Configuration directives could override label/font/security choices.
      // Reject them explicitly rather than silently rewriting teaching content.
      if (/%%\s*\{|^\s*---/m.test(content)) throw new Error('图形包含不允许的配置指令，请重试或检查讲义。')
      await document.fonts.ready
      const result = await mermaid.render(`${id}-${attempt}`, content)
      const safe = cleanSvg(result.svg)
      if (!stopped) setSvg(safe)
    }
    const job = mermaidQueue.then(render)
    mermaidQueue = job.catch(() => {})
    void job.catch(cause => { if (!stopped) setError(cause instanceof Error ? cause.message : '结构图无法绘制。') })
    return () => { stopped = true }
  }, [content, fontReady, attempt, id])
  if (error) return <RenderFailure message={error} retry={() => setAttempt(value => value + 1)} />
  if (!fontReady) return <div className="board-render-wait">结构图等待指定字体就绪；未使用源码替代。</div>
  if (!svg) return <div className="board-render-wait" role="status">正在排版结构图…</div>
  return <div className="board-mermaid" dangerouslySetInnerHTML={{ __html: svg }} />
}

function Operation({ operation, fontReady }: { operation: BoardOperation; fontReady: boolean }) {
  switch (operation.kind) {
    case 'text': return <p className="board-text"><SafeText text={operation.content} /></p>
    case 'list': return <div className="board-list">{operation.content && <p><SafeText text={operation.content} /></p>}<ul>{operation.items.map((item, index) => <li key={index}><SafeText text={item} /></li>)}</ul></div>
    case 'code': return <div className="board-code"><span>{operation.language || '代码'}</span><pre><code>{operation.content}</code></pre></div>
    case 'formula': return <Formula content={operation.content} />
    case 'box': return <div className="board-box"><SafeText text={operation.content} /></div>
    case 'arrow': return <div className="board-arrow"><span aria-hidden="true">⟶</span><span><SafeText text={operation.content} /></span></div>
    case 'highlight': return <p className="board-highlight"><mark><SafeText text={operation.content} /></mark></p>
    case 'mermaid': return <Mermaid content={operation.content} fontReady={fontReady} />
    default: return <RenderFailure message={`不支持的板书操作：${String((operation as BoardOperation).kind)}。内容未被静默忽略。`} retry={() => window.location.reload()} />
  }
}

export function Board({ script, cursor, fontReady }: { script: BoardScript; cursor: number; fontReady: boolean }) {
  const columns = boardPrefix(script, cursor)
  const [review, setReview] = useState<string | null>(null)
  const current = script.steps[cursor]
  const active = columns.find(item => item.page === current?.page && item.column === current.column)
  // Playback owns the confirmed cursor; review owns only this display selection.
  const selected = columns.find(item => `${item.page}:${item.column}` === review) ?? active
  return <section className={`lesson-board ${fontReady ? 'font-ready' : 'font-fallback'}`} aria-label="课堂白板">
    <div className="board-toolbar"><span>WHITEBOARD / {script.steps.length} 步</span><span>{review ? '独立回看' : '跟随课堂'}</span></div>
    <div className="board-paper"><h2>{script.title}</h2>{selected ? selected.steps.map(step => <section className="board-step" key={step.step_id}><h3>{step.title}</h3>{step.operations.map((operation, index) => <Operation key={`${step.step_id}-${index}`} operation={operation} fontReady={fontReady} />)}</section>) : <p className="board-empty">讲义已经保存。点击“开始播放”或“下一步”展开第一步。</p>}</div>
    <nav className="board-pages" aria-label="已展示板书页栏">{columns.map(item => <button type="button" key={`${item.page}:${item.column}`} className={selected === item ? 'selected' : ''} onClick={() => setReview(`${item.page}:${item.column}`)}>第 {item.page} 页 · {item.column} 栏</button>)}{review && <button type="button" onClick={() => setReview(null)}>回到当前课堂</button>}</nav>
  </section>
}
