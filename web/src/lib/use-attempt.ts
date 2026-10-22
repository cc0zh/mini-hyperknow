import { useCallback } from 'react'
import { matchesQuizScope, mergeAttempt } from './quiz-state'
import type { QuizScope } from './quiz-state'
import type { AttemptSnapshot } from './types'
import { useQuizSync } from './use-quiz-sync'

export function useAttempt(attemptId: string | null, { courseId, targetType, targetId }: QuizScope) {
  const validate = useCallback((value: AttemptSnapshot) => value.course.course_id === courseId &&
    value.attempt.attempt_id === attemptId && value.attempt.quiz_id === value.quiz.quiz_id &&
    matchesQuizScope(value.attempt, { courseId, targetType, targetId }) &&
    matchesQuizScope(value.quiz, { courseId, targetType, targetId }), [attemptId, courseId, targetType, targetId])
  return useQuizSync(attemptId ? `/attempts/${encodeURIComponent(attemptId)}` : null,
    attemptId ? `attempt:${attemptId}|course:${courseId}` : '', validate, mergeAttempt)
}
