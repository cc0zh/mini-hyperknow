import type { Answer, Question, Run, RunStatus } from './types'

export const runLabels: Record<RunStatus, string> = {
  queued: '等待执行', clarifying: '正在理解目标', awaiting_answers: '等待你的补充',
  generating: '正在生成课程', ready: '课程已就绪', failed: '生成失败',
  cancelled: '已取消', interrupted: '运行已中断',
}

export const isTerminal = (status: RunStatus) => ['ready', 'failed', 'cancelled', 'interrupted'].includes(status)

// Notifications only invalidate a snapshot; their partial state never becomes a Run.
export function newerRun(current: Run | null, incoming: Run): Run {
  return !current || current.run_id !== incoming.run_id || incoming.version > current.version ? incoming : current
}

export function toggleOption(question: Question, answer: Answer, optionId: string): Answer {
  const selected = answer.option_ids.includes(optionId)
  return {
    ...answer,
    option_ids: question.type === 'single' ? (selected ? [] : [optionId]) :
      selected ? answer.option_ids.filter(id => id !== optionId) : [...answer.option_ids, optionId],
    custom_text: question.type === 'single' ? '' : answer.custom_text,
  }
}

export function hasAnswers(questions: Question[], answers: Answer[]): boolean {
  return questions.every(question => answers.some(answer => answer.question_id === question.id &&
    (answer.option_ids.length > 0 || (question.allow_custom && answer.custom_text.trim().length > 0))))
}
