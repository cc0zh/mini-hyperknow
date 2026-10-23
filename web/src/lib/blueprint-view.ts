import type { Course, Session, Unit } from './types.ts'

type NodeData = {
  course: Course
  unit: Unit
  lecture: Unit['lectures'][number]
  session: Session
  project: Course['projects'][number]
  stage: Unit['project_stages'][number]
  exam: Unit['exams'][number]
}

export type BlueprintKind = keyof NodeData
export type BlueprintNode = {
  [K in BlueprintKind]: {
    key: string
    kind: K
    title: string
    parentKey: string | null
    unitId: string | null
    data: NodeData[K]
  }
}[BlueprintKind]

// Tuple keys keep type and course namespaces separate, even for IDs containing separators.
export const blueprintKey = (courseId: string, kind: BlueprintKind, id: string) => JSON.stringify([courseId, kind, id])

export function blueprintNodes(course: Course): BlueprintNode[] {
  const key = (kind: BlueprintKind, id: string) => blueprintKey(course.course_id, kind, id)
  const rootKey = key('course', course.course_id)
  const nodes: BlueprintNode[] = [{ key: rootKey, kind: 'course', title: course.title, parentKey: null, unitId: null, data: course }]
  for (const project of course.projects) {
    nodes.push({ key: key('project', project.project_id), kind: 'project', title: project.name, parentKey: rootKey, unitId: null, data: project })
  }
  for (const unit of course.units) {
    const unitKey = key('unit', unit.unit_id)
    nodes.push({ key: unitKey, kind: 'unit', title: unit.title, parentKey: rootKey, unitId: unit.unit_id, data: unit })
    for (const lecture of unit.lectures) {
      const lectureKey = key('lecture', lecture.lecture_id)
      nodes.push({ key: lectureKey, kind: 'lecture', title: lecture.title, parentKey: unitKey, unitId: unit.unit_id, data: lecture })
      for (const session of lecture.sessions) {
        nodes.push({ key: key('session', session.session_id), kind: 'session', title: session.title, parentKey: lectureKey, unitId: unit.unit_id, data: session })
      }
    }
    for (const stage of unit.project_stages) {
      nodes.push({ key: key('stage', stage.stage_id), kind: 'stage', title: stage.title, parentKey: unitKey, unitId: unit.unit_id, data: stage })
    }
    for (const exam of unit.exams) {
      nodes.push({ key: key('exam', exam.exam_id), kind: 'exam', title: exam.title, parentKey: unitKey, unitId: unit.unit_id, data: exam })
    }
  }
  return nodes
}

// Version and generation updates never choose a different node or move focus.
export function resolveBlueprintSelection(nodes: BlueprintNode[], selectedKey: string | null): BlueprintNode {
  const selected = nodes.find(node => node.key === selectedKey) ?? nodes.find(node => node.kind === 'unit') ?? nodes[0]
  if (!selected) throw new Error('A blueprint must include its course root')
  return selected
}

export function blueprintStats(nodes: BlueprintNode[]) {
  return {
    units: nodes.filter(node => node.kind === 'unit').length,
    readyUnits: nodes.filter(node => node.kind === 'unit' && node.data.generation_status === 'ready').length,
    sessions: nodes.filter(node => node.kind === 'session').length,
    exams: nodes.filter(node => node.kind === 'exam').length,
    stages: nodes.filter(node => node.kind === 'stage').length,
  }
}
