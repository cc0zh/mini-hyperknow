import type { Answer, Course, Question, Run, RunStatus } from './types'

export const runLabels: Record<RunStatus, string> = {
  queued: '等待执行', clarifying: '正在理解目标', awaiting_answers: '等待你的补充', awaiting_blueprint: '等待确认课程蓝图',
  generating: '正在生成课程', ready: '课程已就绪', failed: '生成失败',
  cancelled: '已取消', interrupted: '运行已中断',
}

export const isTerminal = (status: RunStatus) => ['ready', 'failed', 'cancelled', 'interrupted'].includes(status)
export const isWorking = (status: RunStatus) => ['queued', 'clarifying', 'generating'].includes(status)
export const needsClarificationAnswers = (run: Pick<Run, 'status' | 'questions'>) => run.status === 'awaiting_answers' && run.questions.length > 0

export const stageLabels = { clarifying: '需求澄清', research: '网页调研', blueprint: '全局蓝图', units: '逐单元展开' }
export function runHeading(run: Pick<Run, 'status' | 'stage'>): string {
  return run.status === 'generating' && run.stage ? stageLabels[run.stage] : runLabels[run.status]
}

export function blueprintDecision(run: Pick<Run, 'status' | 'version'>, approve: boolean, feedback = '', locked = false) {
  if (locked || run.status !== 'awaiting_blueprint' || (!approve && !feedback.trim())) return null
  return { expected_version: run.version, approve, feedback: feedback.trim() }
}

// Notifications only invalidate a snapshot; their partial state never becomes a Run.
export function newerRun(current: Run | null, incoming: Run): Run {
  return !current || current.run_id !== incoming.run_id || incoming.version > current.version ? incoming : current
}

function isCourseRun(run: Pick<Run, 'kind'>) { return !run.kind || run.kind === 'course' }

export function supersedingCourseRunId(run: Pick<Run, 'run_id' | 'kind' | 'course_id'>,
  course: Pick<Course, 'course_id' | 'creation_run_id'> | null): string | null {
  if (!isCourseRun(run) || !course || !run.course_id || run.course_id !== course.course_id ||
    !course.creation_run_id || course.creation_run_id === run.run_id) return null
  return course.creation_run_id
}

export function recoverableCourseRuns(runs: Run[], courses: Pick<Course, 'course_id' | 'creation_run_id'>[]): Run[] {
  const owners = new Map(courses.map(course => [course.course_id, course.creation_run_id]))
  const byId = new Map(runs.map(run => [run.run_id, run]))
  const superseded = new Set<string>()
  for (const child of runs) {
    if (!isCourseRun(child) || !child.parent_run_id) continue
    let parent = byId.get(child.parent_run_id)
    const seen = new Set<string>()
    while (parent && !seen.has(parent.run_id)) {
      superseded.add(parent.run_id)
      seen.add(parent.run_id)
      parent = parent.parent_run_id ? byId.get(parent.parent_run_id) : undefined
    }
  }
  const descendsFromOwner = (run: Run) => {
    let parent = run.parent_run_id ? byId.get(run.parent_run_id) : undefined
    const seen = new Set<string>()
    while (parent && !seen.has(parent.run_id)) {
      if (parent.course_id && owners.get(parent.course_id) === parent.run_id) return true
      seen.add(parent.run_id)
      parent = parent.parent_run_id ? byId.get(parent.parent_run_id) : undefined
    }
    return false
  }
  return runs.filter(run => isCourseRun(run) && run.status !== 'ready' &&
    (!run.course_id || !owners.get(run.course_id) || owners.get(run.course_id) === run.run_id || descendsFromOwner(run)) && !superseded.has(run.run_id))
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
