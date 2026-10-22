export interface ServiceError {
  code: string
  message: string
  retryable: boolean
}

export interface Health {
  status: 'ok'
  database: 'ok'
  model: { configured: boolean; name: string; verified: false }
}

export interface Question {
  id: string
  question: string
  type: 'single' | 'multi'
  allow_custom: boolean
  options: { id: string; label: string; description: string }[]
}

export interface Answer {
  question_id: string
  option_ids: string[]
  custom_text: string
}

export type RunStatus = 'queued' | 'clarifying' | 'awaiting_answers' | 'generating' | 'ready' | 'failed' | 'cancelled' | 'interrupted'

export interface Run {
  run_id: string
  goal: string
  status: RunStatus
  version: number
  questions: Question[]
  answers: Answer[]
  course_id: string | null
  error: ServiceError | null
  model: string
  created_at: string
  updated_at: string
  parent_run_id: string | null
  usage: Record<string, unknown> | null
}

export interface Session {
  session_id: string
  title: string
  description: string
  outline: string | string[]
  key_points: string[]
  estimated_minutes: number
}

export interface Unit {
  unit_id: string
  title: string
  description: string
  lectures: { lecture_id: string; title: string; description: string; sessions: Session[] }[]
  exams: { exam_id: string; title: string; goal: string }[]
  project_stages: { stage_id: string; project_id: string; title: string; description: string; deliverable: string }[]
}

export interface Course {
  course_id: string
  title: string
  description: string
  target_learner: string
  difficulty: 'beginner' | 'intermediate' | 'advanced'
  tags: string[]
  language: string
  projects: { project_id: string; name: string; description: string; final_deliverable: string }[]
  units: Unit[]
  goal: string
  created_at: string
  version: number
  session_count: number
  unit_count: number
  exam_count: number
  progress: number
  next_item: { type: 'lecture'; title: string; session_id: string; unit_id: string } | null
}
