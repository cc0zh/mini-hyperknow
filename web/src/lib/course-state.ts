import type { Course, Run, SessionDepth, Unit, UnitGenerationStatus } from './types.ts'

export const depthLabels: Record<SessionDepth, string> = {
  intuition: '建立直觉', definition: '正式定义', derivation: '公式推导', theory: '进阶理论', practice: '应用实操',
}

export const unitGenerationLabels: Record<UnitGenerationStatus, string> = {
  pending: '等待展开', generating: '正在展开', ready: '已就绪', failed: '展开失败', cancelled: '已取消', interrupted: '展开中断',
}

export const structurePending = (course: Pick<Course, 'structure_status'>) => course.structure_status === 'blueprint' || course.structure_status === 'expanding'
// A partial directory must never imply that the entire course is complete.
export const courseProgress = (course: Pick<Course, 'structure_status' | 'progress'>) => structurePending(course) ? null : course.progress
export const readyUnitCount = (units: Unit[]) => units.filter(unit => unit.generation_status === 'ready').length
export const unitSessionCount = (unit: Unit) => unit.lectures.reduce((sum, lecture) => sum + lecture.sessions.length, 0)

// Authorize review from matching persisted identities, not one particular GET's
// Promise. A later successful automatic read must also recover the controls.
export function canReviewBlueprint(run: Pick<Run, 'run_id' | 'status' | 'blueprint_version'>,
  course: Pick<Course, 'structure_status' | 'blueprint_version' | 'creation_run_id'> | null): boolean {
  return run.status === 'awaiting_blueprint' && !!run.blueprint_version && !!course &&
    course.structure_status === 'blueprint' && course.blueprint_version === run.blueprint_version &&
    course.creation_run_id === run.run_id
}

// HTTP is authoritative; notifications only invalidate it. Equal/stale reads do not replace it.
export function newerCourse(current: Course | null, incoming: Course): Course {
  return !current || current.course_id !== incoming.course_id || incoming.version > current.version ? incoming : current
}
