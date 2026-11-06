import type { BoardScript, BoardStep, Interaction, LessonSnapshot, PlayIntent, Run } from './types.ts'

const terminal = (status: string) => ['ready', 'failed', 'cancelled', 'interrupted'].includes(status)
export const activeRun = (run: Run | null) => !!run && !terminal(run.status)
export const activeInteraction = (item: Interaction) => !terminal(item.status)

export const interactionIdentity = (item: Pick<Interaction, 'interaction_id' | 'run_id'>) => `${item.interaction_id}:${item.run_id}`
export const acknowledgeInteraction = (acknowledged: readonly string[], identity: string): string[] => [...new Set([...acknowledged, identity])]
export function heldInteraction(interactions: Interaction[], acknowledged: readonly string[]): Interaction | undefined {
  return interactions.find(activeInteraction) ?? [...interactions].reverse().find(item => !acknowledged.includes(interactionIdentity(item)))
}

// Session version covers every fact, including answers whose progress version
// is unchanged. Never merge a stale interaction array into a newer snapshot.
export function mergeLesson(current: LessonSnapshot | null, incoming: LessonSnapshot): LessonSnapshot {
  if (!current || current.session.session_id !== incoming.session.session_id) return incoming
  return incoming.version > current.version ? incoming : current
}

export interface BoardColumn { page: number; column: 1 | 2; steps: BoardStep[] }
export function boardPrefix(script: BoardScript, cursor: number): BoardColumn[] {
  const columns = new Map<string, BoardColumn>()
  for (const step of script.steps.slice(0, Math.max(0, cursor + 1))) {
    const key = `${step.page}:${step.column}`
    if (!columns.has(key)) columns.set(key, { page: step.page, column: step.column, steps: [] })
    columns.get(key)!.steps.push(step)
  }
  return [...columns.values()].sort((a, b) => a.page - b.page || a.column - b.column)
}

export function readingDelay(narration: string): number {
  return Math.min(30_000, Math.max(4_000, Array.from(narration).length * 95))
}

// A single clock owns automatic advancement. Its epoch invalidates even an
// already-queued callback when Next, Pause, a question or unmount cancels it.
export class PlaybackClock {
  private timer: ReturnType<typeof setTimeout> | undefined
  private epoch = 0
  private reserved = false
  playing = false
  pauseVersion = 0

  cancel() { this.epoch += 1; clearTimeout(this.timer); this.timer = undefined }
  pause() { this.pauseVersion += 1; this.playing = false; this.cancel() }
  play() { this.cancel(); this.playing = true }
  reserve(): boolean {
    this.cancel()
    if (this.reserved) return false
    this.reserved = true
    return true
  }
  release() { this.reserved = false }
  schedule(delay: number, advance: () => void) {
    this.cancel()
    if (!this.playing || this.reserved) return
    const epoch = this.epoch
    this.timer = setTimeout(() => {
      if (this.playing && !this.reserved && epoch === this.epoch) advance()
    }, delay)
  }
}

export function resumeIntent(wasPlaying: boolean, explicitlyContinued: boolean): PlayIntent {
  return wasPlaying && explicitlyContinued ? 'playing' : 'paused'
}

export function nextCursor(cursor: number, length: number): number | null {
  return cursor + 1 < length ? cursor + 1 : null
}

export function summaryIsShown(script: BoardScript | null, cursor: number): boolean {
  return !!script && script.steps.length > 0 && cursor === script.steps.length - 1 && script.steps[cursor].stage === 'summary'
}

export interface QuestionAnchor { anchor_step_id?: string; anchor_object_id?: string }
export function questionAnchor(script: BoardScript, teachingCursor: number, viewCursor: number, objectId?: string | null): QuestionAnchor | null {
  if (viewCursor < 0 || viewCursor > teachingCursor || !script.steps[viewCursor]) return null
  const step = script.steps[viewCursor]
  if (!objectId) return { anchor_step_id: step.step_id }
  const owner = script.steps.slice(0, viewCursor + 1).find(item => item.operations.some(operation => operation.object_id === objectId || operation.nodes.some(node => node.id === objectId)))
  return owner ? { anchor_step_id: owner.step_id, anchor_object_id: objectId } : null
}

export interface LessonCommand {
  method: 'POST' | 'PUT'
  path: string
  body: Record<string, unknown> & { client_command_id: string }
  // UI acknowledgement is persisted only after its progress command succeeds.
  continue_interaction?: string
  question_after_pause?: { question: string; was_playing: boolean } & QuestionAnchor
}

export function lessonCommand(pending: LessonCommand | null, next: LessonCommand): LessonCommand {
  return pending ?? next
}

export const lessonStorageKey = (id: string) => `hyperknow.lesson.${id}`
