import test from 'node:test'
import assert from 'node:assert/strict'
import { blueprintDecision, hasAnswers, isTerminal, isWorking, newerRun, recoverableCourseRuns, runHeading, runLabels, supersedingCourseRunId, toggleOption } from '../src/lib/run-state.ts'
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
  const statuses: RunStatus[] = ['queued', 'clarifying', 'awaiting_answers', 'awaiting_blueprint', 'generating', 'ready', 'failed', 'cancelled', 'interrupted']
  assert.equal(statuses.every(status => !!runLabels[status]), true)
  assert.deepEqual(statuses.filter(isTerminal), ['ready', 'failed', 'cancelled', 'interrupted'])
})

test('blueprint review is a nonterminal wait, not a working spinner', () => {
  assert.equal(isTerminal('awaiting_blueprint'), false)
  assert.equal(isWorking('awaiting_blueprint'), false)
  assert.equal(isWorking('awaiting_answers'), false)
  assert.equal(isWorking('generating'), true)
  assert.equal(runHeading({ status: 'awaiting_blueprint', stage: 'blueprint' }), '等待确认课程蓝图')
  assert.equal(runHeading({ status: 'failed', stage: 'units' }), '生成失败')
})

test('generation headings follow saved stages rather than pretend progress', () => {
  assert.equal(runHeading({ status: 'generating', stage: 'clarifying' }), '需求澄清')
  assert.equal(runHeading({ status: 'generating', stage: 'research' }), '网页调研')
  assert.equal(runHeading({ status: 'generating', stage: 'blueprint' }), '全局蓝图')
  assert.equal(runHeading({ status: 'generating', stage: 'units' }), '逐单元展开')
})

test('blueprint decisions use the current server version and require nonblank adjustment feedback', () => {
  const run = { status: 'awaiting_blueprint' as const, version: 12 }
  assert.deepEqual(blueprintDecision(run, true), { expected_version: 12, approve: true, feedback: '' })
  assert.equal(blueprintDecision(run, false, ' \n '), null)
  assert.deepEqual(blueprintDecision(run, false, '  增加应用实操  '), { expected_version: 12, approve: false, feedback: '增加应用实操' })
  assert.equal(blueprintDecision(run, true, '', true), null)
  assert.equal(blueprintDecision({ ...run, status: 'generating' }, true), null)
  assert.equal(blueprintDecision({ ...run, status: 'ready' }, false, '调整'), null)
})

test('a pending blueprint adjustment keeps its exact approval flag, feedback, version and command ID', () => {
  const body = blueprintDecision({ status: 'awaiting_blueprint', version: 7 }, false, '增加应用实操')!
  const command = prepareCommand(null, '/runs/r-1/blueprint', body, 'blueprint-command')!
  assert.equal(prepareCommand(command, '/runs/r-1/blueprint', { expected_version: 9, approve: true, feedback: '' }, 'another-id'), command)
  assert.deepEqual(command.body, { ...body, client_command_id: 'blueprint-command' })
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

test('a completed retry replaces the failed attempt in the course library without changing history', () => {
  const failed: Run = { ...state(45), run_id: 'original', status: 'failed', course_id: 'course-a' }
  const ready: Run = { ...failed, run_id: 'retry', parent_run_id: failed.run_id, status: 'ready' }
  const courses = [{ course_id: 'course-a', creation_run_id: ready.run_id }]
  assert.deepEqual(recoverableCourseRuns([ready, failed], courses), [])
  assert.equal(failed.status, 'failed')
  assert.equal(supersedingCourseRunId(failed, courses[0]), ready.run_id)
})

test('only the latest unfinished retry remains recoverable across multiple attempts', () => {
  const first: Run = { ...state(1), run_id: 'first', status: 'failed', course_id: 'course-a' }
  const second: Run = { ...first, run_id: 'second', parent_run_id: first.run_id, status: 'cancelled' }
  const third: Run = { ...first, run_id: 'third', parent_run_id: second.run_id, status: 'generating' }
  assert.deepEqual(recoverableCourseRuns([first, third, second], [{ course_id: 'course-a', creation_run_id: third.run_id }]), [third])
  // A course read that preceded the retry must not hide the newer descendant.
  assert.deepEqual(recoverableCourseRuns([first, third, second], [{ course_id: 'course-a', creation_run_id: first.run_id }]), [third])
})

test('the course owner excludes obsolete failures even when the current run falls outside the recent list', () => {
  const old: Run = { ...state(1), status: 'failed', course_id: 'course-a' }
  assert.deepEqual(recoverableCourseRuns([old], [{ course_id: 'course-a', creation_run_id: 'not-in-recent-list' }]), [])
})

test('retry ancestry supersedes attempts that failed before a course was saved', () => {
  const first: Run = { ...state(1), run_id: 'first', status: 'failed' }
  const next: Run = { ...first, run_id: 'next', parent_run_id: first.run_id, course_id: 'course-a' }
  assert.deepEqual(recoverableCourseRuns([next, first], []), [next])
})

test('unrelated courses with identical goals and non-superseded cancellations remain visible', () => {
  const first: Run = { ...state(1), run_id: 'first', status: 'failed', course_id: 'course-a', goal: '相同目标' }
  const other: Run = { ...first, run_id: 'other', course_id: 'course-b', status: 'cancelled' }
  const lesson: Run = { ...first, run_id: 'lesson', kind: 'lesson', parent_run_id: first.run_id }
  assert.deepEqual(recoverableCourseRuns([first, other, lesson], []), [first, other])
})

test('a redirect requires a different owner of the same course, not just any saved course', () => {
  const run: Run = { ...state(1), course_id: 'course-a' }
  assert.equal(supersedingCourseRunId(run, { course_id: 'course-a', creation_run_id: run.run_id }), null)
  assert.equal(supersedingCourseRunId(run, { course_id: 'course-b', creation_run_id: 'other' }), null)
  assert.equal(supersedingCourseRunId(run, { course_id: 'course-a' }), null)
  assert.equal(supersedingCourseRunId({ ...run, kind: 'lesson' }, { course_id: 'course-a', creation_run_id: 'other' }), null)
  assert.equal(supersedingCourseRunId(run, null), null)
})
