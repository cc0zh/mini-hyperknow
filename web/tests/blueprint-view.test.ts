import assert from 'node:assert/strict'
import test from 'node:test'
import { blueprintKey, blueprintNodes, blueprintStats, resolveBlueprintSelection } from '../src/lib/blueprint-view.ts'
import type { Course, Unit } from '../src/lib/types.ts'

// Direct domain inputs verify presentation rules, not model output or API behavior.
function unit(id: string): Unit {
  return { unit_id: id, title: `单元 ${id}`, description: '完整范围', learning_objectives: ['完整目标'], estimated_sessions: 8, generation_status: 'pending', lectures: [], exams: [], project_stages: [] }
}

function course(units: Unit[]): Course {
  return { course_id: 'course-view', title: '课程', description: '简介', target_learner: '学习者', difficulty: 'beginner', tags: [], language: 'zh', projects: [], units, goal: '目标', created_at: '', version: 1, session_count: 99, unit_count: 99, exam_count: 99, progress: null, next_item: null, structure_status: 'blueprint' }
}

test('all 2–8 planned units exist, but estimates and counters never manufacture descendants', () => {
  for (let count = 2; count <= 8; count++) {
    const input = course(Array.from({ length: count }, (_, i) => unit(String(i))))
    const nodes = blueprintNodes(input)
    assert.equal(nodes.length, count + 1)
    assert.deepEqual(blueprintStats(nodes), { units: count, readyUnits: 0, sessions: 0, exams: 0, stages: 0 })
    assert.equal(resolveBlueprintSelection(nodes, null).data, input.units[0])
  }
})

test('saved lecture, session, project stage and exam retain exact content and parent relationships', () => {
  const expanded = unit('unit-1')
  expanded.generation_status = 'ready'
  expanded.lectures = [{ lecture_id: 'lecture-1', title: '讲次完整标题', description: '讲次范围', sessions: [{ session_id: 'session-1', title: '小节完整标题', description: '小节目标', outline: ['完整提纲一', '完整提纲二'], key_points: ['要点'], depths: ['derivation', 'practice'], estimated_minutes: 30 }] }]
  expanded.project_stages = [{ stage_id: 'stage-1', project_id: 'project-1', title: '阶段', description: '要求', deliverable: '阶段交付' }]
  expanded.exams = [{ exam_id: 'exam-1', title: '考核', goal: '完整考核目标' }]
  const input = course([expanded, unit('unit-2')])
  input.projects = [{ project_id: 'project-1', name: '全局项目', description: '完整要求', final_deliverable: '完整交付' }]
  const nodes = blueprintNodes(input)
  const find = (kind: string) => nodes.find(node => node.kind === kind)!
  assert.equal(find('unit').parentKey, find('course').key)
  assert.equal(find('lecture').parentKey, find('unit').key)
  assert.equal(find('session').parentKey, find('lecture').key)
  assert.equal(find('session').data, expanded.lectures[0].sessions[0])
  assert.equal(find('stage').data, expanded.project_stages[0])
  assert.equal(find('stage').parentKey, find('unit').key)
  assert.equal(find('exam').parentKey, find('unit').key)
  assert.equal(find('project').parentKey, find('course').key)
  assert.equal(find('project').unitId, null)
  assert.deepEqual(blueprintStats(nodes), { units: 2, readyUnits: 1, sessions: 1, exams: 1, stages: 1 })
})

test('stable IDs preserve explicit selection across versions, reordered units and generation changes', () => {
  const input = course([unit('a'), unit('b')])
  const selectedKey = blueprintKey(input.course_id, 'unit', 'b')
  const updated = { ...input, version: 8, blueprint_version: 3, units: [{ ...input.units[1], title: '更新后的完整标题', generation_status: 'generating' as const }, input.units[0]] }
  assert.equal(resolveBlueprintSelection(blueprintNodes(updated), selectedKey).key, selectedKey)
  assert.equal(resolveBlueprintSelection(blueprintNodes(updated), selectedKey).title, '更新后的完整标题')
  const root = blueprintNodes(updated)[0]
  assert.equal(resolveBlueprintSelection(blueprintNodes(updated), root.key).kind, 'course')
  const removed = blueprintNodes({ ...updated, units: [input.units[0]] })
  assert.equal(resolveBlueprintSelection(removed, selectedKey).unitId, 'a')
})

test('a removed descendant falls back to first unit, not a newly generating unit or course root', () => {
  const input = course([unit('first'), unit('second')])
  const oldSessionKey = blueprintKey(input.course_id, 'session', 'removed')
  input.units[1].generation_status = 'generating'
  assert.equal(resolveBlueprintSelection(blueprintNodes(input), oldSessionKey).unitId, 'first')
  assert.equal(resolveBlueprintSelection(blueprintNodes(course([])), oldSessionKey).kind, 'course')
})

test('keys distinguish kind, course and separator-bearing IDs', () => {
  assert.notEqual(blueprintKey('a', 'unit', 'same'), blueprintKey('a', 'session', 'same'))
  assert.notEqual(blueprintKey('a', 'unit', 'b:unit:c'), blueprintKey('a:unit:b', 'unit', 'c'))
  assert.notEqual(blueprintKey('a', 'unit', 'same'), blueprintKey('b', 'unit', 'same'))
})
