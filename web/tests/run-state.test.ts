import test from 'node:test'
import assert from 'node:assert/strict'
import { hasAnswers, isTerminal, newerRun, runLabels, toggleOption } from '../src/lib/run-state.ts'
import { prepareCommand } from '../src/lib/commands.ts'
import type { Answer, Question, Run, RunStatus } from '../src/lib/types.ts'

// Pure domain/UI state checks only: no API substitutes or generated sample courses.
const single: Question = { id: 'q1', question: '你的基础？', type: 'single', allow_custom: true, options: [{ id: 'a', label: '初学', description: '' }, { id: 'b', label: '有基础', description: '' }] }
const multi: Question = { ...single, id: 'q2', type: 'multi' }
const empty = (id: string): Answer => ({ question_id: id, option_ids: [], custom_text: '' })
const state = (version: number): Run => ({ run_id: 'version-test', goal: '', status: 'clarifying', version, questions: [], answers: [], course_id: null, error: null, model: '', created_at: '', updated_at: '', parent_run_id: null, usage: null })

test('single selection replaces previous choice and custom answer', () => {
  assert.deepEqual(toggleOption(single, { ...empty('q1'), option_ids: ['a'], custom_text: '其他' }, 'b'), { question_id: 'q1', option_ids: ['b'], custom_text: '' })
})

test('multi selection accumulates choices while preserving custom text', () => {
  const answer = { ...empty('q2'), option_ids: ['a'], custom_text: '补充目标' }
  assert.deepEqual(toggleOption(multi, answer, 'b').option_ids, ['a', 'b'])
  assert.equal(toggleOption(multi, answer, 'b').custom_text, '补充目标')
  assert.deepEqual(toggleOption(multi, answer, 'a').option_ids, [])
})

test('unanswered required questions block ordinary submission', () => {
  assert.equal(hasAnswers([single, multi], [empty('q1'), empty('q2')]), false)
  assert.equal(hasAnswers([single, multi], [{ ...empty('q1'), option_ids: ['a'] }]), false)
})

test('custom answers count only when explicitly allowed and nonblank', () => {
  assert.equal(hasAnswers([single], [{ ...empty('q1'), custom_text: '  ' }]), false)
  assert.equal(hasAnswers([single], [{ ...empty('q1'), custom_text: '希望打好基础' }]), true)
  assert.equal(hasAnswers([{ ...single, allow_custom: false }], [{ ...empty('q1'), custom_text: '其他' }]), false)
})

test('questions are matched by stable identity rather than array position', () => {
  assert.equal(hasAnswers([single, multi], [{ ...empty('q2'), option_ids: ['b'] }, { ...empty('q1'), option_ids: ['a'] }]), true)
  assert.equal(hasAnswers([], []), true)
})

test('a stale snapshot cannot overwrite a newer run', () => {
  const current = state(8)
  assert.equal(newerRun(current, state(7)), current)
  assert.equal(newerRun(current, state(8)), current)
  assert.equal(newerRun(current, state(9)).version, 9)
})

test('the first recovery snapshot is accepted', () => {
  const incoming = state(3)
  assert.equal(newerRun(null, incoming), incoming)
})

test('all API statuses have a label and only terminal states stop polling', () => {
  const statuses: RunStatus[] = ['queued', 'clarifying', 'awaiting_answers', 'generating', 'ready', 'failed', 'cancelled', 'interrupted']
  assert.equal(statuses.every(status => !!runLabels[status]), true)
  assert.deepEqual(statuses.filter(isTerminal), ['ready', 'failed', 'cancelled', 'interrupted'])
})

test('new commands capture a caller-provided stable ID', () => {
  assert.deepEqual(prepareCommand(null, '/course-runs', { goal: '代数' }, 'command-1'), { path: '/course-runs', body: { goal: '代数', client_command_id: 'command-1' } })
})

test('a retry reuses its original path, version, ID and answers verbatim', () => {
  const command = prepareCommand(null, '/runs/run-1/answers', { expected_version: 4, skip: false, answers: [{ ...empty('q1'), option_ids: ['b'] }] }, 'original-id')!
  assert.equal(prepareCommand(command, '/runs/run-1/cancel', { expected_version: 20 }, 'new-id'), command)
  assert.equal(prepareCommand(command, undefined, undefined, 'another-id'), command)
  assert.equal(command.body.client_command_id, 'original-id')
  assert.equal(command.body.expected_version, 4)
})

test('an empty retry does not manufacture a request', () => {
  assert.equal(prepareCommand(null, undefined, undefined, 'unused'), null)
})
