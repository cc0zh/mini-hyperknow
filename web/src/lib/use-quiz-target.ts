import { useCallback } from 'react'
import { matchesQuizScope, mergeQuizTarget, quizTargetPath } from './quiz-state'
import type { QuizScope } from './quiz-state'
import type { QuizSnapshot } from './types'
import { useQuizSync } from './use-quiz-sync'

export function useQuizTarget({ courseId, targetType, targetId }: QuizScope) {
  const validate = useCallback((value: QuizSnapshot) => matchesQuizScope(value, { courseId, targetType, targetId }) &&
    (!value.quiz || matchesQuizScope(value.quiz, { courseId, targetType, targetId })), [courseId, targetType, targetId])
  return useQuizSync(quizTargetPath(targetType, targetId), `quiz_target:${targetType}:${targetId}|course:${courseId}`, validate, mergeQuizTarget)
}
