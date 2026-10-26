import assert from 'node:assert/strict'
import test from 'node:test'
import { savedPreferences, savedStructureCounts, workbenchStatus, workbenchSteps } from '../src/lib/workbench-state.ts'
import type { Course, Run } from '../src/lib/types.ts'

test('preferences only reflect saved answers; custom single answer replaces an option and skip remains explicit', () => {
  const questions = [{ id: 'base', question: '基础？', type: 'single' as const, allow_custom: true, options: [{ id: 'a', label: '入门', description: '' }] },
    { id: 'focus', question: '侧重？', type: 'multi' as const, allow_custom: true, options: [{ id: 'b', label: '理论', description: '' }] }]
  const run = { questions, answers: [{ question_id: 'base', option_ids: ['a'], custom_text: '  有Python基础  ' },
    { question_id: 'focus', option_ids: ['b'], custom_text: '推导' }], skipped: false }
  assert.deepEqual(savedPreferences(run), [{ question: '基础？', values: ['有Python基础'] }, { question: '侧重？', values: ['理论', '推导'] }])
  assert.deepEqual(savedPreferences({ ...run, skipped: true }), [])
  assert.deepEqual(savedPreferences({ ...run, answers: [] }), [])
})

test('saved counts are actual structure and never planned scale', () => {
  assert.deepEqual(savedStructureCounts(null), { units: 0, lectures: 0, sessions: 0 })
  const course = { units: [{ generation_status: 'ready', estimated_sessions: 20, lectures: [{ sessions: [{}, {}] }] },
    { generation_status: 'pending', estimated_sessions: 10, lectures: [] }] } as Course
  assert.deepEqual(savedStructureCounts(course), { units: 1, lectures: 1, sessions: 2 })
})

test('waiting, cancellation and revision do not masquerade as completed phases', () => {
  const run = { status: 'awaiting_blueprint', stage: 'blueprint' } as Run
  assert.deepEqual(workbenchSteps(run).map(step => step.state), ['done', 'done', 'waiting', 'pending'])
  assert.deepEqual(workbenchSteps({ ...run, status: 'generating' }).map(step => step.state), ['done', 'done', 'active', 'pending'])
  assert.deepEqual(workbenchSteps({ ...run, status: 'cancelled' }).map(step => step.state), ['done', 'done', 'stopped', 'pending'])
  assert.deepEqual(workbenchSteps({ ...run, stage: 'units', status: 'ready' }).map(step => step.state), ['done', 'done', 'done', 'done'])
})

test('current unit caption uses a real run identity and does not guess from saved counts', () => {
  const run = { status: 'generating', stage: 'units', current_unit_id: 'second' } as Run
  const course = { units: [{ unit_id: 'first', title: '第一单元' }, { unit_id: 'second', title: '第二单元' }] } as Course
  assert.deepEqual(workbenchStatus(run, course), { title: '正在完善第 2 / 2 单元', description: '第二单元' })
  assert.equal(workbenchStatus(run, null).title, '正在完善课程内容')
  assert.equal(workbenchStatus({ ...run, status: 'ready' }, course).title, '课程准备好了')
})

test('a course with no clarification questions displays its saved research stage', () => {
  const run = { status: 'generating', stage: 'research', questions: [], answers: [] } as unknown as Run
  assert.deepEqual(workbenchSteps(run).map(step => step.state), ['done', 'active', 'pending', 'pending'])
  assert.equal(workbenchStatus(run, null).title, '正在查阅参考资料')
  assert.deepEqual(savedPreferences(run), [])
})
