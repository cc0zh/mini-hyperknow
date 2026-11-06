﻿import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import DOMPurify from 'dompurify'
import katex from 'katex'
import { cameraForFocus, diagramEdgeGeometry, layoutBoard, sceneFocus, visibleScene, zoomCamera } from '../lib/board-scene'
import type { Camera, SceneObject } from '../lib/board-scene'
import { isBoardFrames, isBoardScriptV2 } from '../lib/board-protocol'
import { fitToWidth, formulaOptions, naturalSvgWidth } from '../lib/board-rendering'
import { boardFontFamily } from '../lib/board-fonts'
import type { BoardFrame, BoardOperation, BoardScript } from '../lib/types'
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
    const element = target.current
    if (!element) return
    let disposed = false
    let observer: ResizeObserver | undefined
    try {
      katex.render(content, element, formulaOptions)
      const fit = () => {
        if (disposed) return
        element.style.removeProperty('font-size')
        const base = parseFloat(getComputedStyle(element).fontSize)
        const ink = element.querySelector<HTMLElement>('.katex-html')
        if (ink) {
          // KaTeX's HTML wrapper stretches to its container, not to the
          // overflowing expression. Measure its contents and undo canvas zoom.
          const range = document.createRange()
          range.selectNodeContents(ink)
          const scale = element.getBoundingClientRect().width / element.offsetWidth
          const naturalWidth = range.getBoundingClientRect().width / scale
          element.style.fontSize = `${base * fitToWidth(naturalWidth, Math.max(1, element.clientWidth - 4))}px`
        }
      }
      let lastWidth = element.clientWidth
      fit()
      observer = new ResizeObserver(() => {
        if (element.clientWidth !== lastWidth) { lastWidth = element.clientWidth; fit() }
      })
      observer.observe(element)
      void document.fonts.ready.then(fit)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '公式无法排版。') }
    return () => { disposed = true; observer?.disconnect() }
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
    case 'table': return <div className="board-table-wrap">{operation.content && <p><SafeText text={operation.content} /></p>}<table className="board-table"><thead><tr>{operation.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead><tbody>{operation.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>
    case 'circle': return <p className="board-circle-text"><SafeText text={operation.content} /></p>
    default: return <RenderFailure message={`不支持的板书操作：${String((operation as BoardOperation).kind)}。内容未被静默忽略。`} retry={() => window.location.reload()} />
  }
}

function svgLines(text: string, width: number, fontSize = 20): string[] {
  const result: string[] = []
  let line = '', size = 0
  for (const character of text) {
    const length = character.codePointAt(0)! > 255 ? fontSize : fontSize * .58
    if (character === '\n' || size + length > width) { result.push(line); line = ''; size = 0 }
    if (character !== '\n') { line += character; size += length }
  }
  return [...result, line]
}

function Diagram({ object, select, selectedId, focusedIds }: { object: SceneObject; select: (id: string) => void; selectedId?: string | null; focusedIds?: readonly string[] }) {
  const marker = `arrow-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  return <svg className="board-diagram" width={object.width} height={object.height} viewBox={`0 0 ${object.width} ${object.height}`} aria-label={object.operation.content || '节点关系图'}>
    <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
    {object.operation.content && <text x="10" y="54" className="diagram-caption">{svgLines(object.operation.content, object.width - 24).map((line, index) => <tspan key={index} x="10" dy={index ? 30 : 0}>{line}</tspan>)}</text>}
    {object.operation.edges.map((edge, index) => {
      const from = object.nodes.find(node => node.id === edge.from_id), to = object.nodes.find(node => node.id === edge.to_id)
      if (!from || !to) return null
      const rightBoundary = Math.max(...object.nodes.map(node => node.x - object.x + node.width))
      const geometry = diagramEdgeGeometry({ ...from, x: from.x - object.x, y: from.y - object.y }, { ...to, x: to.x - object.x, y: to.y - object.y }, index, rightBoundary)
      const lines = svgLines(edge.label, 96, 16)
      const labelY = geometry.labelY - (from.y === to.y ? (lines.length - 1) * 22 : 0)
      return <g key={`${edge.from_id}:${edge.to_id}:${index}`} className="diagram-edge" style={{ '--reveal-delay': `${(index + object.nodes.length) * 100}ms` } as CSSProperties}><path d={geometry.path} markerEnd={`url(#${marker})`} />{edge.label && <text x={geometry.labelX} y={labelY}>{lines.map((line, lineIndex) => <tspan key={lineIndex} x={geometry.labelX} dy={lineIndex ? 22 : 0}>{line}</tspan>)}</text>}</g>
    })}
    {object.nodes.map((node, index) => <g key={node.id} data-object-id={node.id} role="button" tabIndex={0} aria-label={`选择图节点：${node.label}`} className={`diagram-node ${node.id === selectedId ? 'selected' : ''} ${focusedIds?.includes(node.id) ? 'focus-target' : ''}`} transform={`translate(${node.x - object.x}, ${node.y - object.y})`} style={{ '--reveal-delay': `${index * 100}ms` } as CSSProperties} onClick={event => { event.stopPropagation(); select(node.id) }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); select(node.id) } }}><rect width={node.width} height={node.height} rx="12" /><text x={node.width / 2} y="26" textAnchor="middle">{svgLines(node.label, node.width - 24).map((line, lineIndex) => <tspan key={lineIndex} x={node.width / 2} dy={lineIndex ? 28 : 0}>{line}</tspan>)}</text></g>)}
  </svg>
}

function Annotation({ object }: { object: SceneObject }) {
  const marker = `annotation-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const operation = object.operation
  return <svg className={`scene-annotation scene-${operation.kind}`} style={{ left: 0, top: 0, width: '100%', height: '100%' }} aria-label={operation.content || `${operation.kind === 'circle' ? '圈出' : '强调'}已展示对象`}>
    <title>{operation.content}</title>
    <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10z" fill="currentColor" /></marker></defs>
    {operation.kind === 'arrow' && object.targets.length > 1 ? object.targets.slice(1).map(target => { const from = object.targets[0].rect, to = target.rect; return <path key={target.id} d={`M${from.x + from.width},${from.y + from.height / 2} Q${from.x + from.width + 40},${to.y + to.height / 2} ${to.x},${to.y + to.height / 2}`} markerEnd={`url(#${marker})`} /> }) : object.targets.map(target => operation.kind === 'circle'
      ? <ellipse key={target.id} cx={target.rect.x + target.rect.width / 2} cy={target.rect.y + target.rect.height / 2} rx={target.rect.width / 2 + 10} ry={target.rect.height / 2 + 10} />
      : <rect key={target.id} x={target.rect.x - 6} y={target.rect.y - 4} width={target.rect.width + 12} height={target.rect.height + 8} rx="9" />)}
  </svg>
}

interface SceneBoardProps {
  script: { title: string; steps: BoardFrame[] }
  cursor: number
  fontReady: boolean
  focusIds?: readonly string[]
  selectedObjectId?: string | null
  focusRequest?: number
  onSelectObject?: (id: string) => void
  onReturnCurrent?: () => void
}

interface BoardProps extends SceneBoardProps { script: BoardScript }

export function Board(props: BoardProps) {
  if (!isBoardScriptV2(props.script)) return <div className="board-render-error" role="alert"><strong>不支持的白板协议</strong><p>此讲义不是完整的新课堂协议，未转换或自动重新生成。请返回课堂明确重新生成。</p></div>
  return <SceneBoard {...props} focusIds={props.script.steps[props.cursor]?.focus_ids} />
}

export function AssistanceBoardCanvas({ title, frames, cursor, fontReady }: { title: string; frames: BoardFrame[]; cursor: number; fontReady: boolean }) {
  const script = useMemo(() => ({ title, steps: frames }), [title, frames])
  if (!isBoardFrames(frames)) return <div className="board-render-error" role="alert"><strong>不支持的独立白板协议</strong><p>缺少新协议的对象身份或引用。未转换旧产物；请返回会话明确请求新的白板。</p></div>
  return <SceneBoard script={script} cursor={cursor} fontReady={fontReady} />
}

function SceneBoard({ script, cursor, fontReady, focusIds, selectedObjectId, focusRequest = 0, onSelectObject, onReturnCurrent }: SceneBoardProps) {
  const scene = useMemo(() => layoutBoard(script), [script])
  const visible = useMemo(() => visibleScene(scene, cursor), [scene, cursor])
  const viewport = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointerId: number; x: number; y: number; camera: Camera } | null>(null)
  const [camera, setCamera] = useState<Camera>({ x: 24, y: 24, zoom: 1 })
  const [following, setFollowing] = useState(true)
  const [overview, setOverview] = useState(true)
  const [size, setSize] = useState({ width: 900, height: 650 })
  const lastRequest = useRef(focusRequest)
  const current = script.steps[cursor]
  const currentRegion = scene.regions.find(region => region.stepIndex === cursor)
  const select = (id: string) => onSelectObject?.(id)
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const explicit = lastRequest.current !== focusRequest
    lastRequest.current = focusRequest
    if (!following && !explicit) return
    const detail = explicit ? !!selectedObjectId : !overview
    const focus = sceneFocus(scene, cursor, detail ? selectedObjectId : null, focusIds)
    if (focus) setCamera(cameraForFocus(focus, size))
    if (explicit) { setFollowing(true); setOverview(!selectedObjectId) }
  }, [scene, cursor, following, focusRequest, selectedObjectId, focusIds, size, overview])
  function pan(x: number, y: number) { setFollowing(false); setCamera(value => ({ ...value, x: value.x + x, y: value.y + y })) }
  function zoom(factor: number) { setFollowing(false); setCamera(value => zoomCamera(value, factor, { x: size.width / 2, y: size.height / 2 })) }
  function returnCurrent() {
    onReturnCurrent?.()
    setFollowing(true); setOverview(true)
    const focus = sceneFocus(scene, cursor, null, focusIds)
    if (focus) setCamera(cameraForFocus(focus, size))
  }
  function showStep() {
    setFollowing(true); setOverview(true)
    const focus = sceneFocus(scene, cursor, null, focusIds)
    if (focus) setCamera(cameraForFocus(focus, size))
  }
  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    const moves: Record<string, [number, number]> = { ArrowLeft: [100, 0], ArrowRight: [-100, 0], ArrowUp: [0, 100], ArrowDown: [0, -100] }
    if (moves[event.key]) { event.preventDefault(); pan(...moves[event.key]) }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.15) }
    if (event.key === '-') { event.preventDefault(); zoom(1 / 1.15) }
    if (event.key === 'Home') { event.preventDefault(); returnCurrent() }
  }
  return <section className={`lesson-board scene-board ${fontReady ? 'font-ready' : 'font-fallback'}`} aria-label="课堂白板">
    <div className="board-toolbar"><span>{currentRegion ? `第 ${currentRegion.page} 步 · ${selectedObjectId && !overview ? '局部放大' : '本步全览'}` : '课堂白板'} · {following ? '自动跟随' : '自由浏览'}</span><span>按编号阅读 · 点选放大 · 拖动浏览</span></div>
    <div ref={viewport} className={`board-viewport ${following ? 'is-following' : ''}`} data-view-mode={overview || !selectedObjectId ? 'overview' : 'detail'} tabIndex={0} role="region" aria-label="可缩放累积白板，方向键平移，加减号缩放，Home回到当前讲解" onKeyDown={keyboard}
      onWheel={event => { setFollowing(false); if (event.ctrlKey || event.metaKey) { event.preventDefault(); setCamera(value => zoomCamera(value, event.deltaY < 0 ? 1.08 : 1 / 1.08, { x: event.clientX - event.currentTarget.getBoundingClientRect().left, y: event.clientY - event.currentTarget.getBoundingClientRect().top })) } else pan(-event.deltaX, -event.deltaY) }}
      onPointerDown={event => { if (event.button !== 0 || (event.target as Element).closest('a,button,[data-object-id]')) return; drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, camera }; event.currentTarget.setPointerCapture(event.pointerId) }}
      onPointerMove={event => { const start = drag.current; if (!start || start.pointerId !== event.pointerId) return; setFollowing(false); setCamera({ ...start.camera, x: start.camera.x + event.clientX - start.x, y: start.camera.y + event.clientY - start.y }) }}
      onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}>
      <div className="board-scene board-paper" style={{ width: scene.width, height: scene.height, transform: `translate(${camera.x}px,${camera.y}px) scale(${camera.zoom})` }}>
        <h2 className="scene-title">{script.title}</h2>
        {!current && <p className="board-empty">讲义已保存。点击“开始播放”或“下一步”展开本课路线图。</p>}
        {visible.regions.map(region => <section key={region.stepIndex} data-step-region={region.stepIndex} className={`scene-step-frame ${region.stepIndex === cursor ? 'current' : ''}`} style={{ left: region.x, top: region.y, width: region.width, height: region.height }} aria-label={`第${region.stepIndex + 1}步板书`}><h3 className="scene-step-title"><span>{String(region.stepIndex + 1).padStart(2, '0')}</span>{region.step.title}</h3></section>)}
        {visible.objects.map(object => object.targets.length ? <Annotation key={object.id} object={object} /> : <div key={object.id} data-object-id={object.id} data-step-index={object.stepIndex} data-operation-index={object.operationIndex} className={`scene-object ${object.stepIndex === cursor ? 'just-revealed' : ''} ${object.id === selectedObjectId ? 'selected' : ''} ${focusIds?.includes(object.id) ? 'focus-target' : ''}`} style={{ left: object.x, top: object.y, width: object.width, height: object.height, '--reveal-delay': `${object.operationIndex * 140}ms` } as CSSProperties} role="button" tabIndex={0} aria-label={`选择板书对象：${object.operation.content || object.operation.kind}`} onClick={() => select(object.id)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); select(object.id) } }}>
          <span className="scene-object-order" aria-hidden="true">{String(object.operationIndex + 1).padStart(2, '0')}</span>
          {object.operation.kind === 'diagram' ? <Diagram object={object} select={select} selectedId={selectedObjectId} focusedIds={focusIds} /> : <div className="scene-object-ink"><Operation operation={object.operation} fontReady={fontReady} /></div>}
        </div>)}
      </div>
    </div>
    <div className="board-camera-controls" aria-label="白板视图控制"><div><button type="button" aria-label="向左浏览白板" onClick={() => pan(140, 0)}>←</button><button type="button" aria-label="向上浏览白板" onClick={() => pan(0, 140)}>↑</button><button type="button" aria-label="向下浏览白板" onClick={() => pan(0, -140)}>↓</button><button type="button" aria-label="向右浏览白板" onClick={() => pan(-140, 0)}>→</button></div><div><button type="button" aria-label="缩小白板" onClick={() => zoom(1 / 1.15)}>−</button><output aria-label="白板缩放比例">{Math.round(camera.zoom * 100)}%</output><button type="button" aria-label="放大白板" onClick={() => zoom(1.15)}>+</button></div><button type="button" className="return-to-current" disabled={!current} onClick={showStep}>本步全览</button><button type="button" className="return-to-current" onClick={returnCurrent}>回到当前讲解</button></div>
  </section>
}
