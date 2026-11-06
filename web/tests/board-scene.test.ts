import test from 'node:test'
import assert from 'node:assert/strict'
import { textLines } from '../src/lib/board-scene.ts'
import { cameraForFocus, confirmedCursor, diagramEdgeGeometry, diagramNodes, layoutBoard, operationHeight, sceneFocus, visibleScene, zoomCamera } from '../src/lib/board-scene.ts'
import { isBoardFrames, isBoardScriptV2 } from '../src/lib/board-protocol.ts'
import { questionAnchor, summaryIsShown } from '../src/lib/lesson-state.ts'
import type { BoardOperation, BoardScript, BoardStep } from '../src/lib/types.ts'

// Geometry / transition inputs only, not a replacement teaching service.
const operation = (id: string, patch: Partial<BoardOperation> = {}): BoardOperation => ({ object_id: id, kind: 'text', content: '布局状态', items: [], language: '', target_ids: [], columns: [], rows: [], nodes: [], edges: [], ...patch })
const step = (id: string, operations: BoardOperation[], patch: Partial<BoardStep> = {}): BoardStep => ({ step_id: id, title: id, narration: '状态测试', page: 1, column: 1, stage: 'explain', keypoint_id: 'k1', focus_ids: [], check: null, operations, ...patch })
function script(): BoardScript {
  return { script_id: 'geometry', session_id: 'state', course_id: 'state', content_version: 1, schema_version: 2, title: '几何与恢复测试', objectives: ['验证布局'], roadmap: [{ keypoint_id: 'k1', source_keypoint_index: 0, title: '布局', question: '如何保持稳定？' }], created_at: '', steps: [
    step('opening', [operation('intro')], { stage: 'opening', keypoint_id: null }),
    step('diagram', [operation('graph', { kind: 'diagram', nodes: [{ id: 'n1', label: '开始' }, { id: 'n2', label: '下一步' }, { id: 'n3', label: '完成' }], edges: [{ from_id: 'n1', to_id: 'n2', label: '继续' }, { from_id: 'n2', to_id: 'n3', label: '' }] })], { column: 2, focus_ids: ['n2'] }),
    step('table', [operation('comparison', { kind: 'table', columns: ['条件', '结果'], rows: [['一', '二'], ['长内容'.repeat(30), '三']] })], { stage: 'example' }),
    step('check', [operation('mark-node', { kind: 'highlight', target_ids: ['n2'] }), operation('circle-intro', { kind: 'circle', target_ids: ['intro'] })], { stage: 'check', check: { question: '说说你的想法', expected_answer: '只用于显式展开' }, focus_ids: ['n2'] }),
    step('summary', [operation('recap')], { stage: 'summary', keypoint_id: null, page: 2 }),
  ] }
}

test('only the explicit complete v2 fields are accepted; no legacy conversion', () => {
  const value = script()
  assert.equal(isBoardScriptV2(value), true)
  assert.equal(isBoardScriptV2({ ...value, schema_version: 1 }), false)
  for (const key of ['objectives', 'roadmap']) { const input = structuredClone(value) as unknown as Record<string, unknown>; delete input[key]; assert.equal(isBoardScriptV2(input), false, key) }
  for (const key of ['stage', 'keypoint_id', 'focus_ids', 'check']) { const input = structuredClone(value); delete (input.steps[0] as unknown as Record<string, unknown>)[key]; assert.equal(isBoardScriptV2(input), false, key) }
  for (const key of ['object_id', 'target_ids', 'columns', 'rows', 'nodes', 'edges']) { const input = structuredClone(value); delete (input.steps[0].operations[0] as unknown as Record<string, unknown>)[key]; assert.equal(isBoardScriptV2(input), false, key) }
  const missingIndex = structuredClone(value); delete (missingIndex.roadmap[0] as unknown as Record<string, unknown>).source_keypoint_index
  assert.equal(isBoardScriptV2(missingIndex), false)
})

test('IDs must be unique and emphasis may only target already introduced objects/nodes', () => {
  const duplicate = script(); duplicate.steps[1].operations[0].nodes[0].id = 'intro'
  assert.equal(isBoardScriptV2(duplicate), false)
  const future = script(); future.steps[0].operations[0].target_ids = ['recap']
  assert.equal(isBoardScriptV2(future), false)
  const invalidEdge = script(); invalidEdge.steps[1].operations[0].edges[0].to_id = 'intro'
  assert.equal(isBoardScriptV2(invalidEdge), false)
})

test('scene identity and dimensions remain stable while only confirmed prefixes reveal', () => {
  const value = script(), scene = layoutBoard(value)
  assert.deepEqual(layoutBoard(value), scene)
  assert.equal(visibleScene(scene, -1).objects.length, 0)
  for (let cursor = 0; cursor < value.steps.length; cursor += 1) {
    const visible = visibleScene(scene, cursor)
    assert.ok(visible.objects.every(object => object.stepIndex <= cursor))
    assert.equal(visible.regions.length, cursor + 1)
    assert.deepEqual(visible.objects.find(object => object.id === 'intro'), scene.objects.find(object => object.id === 'intro'))
  }
  assert.equal(new Set(scene.objects.map(object => object.id)).size, scene.objects.length)
})

test('narrow CJK cells count whole glyph slots, not fractional packed characters', () => {
  assert.equal(textLines('一二三四五六', 125, 19), 1)
  assert.equal(textLines('一二三四五六七八九十甲乙丙', 125, 19), 3)
  assert.equal(textLines('一二三四五六\n七八九十', 125, 19), 2)
})

test('step regions and table content reserve nonoverlapping readable geometry', () => {
  const value = script(), scene = layoutBoard(value)
  const regions = scene.regions.filter(region => region.step.page === 1 && region.step.column === 1)
  for (let i = 1; i < regions.length; i += 1) assert.ok(regions[i].y >= regions[i - 1].y + regions[i - 1].height)
  const table = value.steps[2].operations[0]
  assert.ok(operationHeight(table) > operationHeight({ ...table, rows: [] }))
  assert.ok(operationHeight({ ...table, content: '消息角色与返回关系' }) > operationHeight({ ...table, content: '' }))
  assert.ok(scene.objects.every(object => object.width > 0 && object.height > 0 && Number.isFinite(object.y)))
  assert.ok(scene.regions.find(region => region.step.page === 2)!.y > regions.at(-1)!.y)
})

test('native diagrams preserve directed identity in a compact reading path, including cycles', () => {
  const graph = script().steps[1].operations[0], nodes = diagramNodes(graph)
  assert.deepEqual(diagramNodes(graph), nodes)
  assert.deepEqual(nodes.map(node => node.id), ['n1', 'n2', 'n3'])
  assert.equal(nodes[0].y, nodes[1].y)
  assert.ok(nodes[0].x + nodes[0].width < nodes[1].x)
  assert.ok(nodes[1].y + nodes[1].height < nodes[2].y)
  const cyclic = { ...graph, edges: [...graph.edges, { from_id: 'n3', to_id: 'n1', label: '' }] }
  const loopNodes = diagramNodes(cyclic)
  assert.equal(loopNodes.length, 3)
  assert.equal(loopNodes[0].y, loopNodes[1].y)
  assert.ok(loopNodes[1].y < loopNodes[2].y)
})

test('one step owns one sheet regardless of model page labels; confirmed sheets remain cumulative', () => {
  const value = script()
  value.steps.forEach((step, index) => { step.page = index + 1; step.column = 1 })
  const scene = layoutBoard(value)
  assert.equal(scene.regions[0].page, 1)
  assert.equal(scene.regions[1].page, 2)
  assert.equal(scene.regions[0].x, scene.regions[1].x)
  assert.ok(scene.regions[1].y >= scene.regions[0].y + scene.regions[0].height)
  assert.ok(scene.regions[2].y >= Math.max(...scene.regions.slice(0, 2).map(region => region.y + region.height)))
  assert.deepEqual(visibleScene(scene, 1).regions, scene.regions.slice(0, 2))
})

test('all blocks of a dense step are grouped, bounded and ordered down each numbered column', () => {
  const operations = Array.from({ length: 6 }, (_, index) => operation(`block_${index}`, { content: '同一步的关键内容与示例，按编号阅读。'.repeat(3) }))
  const scene = layoutBoard({ steps: [step('dense', operations)] }), sheet = scene.regions[0]
  assert.equal(sheet.column, 2)
  assert.equal(scene.objects.length, operations.length)
  assert.deepEqual(scene.objects.map(object => object.operationIndex), [0, 1, 2, 3, 4, 5])
  for (let index = 0; index < scene.objects.length; index += 1) {
    const object = scene.objects[index]
    assert.ok(object.x >= sheet.x && object.y >= sheet.y)
    assert.ok(object.x + object.width <= sheet.x + sheet.width)
    assert.ok(object.y + object.height <= sheet.y + sheet.height)
    for (const other of scene.objects.slice(index + 1)) {
      assert.ok(object.x + object.width <= other.x || other.x + other.width <= object.x || object.y + object.height <= other.y || other.y + other.height <= object.y)
    }
    const previous = scene.objects[index - 1]
    if (previous) assert.ok(object.x > previous.x || object.x === previous.x && object.y > previous.y)
  }
  assert.ok(sheet.height < operations.reduce((height, operation) => height + operationHeight(operation) + 20, 0))
})

test('independent assistance accepts explicit new frames, never a fabricated classroom or old payload', () => {
  const frames = script().steps.map(({ title, narration, page, column, operations }) => ({ title, narration, page, column, operations }))
  assert.equal(isBoardFrames(frames), true)
  assert.equal(isBoardScriptV2({ title: '独立帧', steps: frames }), false)
  const legacy = structuredClone(frames)
  delete (legacy[0].operations[0] as unknown as Record<string, unknown>).object_id
  assert.equal(isBoardFrames(legacy), false)
  assert.equal(isBoardFrames([]), false)
})

test('diagram forward, horizontal and return edges use different attachment geometry', () => {
  const first = { x: 16, y: 20, width: 260, height: 76 }
  const second = { ...first, y: 200 }
  const forward = diagramEdgeGeometry(first, second)
  assert.match(forward.path, /^M146,96 C/)
  const back = diagramEdgeGeometry(second, first)
  assert.match(back.path, /^M276,238 C/)
  assert.ok(back.labelX > first.x + first.width)
  const across = diagramEdgeGeometry(first, { ...first, x: 320 })
  assert.match(across.path, /^M276,58 L320,58$/)
  assert.ok(across.labelY < first.y)
  assert.ok(diagramEdgeGeometry(second, first, 0, 580).labelX > 580)
})

test('highlight and circle reference existing geometry without inserting duplicate content', () => {
  const scene = layoutBoard(script())
  const graph = scene.objects.find(object => object.id === 'graph')!
  const highlight = scene.objects.find(object => object.id === 'mark-node')!
  assert.deepEqual(highlight.targets[0].rect, graph.nodes.find(node => node.id === 'n2'))
  assert.equal(highlight.stepIndex, 3)
  assert.equal(visibleScene(scene, 2).objects.some(object => object.id === highlight.id), false)
  assert.deepEqual(scene.objects.find(object => object.id === 'circle-intro')!.targets[0].rect, scene.objects.find(object => object.id === 'intro'))
})

test('focus resolves graph nodes in the viewed prefix but never future objects', () => {
  const scene = layoutBoard(script())
  const node = scene.objects.find(object => object.id === 'graph')!.nodes.find(node => node.id === 'n2')!
  assert.equal(sceneFocus(scene, 1, null, ['n2']), scene.regions[1])
  assert.deepEqual(sceneFocus(scene, 1, 'n2'), { x: node.x, y: node.y, width: node.width, height: node.height })
  assert.equal(sceneFocus(scene, -1, 'n2'), null)
  assert.equal(sceneFocus(scene, 0, 'recap'), scene.regions[0])
  assert.equal(confirmedCursor(100, 2), 2)
  assert.equal(confirmedCursor(-100, 2), -1)
})

test('camera fits both dimensions of the current step, not merely the first block or a width floor', () => {
  const rect = { x: 800, y: 9000, width: 1280, height: 900 }
  const camera = cameraForFocus(rect, { width: 1000, height: 600 })
  assert.ok(camera.zoom < .75)
  const tall = cameraForFocus({ ...rect, height: 12000 }, { width: 1000, height: 600 })
  assert.ok(tall.zoom < .05)
  assert.ok(tall.y + (rect.y + 12000) * tall.zoom <= 576.01)
  assert.ok(zoomCamera(tall, .8, { x: 500, y: 300 }).zoom <= tall.zoom)
  for (const viewport of [{ width: 1000, height: 600 }, { width: 680, height: 540 }, { width: 1280, height: 760 }]) {
    const fit = cameraForFocus(rect, viewport)
    assert.ok(fit.x + rect.x * fit.zoom >= 23.99)
    assert.ok(fit.y + rect.y * fit.zoom >= 23.99)
    assert.ok(fit.x + (rect.x + rect.width) * fit.zoom <= viewport.width - 23.99)
    assert.ok(fit.y + (rect.y + rect.height) * fit.zoom <= viewport.height - 23.99)
    assert.deepEqual(cameraForFocus(rect, viewport), fit)
  }
  const pointer = { x: 450, y: 300 }, changed = zoomCamera(camera, 1.15, pointer)
  assert.ok(Math.abs((pointer.x - camera.x) / camera.zoom - (pointer.x - changed.x) / changed.zoom) < .0001)
  assert.equal(zoomCamera(camera, 100, pointer).zoom, 2)
  assert.equal(zoomCamera(camera, .001, pointer).zoom, .05)
})

test('questions anchor the actual viewed object without moving teaching progress', () => {
  const value = script()
  assert.deepEqual(questionAnchor(value, 3, 1, 'n2'), { anchor_step_id: 'diagram', anchor_object_id: 'n2' })
  assert.deepEqual(questionAnchor(value, 3, 2, 'intro'), { anchor_step_id: 'opening', anchor_object_id: 'intro' })
  assert.equal(questionAnchor(value, 1, 3), null)
  assert.equal(questionAnchor(value, 3, 1, 'recap'), null)
  assert.equal(summaryIsShown(value, 3), false)
  assert.equal(summaryIsShown(value, 4), true)
  value.steps[4].stage = 'example'
  assert.equal(summaryIsShown(value, 4), false)
})
