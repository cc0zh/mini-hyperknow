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

export type RunStatus = 'queued' | 'clarifying' | 'awaiting_answers' | 'awaiting_blueprint' | 'generating' | 'ready' | 'failed' | 'cancelled' | 'interrupted'

export interface Research {
  steps: { tool: 'web_search' | 'read_webpage'; status: 'ready' | 'failed'; arguments: { query?: string; url?: string }; error?: { code: string; message: string } | null }[]
  sources: { source_id: string; url: string; title: string; text: string; fetched_at: string; truncated: boolean; content_sha256: string }[]
  report: { summary: string; findings: { title: string; summary: string; source_ids: string[] }[]; suggested_sequence: string[]; limitations: string[] } | null
}

export interface Run {
  workflow?: 'blueprint-v1'
  blueprint_version?: number
  current_unit_id?: string | null
  answers_submitted?: boolean
  skipped?: boolean
  blueprint_feedback?: string
  stage?: 'clarifying' | 'research' | 'blueprint' | 'units'
  research?: Research | null
  kind?: 'course' | 'lesson' | 'question' | 'quiz' | 'research'
  quiz_id?: string | null
  target_type?: 'practice' | 'exam' | null
  target_id?: string | null
  session_id?: string | null
  script_id?: string | null
  interaction_id?: string | null
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
  depths?: SessionDepth[]
  completed?: boolean
  session_id: string
  title: string
  description: string
  outline: string | string[]
  key_points: string[]
  estimated_minutes: number
}

export type SessionDepth = 'intuition' | 'definition' | 'derivation' | 'theory' | 'practice'
export type UnitGenerationStatus = 'pending' | 'generating' | 'ready' | 'failed' | 'cancelled' | 'interrupted'

export interface Unit {
  learning_objectives?: string[]
  estimated_sessions?: number
  project_keys?: string[]
  exam_goal?: string
  generation_status?: UnitGenerationStatus
  unit_id: string
  title: string
  description: string
  lectures: { lecture_id: string; title: string; description: string; sessions: Session[] }[]
  exams: { exam_id: string; title: string; goal: string; completed?: boolean }[]
  project_stages: { stage_id: string; project_id: string; title: string; description: string; deliverable: string }[]
}

export interface Course {
  structure_status?: 'blueprint' | 'expanding' | 'ready'
  blueprint_version?: number
  creation_run_id?: string | null
  course_id: string
  title: string
  description: string
  target_learner: string
  difficulty: 'beginner' | 'intermediate' | 'advanced'
  tags: string[]
  language: string
  projects: { project_id: string; project_key?: string; name: string; description: string; final_deliverable: string }[]
  units: Unit[]
  goal: string
  created_at: string
  version: number
  session_count: number
  unit_count: number
  exam_count: number
  progress: number | null
  next_item: { type: 'lecture' | 'session' | 'project' | 'project_stage' | 'exam' | 'generation'; title: string; session_id?: string; unit_id: string; stage_id?: string; exam_id?: string; run_id?: string } | null
}

export type PlayIntent = 'paused' | 'playing'
export interface BoardOperation {
  kind: 'text' | 'list' | 'code' | 'formula' | 'box' | 'arrow' | 'highlight' | 'mermaid' | 'table' | 'diagram' | 'circle'
  object_id: string
  target_ids: string[]
  content: string
  items: string[]
  language: string
  columns: string[]
  rows: string[][]
  nodes: { id: string; label: string }[]
  edges: { from_id: string; to_id: string; label: string }[]
}
export interface BoardFrame {
  step_id: string
  title: string
  narration: string
  page: number
  column: 1 | 2
  operations: BoardOperation[]
}
export interface BoardStep extends BoardFrame {
  stage: 'opening' | 'explain' | 'example' | 'check' | 'summary'
  keypoint_id: string | null
  focus_ids: string[]
  check: { question: string; expected_answer: string } | null
}
export interface BoardScript {
  script_id: string
  session_id: string
  course_id: string
  content_version: number
  schema_version: 2
  title: string
  objectives: string[]
  roadmap: { keypoint_id: string; title: string; question: string; source_keypoint_index: number }[]
  steps: BoardStep[]
  created_at: string
}
export interface LessonProgress {
  script_id: string | null
  cursor: number
  play_intent: PlayIntent
  version: number
  updated_at: string
}
export interface Interaction {
  interaction_id: string
  run_id: string
  script_id: string
  step_id: string | null
  anchor_step_id: string | null
  anchor_object_id: string | null
  cursor: number
  question: string
  answer: string | null
  was_playing: boolean
  status: 'pending' | 'ready' | 'failed' | 'cancelled' | 'interrupted'
  error: ServiceError | null
  created_at: string
}
export interface LessonSnapshot {
  version: number
  course_id: string
  course_title: string
  unit_title: string
  lecture_title: string
  session: Session
  script: BoardScript | null
  format_error: ServiceError | null
  progress: LessonProgress
  interactions: Interaction[]
  generation_run: Run | null
  completed: boolean
}

export type QuizTargetType = 'practice' | 'exam'
export interface QuizQuestion {
  question_id: string
  kind: 'single' | 'multiple' | 'boolean'
  prompt: string
  options: { id: string; text: string }[]
  correct_option_ids: string[]
  explanation: string
  source_refs: string[]
}
export interface Quiz {
  quiz_id: string
  course_id: string
  unit_id: string
  target_type: QuizTargetType
  target_id: string
  title: string
  content_version: number
  schema_version: number
  source_refs: string[]
  questions: QuizQuestion[]
  created_at: string
}
export interface QuizAnswer {
  question_id: string
  option_ids: string[]
  skipped: boolean
  elapsed_ms: number
  correct: boolean
  fast: boolean
  points: number
  answered_at: string
}
export interface QuizResult {
  total_score: number
  max_score: number
  correct_count: number
  question_count: number
  skipped_count: number
  fast_count: number
  best_streak: number
  stars: number
  total_elapsed_ms: number
  scoring_version: number
}
export interface QuizAttempt {
  attempt_id: string
  quiz_id: string
  course_id: string
  target_type: QuizTargetType
  target_id: string
  status: 'in_progress' | 'submitted'
  version: number
  cursor: number
  question_started_at: string
  answers: QuizAnswer[]
  result: QuizResult | null
  created_at: string
  updated_at: string
  submitted_at: string | null
}
export interface QuizSnapshot {
  course_id: string
  unit_id: string
  target_type: QuizTargetType
  target_id: string
  title: string
  description: string
  quiz: Quiz | null
  generation_run: Run | null
  latest_attempt: QuizAttempt | null
  completed: boolean
  version: number
}
export interface AttemptSnapshot {
  quiz: Quiz
  attempt: QuizAttempt
  course: Course
}
