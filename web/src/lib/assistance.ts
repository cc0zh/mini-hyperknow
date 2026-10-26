import { request } from './api.ts'
import type { BoardScript, BoardStep, ServiceError } from './types.ts'

// Artifact kind is the model's decision, not a learner-facing choice. Only
// these two turn intents exist: an ordinary teaching message and an explicit
// advance through an already saved plan.
export type AssistanceAction = 'message' | 'continue'
export type AssistanceStatus = 'queued' | 'generating' | 'ready' | 'failed' | 'cancelled' | 'interrupted'
export interface AssistanceQuestion { question_id: string; question: string; options: string[]; multiple: boolean }
export interface AssistanceResponse {
  text: string
  questions: AssistanceQuestion[]
  plan: string[]
  current_step: number
  waiting_for: 'answer' | 'continue' | 'none'
  suggestions?: AssistanceSuggestion[]
}
export interface AssistanceSuggestion { label: string; text: string; action: AssistanceAction }
export interface AssistanceRun {
  run_id: string
  version: number
  status: AssistanceStatus
  input?: { artifact_id?: string }
  steps?: AssistanceStep[]
}
// Steps are the recorded teaching-agent trace already persisted on the run
// (skill load, artifact creation). They stay on the saved turn after the run
// finishes, so a ready reply is still legible as the steps that produced it.
export interface AssistanceStep { tool: string; status: string; name?: string; version?: string; title?: string }
interface ArtifactBase { artifact_id: string; conversation_id: string; turn_id: string; title: string; version: number }
export type AssistanceArtifact = ArtifactBase & (
  { kind: 'flashcards'; data: { cards: { question: string; answer: string }[] } } |
  { kind: 'quiz'; data: { questions: { question_id: string; question: string; options: { id: string; text: string }[]; correct_ids: string[]; explanation: string }[] } } |
  { kind: 'whiteboard'; data: { steps: BoardStep[]; cursor: number } } |
  { kind: 'animation'; data: { html: string } } |
  { kind: 'diagram'; data: { source: string; caption: string } }
) & { version: number; feedback?: 'up' | 'down'; feedback_at?: string }
export type WhiteboardArtifact = Extract<AssistanceArtifact, { kind: 'whiteboard' }>
export interface AssistanceTurn {
  turn_id: string
  run_id: string
  user_text: string
  action: AssistanceAction
  status: AssistanceStatus
  response: AssistanceResponse | null
  artifacts: AssistanceArtifact[]
  skill_uses: { name: string; version: string; sha256: string }[]
  steps: AssistanceStep[]
  error: ServiceError | null
}
export interface AssistanceSummary { conversation_id: string; title: string; version: number; created_at: string; updated_at: string }
export interface AssistanceConversation extends AssistanceSummary { turns: AssistanceTurn[]; active_run: AssistanceRun | null }
export interface PendingAssistanceCommand {
  method: 'POST' | 'PUT'
  path: string
  body: Record<string, unknown> & { client_command_id: string }
  conversationId: string
  question_after_save?: { text: string; artifact_id: string }
}

export const assistanceLabels: Record<AssistanceAction, string> = { message: '提问', continue: '继续讲解' }
export const artifactLabels: Record<AssistanceArtifact['kind'], string> = { flashcards: '闪卡', quiz: '测验', whiteboard: '白板', animation: '动画', diagram: '结构图' }
export const assistanceStatusLabels: Record<AssistanceStatus, string> = { queued: '排队中', generating: '生成中', ready: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' }
export function assistanceStepLabel(step: AssistanceStep): string {
  if (step.tool === 'get_skills') return step.name ? `加载技能 · ${step.name}` : '加载技能'
  const createLabels: Record<string, string> = { create_flashcards: '生成闪卡', create_quiz: '生成测验', create_whiteboard: '生成白板', create_animation: '生成动画', create_diagram: '生成结构图' }
  return createLabels[step.tool] ?? step.tool
}
export const planProgressPercent = (current: number, total: number) => total > 0 ? Math.round(((current + 1) / total) * 100) : 0
export const conversationPath = (id: string) => `/assistance/conversations/${encodeURIComponent(id)}`
export const artifactPath = (id: string) => `/assistance/artifacts/${encodeURIComponent(id)}`
export const conversationRoute = (id: string) => `/assistance/${encodeURIComponent(id)}`
export const boardArtifactPath = (id: string) => `/assistance/boards/${encodeURIComponent(id)}`
export const commandScope = (id: string) => `conversation:${id}`
const commandKey = (scope: string) => `hyperknow.assistance.command.${scope}`

export function readAssistanceCommand(scope: string): PendingAssistanceCommand | null {
  try {
    return pendingCommandForScope(JSON.parse(sessionStorage.getItem(commandKey(scope)) || 'null'), scope)
  } catch { return null }
}
export function pendingCommandForScope(input: unknown, scope: string): PendingAssistanceCommand | null {
  if (!input || typeof input !== 'object') return null
  const value = input as PendingAssistanceCommand
  if (!['POST', 'PUT'].includes(value.method) || typeof value.path !== 'string' || !value.body || typeof value.body !== 'object' || Array.isArray(value.body) ||
    typeof value.body.client_command_id !== 'string' || typeof value.conversationId !== 'string') return null
  if (scope === 'create') return value.method === 'POST' && value.path === '/assistance/conversations' && value.conversationId === '' ? value : null
  if (scope !== commandScope(value.conversationId) || !Number.isInteger(value.body.expected_version) || Number(value.body.expected_version) < 1) return null
  const validPath = value.method === 'PUT' ? /^\/assistance\/artifacts\/[^/?#]+\/(progress|feedback)$/.test(value.path)
    : value.path === `${conversationPath(value.conversationId)}/turns` || /^\/runs\/[^/?#]+\/(cancel|retry)$/.test(value.path)
  if (!validPath) return null
  if (value.question_after_save !== undefined && (!value.question_after_save || typeof value.question_after_save !== 'object' ||
    typeof value.question_after_save.text !== 'string' || !validTurn(value.question_after_save.text) ||
    typeof value.question_after_save.artifact_id !== 'string' || !value.question_after_save.artifact_id ||
    value.method !== 'PUT' || value.path !== `${artifactPath(value.question_after_save.artifact_id)}/progress`)) return null
  return value
}
export function saveAssistanceCommand(scope: string, command: PendingAssistanceCommand | null) {
  try { command ? sessionStorage.setItem(commandKey(scope), JSON.stringify(command)) : sessionStorage.removeItem(commandKey(scope)) } catch { /* This visit retains the exact command in memory. */ }
}
export const ownsAssistanceCommand = (stored: PendingAssistanceCommand | null, done: PendingAssistanceCommand) =>
  stored?.method === done.method && stored.path === done.path && stored.body.client_command_id === done.body.client_command_id
export const prepareAssistanceCommand = (pending: PendingAssistanceCommand | null, proposed: PendingAssistanceCommand | null) => pending ?? proposed

export function mergeArtifact<T extends AssistanceArtifact>(current: T | null, incoming: T): T {
  return !current || current.artifact_id !== incoming.artifact_id || incoming.version > current.version ? incoming : current
}

// A replayed command may target a different board in this conversation. It can
// complete its receipt/question chain, but must never replace the current URL.
export function matchesAssistanceResource(path: string, resource: AssistanceConversation | AssistanceArtifact): boolean {
  return path === ('turns' in resource ? conversationPath(resource.conversation_id) : artifactPath(resource.artifact_id))
}
export function mergeConversation(current: AssistanceConversation | null, incoming: AssistanceConversation): AssistanceConversation {
  if (!current || current.conversation_id !== incoming.conversation_id) return incoming
  const base = incoming.version > current.version ? incoming : current
  // Artifact cursors have their own version; saving one need not increment the
  // conversation version. A conversation GET must retain newer artifact facts.
  const artifacts = new Map(current.turns.flatMap(turn => turn.artifacts).map(artifact => [artifact.artifact_id, artifact]))
  incoming.turns.flatMap(turn => turn.artifacts).forEach(artifact => artifacts.set(artifact.artifact_id, mergeArtifact(artifacts.get(artifact.artifact_id) ?? null, artifact)))
  return { ...base, turns: base.turns.map(turn => ({ ...turn, artifacts: turn.artifacts.map(artifact => artifacts.get(artifact.artifact_id) ?? artifact) })) }
}
export function makeAssistanceCommand(conversationId: string, path: string, body: Record<string, unknown>, method: 'POST' | 'PUT' = 'POST'): PendingAssistanceCommand {
  return { conversationId, path, method, body: { ...body, client_command_id: crypto.randomUUID() } }
}
export function makeTurnCommand(conversation: AssistanceConversation, text: string, action: AssistanceAction, artifact_id?: string) {
  return makeAssistanceCommand(conversation.conversation_id, `${conversationPath(conversation.conversation_id)}/turns`, {
    expected_version: conversation.version, text, action, ...(artifact_id ? { artifact_id } : {}),
  })
}
// Every turn needs the learner's own words, including an explicit advance.
export const validTurn = (text: string) => text.trim().length > 0 && text.trim().length <= 12000
export const validBoardCursor = (previous: number, next: number, count: number) => Number.isInteger(next) && next >= -1 && next < count && (next === previous || next === previous + 1)
export const isAdvanceAllowed = (cursor: number, count: number, pendingQuestion: boolean) => !pendingQuestion && cursor + 1 < count
export const makeBoardScript = (artifact: WhiteboardArtifact): BoardScript => ({
  script_id: artifact.artifact_id, session_id: '', course_id: '', content_version: artifact.version, schema_version: 1,
  title: artifact.title, steps: artifact.data.steps, created_at: '',
})
export function selectQuizOption(selected: string[], id: string, correctIds: string[]) {
  return correctIds.length > 1 ? selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id] : [id]
}
export const quizAnswerCorrect = (selected: string[], correct: string[]) => selected.length === correct.length && selected.every(id => correct.includes(id))
export function clarificationText(questions: AssistanceQuestion[], selected: Record<string, string[]>, custom: string) {
  return [...questions.flatMap(question => selected[question.question_id]?.length ? [`${question.question}\n${selected[question.question_id].join('、')}`] : []), custom.trim()].filter(Boolean).join('\n\n')
}
export const getConversation = (id: string, signal?: AbortSignal) => request<AssistanceConversation>(conversationPath(id), { signal })
export const getArtifact = (id: string, signal?: AbortSignal) => request<AssistanceArtifact>(artifactPath(id), { signal })
