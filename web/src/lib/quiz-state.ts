import type { AttemptSnapshot, Course, QuizAttempt, QuizQuestion, QuizSnapshot, QuizTargetType } from './types.ts'

export interface QuizScope { courseId: string; targetType: QuizTargetType; targetId: string }
export interface QuizCommand {
  method: 'POST'
  path: string
  body: Record<string, unknown> & { client_command_id: string }
}
export const QUIZ_MAX_ELAPSED_MS = 86_400_000

export const quizStorageKey = (scope: QuizScope) => `hyperknow.quiz.${scope.courseId}.${scope.targetType}.${scope.targetId}`
export const quizTargetPath = (type: QuizTargetType, id: string) => type === 'practice'
  ? `/sessions/${encodeURIComponent(id)}/practice` : `/exams/${encodeURIComponent(id)}`
export const matchesQuizScope = (value: { course_id: string; target_type: QuizTargetType; target_id: string }, scope: QuizScope) =>
  value.course_id === scope.courseId && value.target_type === scope.targetType && value.target_id === scope.targetId

export function mergeQuizTarget(current: QuizSnapshot | null, incoming: QuizSnapshot): QuizSnapshot {
  if (!current || current.course_id !== incoming.course_id || current.target_type !== incoming.target_type || current.target_id !== incoming.target_id) return incoming
  return incoming.version > current.version ? incoming : current
}
export function mergeAttempt(current: AttemptSnapshot | null, incoming: AttemptSnapshot): AttemptSnapshot {
  if (!current || current.attempt.attempt_id !== incoming.attempt.attempt_id) return incoming
  const facts = incoming.attempt.version > current.attempt.version ? incoming : current
  const course = incoming.course.version > current.course.version ? incoming.course : current.course
  return facts.course === course ? facts : { ...facts, course }
}

export const preserveQuizCommand = (pending: QuizCommand | null, proposed: QuizCommand) => pending ?? proposed
export const ownsQuizCommand = (stored: QuizCommand | null, completed: QuizCommand) =>
  stored?.body.client_command_id === completed.body.client_command_id && stored.path === completed.path && stored.method === completed.method
export function quizFailure(status: number, code: string): 'conflict' | 'rejected' | 'unknown' {
  if (status === 409 && ['version_conflict', 'state_conflict', 'command_conflict'].includes(code)) return 'conflict'
  if ([400, 404, 405, 409, 422].includes(status) || code === 'model_not_configured') return 'rejected'
  return 'unknown'
}
export const followLatestAttempt = (selectedId: string | null, latest: QuizAttempt | null) => selectedId ?? latest?.attempt_id ?? null
export function readQuizCommand(raw: string | null): QuizCommand | null {
  try {
    const value = JSON.parse(raw || 'null') as QuizCommand | null
    return value?.method === 'POST' && typeof value.path === 'string' && typeof value.body?.client_command_id === 'string' ? value : null
  } catch { return null }
}
export function commandAttemptId(command: QuizCommand | null): string | null {
  const id = command?.path.match(/^\/attempts\/([^/]+)\/(?:answers|next|submit)$/)?.[1]
  try { return id ? decodeURIComponent(id) : null } catch { return null }
}

// Backend timestamps without an explicit offset represent UTC, not local time.
export function questionElapsed(startedAt: string, now = Date.now()): number | null {
  const start = Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(startedAt) ? startedAt : `${startedAt}Z`)
  return Number.isFinite(start) && Number.isFinite(now) ? Math.max(0, Math.floor(now - start)) : null
}
export function answerCommand(attempt: QuizAttempt, question: QuizQuestion, optionIds: string[], skipped: boolean, commandId: string, now = Date.now()): QuizCommand | null {
  if (attempt.status !== 'in_progress' || attempt.answers.some(answer => answer.question_id === question.question_id)) return null
  const elapsed = questionElapsed(attempt.question_started_at, now)
  if (elapsed === null) return null
  const options = skipped ? [] : question.options.filter(option => optionIds.includes(option.id)).map(option => option.id)
  if (!skipped && (!options.length || (question.kind !== 'multiple' && options.length !== 1))) return null
  return { method: 'POST', path: `/attempts/${encodeURIComponent(attempt.attempt_id)}/answers`, body: {
    client_command_id: commandId, expected_version: attempt.version, question_id: question.question_id,
    option_ids: options, skipped, elapsed_ms: Math.min(QUIZ_MAX_ELAPSED_MS, elapsed),
  } }
}
export function selectedQuizOptions(questionId: string, draft: string[], attempt: QuizAttempt): string[] {
  return attempt.answers.find(answer => answer.question_id === questionId)?.option_ids ?? draft
}
export function attemptTransition(attempt: QuizAttempt, questionCount: number): 'answer' | 'next' | 'submit' | 'result' {
  if (attempt.status === 'submitted') return 'result'
  if (attempt.answers.length <= attempt.cursor) return 'answer'
  return attempt.cursor + 1 < questionCount ? 'next' : 'submit'
}
export function nextLearningPath(course: Pick<Course, 'course_id' | 'next_item'>): string | null {
  const base = `/courses/${encodeURIComponent(course.course_id)}`
  const item = course.next_item
  if (item?.session_id && ['lecture', 'session'].includes(item.type)) return `${base}/sessions/${encodeURIComponent(item.session_id)}`
  if (item?.type === 'exam' && item.exam_id) return `${base}/exams/${encodeURIComponent(item.exam_id)}`
  return null
}
