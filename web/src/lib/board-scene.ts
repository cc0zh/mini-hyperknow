import type { BoardFrame, BoardOperation } from './types.ts'

export interface Rect { x: number; y: number; width: number; height: number }
export interface SceneNode extends Rect { id: string; label: string }
export interface SceneObject extends Rect {
  id: string
  stepIndex: number
  operationIndex: number
  operation: BoardOperation
  nodes: SceneNode[]
  targets: { id: string; rect: Rect }[]
}
export interface SceneRegion extends Rect { stepIndex: number; step: BoardFrame; page: number; column: number }
export interface BoardScene { objects: SceneObject[]; regions: SceneRegion[]; width: number; height: number }
export interface Camera { x: number; y: number; zoom: number }

const COLUMN_WIDTH = 600
const SHEET_WIDTH = 1280
const COLUMN_GAP = 32
const MARGIN = 48
const LINE = 30
const annotation = (operation: BoardOperation) => ['highlight', 'circle', 'arrow'].includes(operation.kind) && operation.target_ids.length > 0

// Conservative font-independent measurement: Chinese characters use a full em,
// ASCII a little over half. Wrapping and deliberate reserves keep later regions
// independent of asynchronous font / KaTeX / Mermaid rendering.
export function textLines(text: string, width: number, fontSize = 22): number {
  return text.split('\n').reduce((sum, line) => {
    const units = Array.from(line).reduce((n, char) => n + (char.codePointAt(0)! > 255 ? 1 : .58), 0)
    // A cell that fits 6.5 em still holds only six whole CJK characters.
    // Fractional capacity otherwise undercounts wrapped lines in narrow tables.
    const capacity = Math.max(1, Math.floor(width / fontSize))
    return sum + Math.max(1, Math.ceil(units / capacity))
  }, 0)
}

export function diagramNodes(operation: BoardOperation, width = COLUMN_WIDTH): SceneNode[] {
  // Stable topological layers, with cycles placed in their declared order.
  const ranks = new Map(operation.nodes.map(node => [node.id, 0]))
  const indegree = new Map(operation.nodes.map(node => [node.id, 0]))
  for (const edge of operation.edges) if (indegree.has(edge.to_id)) indegree.set(edge.to_id, indegree.get(edge.to_id)! + 1)
  const queue = operation.nodes.filter(node => indegree.get(node.id) === 0).map(node => node.id)
  for (let index = 0; index < queue.length; index += 1) {
    const id = queue[index]
    for (const edge of operation.edges.filter(item => item.from_id === id)) {
      if (!ranks.has(edge.to_id)) continue
      ranks.set(edge.to_id, Math.max(ranks.get(edge.to_id)!, ranks.get(id)! + 1))
      indegree.set(edge.to_id, indegree.get(edge.to_id)! - 1)
      if (indegree.get(edge.to_id) === 0) queue.push(edge.to_id)
    }
  }
  // Kahn's traversal leaves a directed cycle unranked. Lay out its spanning
  // path in declaration order instead of piling every node into one layer.
  const visited = new Set(queue)
  const active = new Set<string>()
  function walk(id: string) {
    visited.add(id); active.add(id)
    for (const edge of operation.edges.filter(item => item.from_id === id)) {
      if (active.has(edge.to_id) || visited.has(edge.to_id)) continue
      ranks.set(edge.to_id, ranks.get(id)! + 1)
      walk(edge.to_id)
    }
    active.delete(id)
  }
  operation.nodes.forEach(node => { if (!visited.has(node.id)) walk(node.id) })
  const ordered = [...operation.nodes].sort((a, b) => ranks.get(a.id)! - ranks.get(b.id)!)
  const columns = Math.min(3, Math.max(1, Math.floor((width - 128) / 220)))
  const nodeWidth = (width - 160 - (columns - 1) * 48) / columns
  const result: SceneNode[] = []
  let y = 78 + (operation.content ? textLines(operation.content, width - 24, 20) * LINE + 24 : 0)
  for (let offset = 0; offset < ordered.length; offset += columns) {
    const row = ordered.slice(offset, offset + columns)
    const height = Math.max(72, ...row.map(node => textLines(node.label, nodeWidth - 24, 20) * 28 + 28))
    row.forEach((node, index) => {
      const column = Math.floor(offset / columns) % 2 ? columns - 1 - index : index
      result.push({ id: node.id, label: node.label, x: 16 + column * (nodeWidth + 48), y, width: nodeWidth, height })
    })
    y += height + 72
  }
  return operation.nodes.map(node => result.find(position => position.id === node.id)!)
}

export function operationHeight(operation: BoardOperation, width = COLUMN_WIDTH): number {
  if (annotation(operation)) return 0
  switch (operation.kind) {
    case 'diagram': return Math.max(130, ...diagramNodes(operation, width).map(node => node.y + node.height)) + 50
    case 'table': {
      const cellWidth = (width - 20) / Math.max(1, operation.columns.length) - 20
      return (operation.content ? textLines(operation.content, width) * LINE + 16 : 0) +
        [operation.columns, ...operation.rows].reduce((height, row) => height + Math.max(1, ...row.map(value => textLines(value, cellWidth, 19))) * 26 + 23, 0) + 40 +
        (operation.content ? textLines(operation.content, width - 24) * LINE + 12 : 0)
    }
    case 'list': return (operation.content ? textLines(operation.content, width - 20) * LINE + 10 : 0) + operation.items.reduce((height, item) => height + textLines(item, width - 48) * LINE + 8, 0) + 56
    case 'code': return textLines(operation.content, width - 48, 16.5) * 24 + 84
    case 'formula': return Math.max(120, textLines(operation.content, width - 40, 22) * 36 + 64)
    case 'mermaid': return 420
    default: return textLines(operation.content, width - 40) * LINE + 64
  }
}

export function diagramEdgeGeometry(from: Rect, to: Rect, lane = 0, rightBoundary = 0): { path: string; labelX: number; labelY: number } {
  if (to.y > from.y + from.height) {
    const x1 = from.x + from.width / 2, y1 = from.y + from.height
    const x2 = to.x + to.width / 2, y2 = to.y, mid = (y1 + y2) / 2
    return { path: `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`, labelX: (x1 + x2) / 2 + 10, labelY: mid }
  }
  if (from.y === to.y && from.x !== to.x) {
    const forward = to.x > from.x
    const x1 = forward ? from.x + from.width : from.x, y1 = from.y + from.height / 2
    const x2 = forward ? to.x : to.x + to.width, y2 = to.y + to.height / 2
    if (Math.abs(to.x - from.x) > Math.max(from.width, to.width) * 1.8) {
      const top = from.y - 32 - lane % 2 * 16
      return { path: `M${from.x + from.width / 2},${from.y} Q${(from.x + to.x) / 2},${top - 32} ${to.x + to.width / 2},${to.y}`, labelX: (from.x + to.x + from.width) / 2, labelY: top - 10 }
    }
    return { path: `M${x1},${y1} L${x2},${y2}`, labelX: (x1 + x2) / 2, labelY: Math.min(from.y, to.y) - 14 }
  }
  const x1 = from.x + from.width, y1 = from.y + from.height / 2
  const x2 = to.x + to.width, y2 = to.y + to.height / 2
  const gutter = Math.max(x1, x2, rightBoundary) + 28 + lane % 2 * 12
  return { path: `M${x1},${y1} C${gutter},${y1 + 40} ${gutter},${y2 - 40} ${x2},${y2}`, labelX: gutter + 4, labelY: (y1 + y2) / 2 }
}

export function unionRects(rects: readonly Rect[]): Rect | null {
  if (!rects.length) return null
  const x = Math.min(...rects.map(rect => rect.x))
  const y = Math.min(...rects.map(rect => rect.y))
  return { x, y, width: Math.max(...rects.map(rect => rect.x + rect.width)) - x, height: Math.max(...rects.map(rect => rect.y + rect.height)) - y }
}

/** Layout the saved script once, then reveal only its confirmed prefix. No
 * model coordinates, DOM measurement, random IDs, or prefix-dependent reflow. */
export function layoutBoard(script: { steps: BoardFrame[] }): BoardScene {
  const regions: SceneRegion[] = []
  const objects: SceneObject[] = []
  // Each teaching step owns one bounded sheet. Partition its ordered blocks
  // into balanced, contiguous columns; never scatter a step across pages.
  let pageY = 100
  script.steps.forEach((step, stepIndex) => {
    const blocks = step.operations.map((operation, operationIndex) => ({ operation, operationIndex })).filter(block => !annotation(block.operation))
    const innerWidth = SHEET_WIDTH - 48
    const headerHeight = textLines(step.title, innerWidth - 100, 28) * 38 + 36
    let columns = 1, cut = blocks.length, width = innerWidth
    let heights = blocks.map(block => operationHeight(block.operation, width))
    let height = heights.reduce((sum, value) => sum + value + 20, 0)
    if (blocks.length > 1) {
      const narrow = (innerWidth - COLUMN_GAP) / 2
      const candidates = blocks.map(block => operationHeight(block.operation, narrow))
      for (let split = 1; split < blocks.length; split += 1) {
        const candidate = Math.max(candidates.slice(0, split).reduce((sum, value) => sum + value + 20, 0), candidates.slice(split).reduce((sum, value) => sum + value + 20, 0))
        if (candidate < height * .97) { columns = 2; cut = split; width = narrow; heights = candidates; height = candidate }
      }
    }
    const bottoms = [pageY + headerHeight, pageY + headerHeight]
    blocks.forEach(({ operation, operationIndex }, index) => {
      const column = index < cut ? 0 : 1
      const x = MARGIN + 24 + column * (width + COLUMN_GAP), y = bottoms[column]
      const nodes = operation.kind === 'diagram' ? diagramNodes(operation, width).map(node => ({ ...node, x: x + node.x, y: y + node.y })) : []
      objects.push({ id: operation.object_id, stepIndex, operationIndex, operation, x, y, width, height: heights[index], nodes, targets: [] })
      bottoms[column] = y + heights[index] + 20
    })
    const sheetHeight = Math.max(240, headerHeight + height + 20)
    regions.push({ stepIndex, step, page: stepIndex + 1, column: columns, x: MARGIN, y: pageY, width: SHEET_WIDTH, height: sheetHeight })
    pageY += sheetHeight + 100
  })
  // Resolve references only to objects/nodes introduced earlier (including an
  // earlier operation of the same step). Invalid links are protocol errors,
  // never invented stand-ins or content copies.
  const refs = new Map<string, { rect: Rect; stepIndex: number; operationIndex: number }>()
  for (const object of objects) {
    refs.set(object.id, { rect: object, stepIndex: object.stepIndex, operationIndex: object.operationIndex })
    object.nodes.forEach(node => refs.set(node.id, { rect: node, stepIndex: object.stepIndex, operationIndex: object.operationIndex }))
  }
  script.steps.forEach((step, stepIndex) => step.operations.forEach((operation, operationIndex) => {
    if (!annotation(operation)) return
    const targets = operation.target_ids.map(id => {
      const ref = refs.get(id)
      return ref && (ref.stepIndex < stepIndex || ref.stepIndex === stepIndex && ref.operationIndex < operationIndex) ? { id, rect: ref.rect } : null
    }).filter((target): target is { id: string; rect: Rect } => target !== null)
    const rect = unionRects(targets.map(target => target.rect))
    if (rect) objects.push({ ...rect, id: operation.object_id, stepIndex, operationIndex, operation, targets, nodes: [] })
  }))
  objects.sort((a, b) => a.stepIndex - b.stepIndex || a.operationIndex - b.operationIndex)
  regions.sort((a, b) => a.stepIndex - b.stepIndex)
  return { objects, regions, width: MARGIN * 2 + SHEET_WIDTH, height: Math.max(800, pageY) }
}

export function confirmedCursor(viewCursor: number, teachingCursor: number): number {
  return Math.max(-1, Math.min(Math.trunc(viewCursor), teachingCursor))
}

export function visibleScene(scene: BoardScene, cursor: number): BoardScene {
  return { ...scene, objects: scene.objects.filter(object => object.stepIndex <= cursor), regions: scene.regions.filter(region => region.stepIndex <= cursor) }
}

export function sceneFocus(scene: BoardScene, cursor: number, objectId?: string | null, focusIds: readonly string[] = []): Rect | null {
  const visible = visibleScene(scene, cursor)
  const region = visible.regions.find(item => item.stepIndex === cursor)
  // Following shows the complete current sheet. Model focus IDs may guide
  // emphasis, but must not crop away the rest of this step's board.
  if (!objectId && visible.objects.some(object => object.stepIndex === cursor && !object.targets.length)) return region ?? null
  const ids = objectId ? [objectId] : focusIds
  const rects = ids.flatMap(id => visible.objects.flatMap<Rect>(object => object.id === id ? [object] : object.nodes.filter(node => node.id === id)))
  const focus = unionRects(rects)
  // Keep this step's heading with its ink. A cross-step emphasis deliberately
  // focuses its older target instead of the empty annotation's new region.
  if (!objectId && focus && region && focus.y >= region.y && focus.y <= region.y + 130 && focus.y + focus.height <= region.y + region.height) {
    return unionRects([focus, { x: region.x, y: region.y, width: region.width, height: 50 }])
  }
  return focus ?? region ?? null
}

export function cameraForFocus(rect: Rect, viewport: { width: number; height: number }): Camera {
  const scale = Math.min(1.2, Math.max(1, viewport.width - 48) / rect.width, Math.max(1, viewport.height - 48) / rect.height)
  return { zoom: scale, x: (viewport.width - rect.width * scale) / 2 - rect.x * scale, y: (viewport.height - rect.height * scale) / 2 - rect.y * scale }
}

export function zoomCamera(camera: Camera, factor: number, point: { x: number; y: number }): Camera {
  const zoom = Math.max(Math.min(.05, camera.zoom), Math.min(2, camera.zoom * factor))
  const ratio = zoom / camera.zoom
  return { zoom, x: point.x - (point.x - camera.x) * ratio, y: point.y - (point.y - camera.y) * ratio }
}
