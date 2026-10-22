import assert from 'node:assert/strict'
import test from 'node:test'
import { answerCommand, attemptTransition, commandAttemptId, followLatestAttempt, matchesQuizScope, mergeAttempt, mergeQuizTarget, nextLearningPath, ownsQuizCommand, preserveQuizCommand, questionElapsed, quizFailure, quizTargetPath, readQuizCommand, selectedQuizOptions } from '../src/lib/quiz-state.ts'
import type { AttemptSnapshot, Course, QuizAttempt, QuizQuestion, QuizSnapshot } from '../src/lib/types.ts'

// Concrete inputs to actual deterministic helpers, not API/model substitutes.
const scope = { courseId: 'course-a', targetType: 'practice' as const, targetId: 'session-a' }
const question: QuizQuestion = { question_id: 'q-a', kind: 'multiple', prompt: 'Pick both', options: [{ id: 'a', text: 'A' }, { id: 'b', text: 'B' }], correct_option_ids: ['a', 'b'], explanation: 'Both apply', source_refs: ['step:a'] }
const initial: QuizAttempt = { attempt_id: 'attempt-a', quiz_id: 'quiz-a', course_id: 'course-a', target_type: 'practice', target_id: 'session-a', status: 'in_progress', version: 1, cursor: 0, question_started_at: '2026-10-22T00:00:00+00:00', answers: [], result: null, created_at: '2026-10-22T00:00:00+00:00', updated_at: '2026-10-22T00:00:00+00:00', submitted_at: null }
const savedAnswer = { question_id: 'q-a', option_ids: ['a', 'b'], skipped: false, elapsed_ms: 12000, correct: true, fast: false, points: 600, answered_at: initial.created_at }

test('target paths and scope keep practice and exam in their actual course', () => {
  assert.equal(quizTargetPath('practice', 'a/b'), '/sessions/a%2Fb/practice')
  assert.equal(quizTargetPath('exam', 'a/b'), '/exams/a%2Fb')
  assert.equal(matchesQuizScope(initial, scope), true)
  assert.equal(matchesQuizScope({ ...initial, course_id: 'other' }, scope), false)
  assert.equal(matchesQuizScope({ ...initial, target_type: 'exam' }, scope), false)
})

test('target snapshots reject equal and older versions', () => {
  const current = { version: 4, course_id: 'course-a', target_type: 'practice', target_id: 'session-a' } as QuizSnapshot
  assert.equal(mergeQuizTarget(current, { ...current, version: 3 }), current)
  assert.equal(mergeQuizTarget(current, { ...current }), current)
  assert.equal(mergeQuizTarget(current, { ...current, version: 5 }).version, 5)
})

test('attempt facts and parent course independently retain newer versions', () => {
  const current = { attempt: { ...initial, version: 5, answers: [savedAnswer] }, quiz: { quiz_id: 'quiz-a' }, course: { course_id: 'course-a', version: 2 } } as AttemptSnapshot
  const newerCourse = { ...current, attempt: { ...initial, version: 3 }, course: { ...current.course, version: 4 } }
  const merged = mergeAttempt(current, newerCourse)
  assert.equal(merged.attempt, current.attempt)
  assert.equal(merged.course, newerCourse.course)
  const again = mergeAttempt(merged, { ...current, attempt: { ...current.attempt, version: 6 } })
  assert.equal(again.attempt.version, 6)
  assert.equal(again.course.version, 4)
})

test('elapsed uses the saved question start and an unknown retry preserves its exact time', () => {
  const now = Date.parse('2026-10-22T00:00:12Z')
  assert.equal(questionElapsed(initial.question_started_at, now), 12000)
  assert.equal(questionElapsed('2026-10-22T00:00:00', now), 12000)
  assert.equal(questionElapsed('invalid', now), null)
  assert.equal(questionElapsed(initial.question_started_at, Date.parse('2026-10-21T23:59:59Z')), 0)
  const first = answerCommand(initial, question, ['b', 'a'], false, 'command-a', now)!
  assert.deepEqual(first.body.option_ids, ['a', 'b'])
  assert.equal(first.body.elapsed_ms, 12000)
  const retry = preserveQuizCommand(first, answerCommand(initial, question, ['a'], false, 'command-b', now + 30000)!)
  assert.equal(retry, first)
  assert.equal(retry.body.elapsed_ms, 12000)
  assert.deepEqual(readQuizCommand(JSON.stringify(retry)), first)
})

test('a question resumed after a day can be answered with an explicitly bounded duration', () => {
  const command = answerCommand(initial, question, ['a', 'b'], false, 'command-a', Date.parse(initial.question_started_at) + 2 * 86_400_000)!
  assert.equal(command.body.elapsed_ms, 86_400_000)
})

test('single and boolean reject empty/multiple selections and skip stores no options', () => {
  for (const kind of ['single', 'boolean'] as const) {
    assert.equal(answerCommand(initial, { ...question, kind }, [], false, 'command-a'), null)
    assert.equal(answerCommand(initial, { ...question, kind }, ['a', 'b'], false, 'command-a'), null)
    assert.deepEqual(answerCommand(initial, { ...question, kind }, ['a'], true, 'command-a')!.body.option_ids, [])
  }
  assert.equal(answerCommand({ ...initial, answers: [savedAnswer] }, question, ['a'], false, 'command-a'), null)
  assert.equal(answerCommand({ ...initial, status: 'submitted' }, question, ['a'], false, 'command-a'), null)
})

test('feedback stays on its answered question and the last answer is not submission', () => {
  assert.equal(attemptTransition(initial, 3), 'answer')
  const answered = { ...initial, answers: [savedAnswer] }
  assert.equal(attemptTransition(answered, 3), 'next')
  assert.equal(attemptTransition(answered, 1), 'submit')
  assert.equal(attemptTransition({ ...answered, status: 'submitted' }, 1), 'result')
  assert.deepEqual(selectedQuizOptions('q-a', ['b'], answered), ['a', 'b'])
  assert.deepEqual(selectedQuizOptions('q-b', ['b'], answered), ['b'])
})

test('unknown commands restore their exact attempt and malformed storage is ignored', () => {
  const command = answerCommand(initial, question, ['a'], false, 'command-a')!
  assert.equal(commandAttemptId(command), 'attempt-a')
  assert.equal(commandAttemptId({ ...command, path: '/attempts/a%2Fb/next' }), 'a/b')
  assert.equal(commandAttemptId({ ...command, path: '/quizzes/quiz-a/attempts' }), null)
  assert.equal(commandAttemptId({ ...command, path: '/attempts/%ZZ/submit' }), null)
  assert.equal(readQuizCommand('{broken'), null)
  assert.equal(readQuizCommand('{"method":"GET","path":"/attempts/a","body":{}}'), null)
})

test('definite rejection is distinct from an unknown server/network result', () => {
  assert.equal(quizFailure(409, 'version_conflict'), 'conflict')
  assert.equal(quizFailure(409, 'lesson_required'), 'rejected')
  assert.equal(quizFailure(503, 'model_not_configured'), 'rejected')
  assert.equal(quizFailure(422, 'invalid_request'), 'rejected')
  assert.equal(quizFailure(502, 'model_request_failed'), 'unknown')
  assert.equal(quizFailure(503, 'storage_unavailable'), 'unknown')
})

test('a late command A cannot clear a newer stored command B after navigation', () => {
  const a = answerCommand(initial, question, ['a'], false, 'command-a')!
  const b = { ...a, body: { ...a.body, client_command_id: 'command-b' } }
  assert.equal(ownsQuizCommand(readQuizCommand(JSON.stringify(a)), a), true)
  assert.equal(ownsQuizCommand(readQuizCommand(JSON.stringify(b)), a), false)
  assert.equal(ownsQuizCommand(null, a), false)
  assert.equal(ownsQuizCommand({ ...a, path: '/attempts/other/next' }, a), false)
})

test('a historical result remains pinned when a newer attempt exists', () => {
  assert.equal(followLatestAttempt('old-result', initial), 'old-result')
  assert.equal(followLatestAttempt(null, initial), 'attempt-a')
  assert.equal(followLatestAttempt(null, null), null)
})

test('continue supports a real exam without inventing a project submit route', () => {
  const course = { course_id: 'course-a', next_item: { type: 'exam', exam_id: 'exam-a', unit_id: 'unit-a', title: 'Exam' } } as Course
  assert.equal(nextLearningPath(course), '/courses/course-a/exams/exam-a')
  assert.equal(nextLearningPath({ ...course, next_item: { type: 'session', session_id: 's-a', unit_id: 'unit-a', title: 'Lesson' } }), '/courses/course-a/sessions/s-a')
  assert.equal(nextLearningPath({ ...course, next_item: { type: 'project', stage_id: 'stage-a', unit_id: 'unit-a', title: 'Project' } }), null)
  assert.equal(nextLearningPath({ ...course, next_item: null }), null)
})
