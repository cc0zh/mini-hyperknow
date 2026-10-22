import { useEffect, useRef, useState } from 'react'
import { ApiError, describeError, isInputRejection, request } from './api'
import { acknowledgeInteraction, activeInteraction, heldInteraction, interactionIdentity, lessonCommand, lessonStorageKey, nextCursor, PlaybackClock, readingDelay, resumeIntent } from './lesson-state'
import type { LessonCommand } from './lesson-state'
import type { Interaction, LessonSnapshot, PlayIntent, Run } from './types'
import type { useLesson } from './use-lesson'

type StoredCommand = LessonCommand
function readSaved<T>(key: string): T | null {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') as T | null } catch { return null }
}
function save(key: string, value: unknown) {
  try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* Memory identity still protects this visit. */ }
}

export function useLessonPlayer(sessionId: string, lesson: ReturnType<typeof useLesson>) {
  const key = lessonStorageKey(sessionId)
  const clock = useRef(new PlaybackClock()).current
  // GET preserves authoritative play_intent for version/idempotency consistency.
  // Recovery still creates a paused local clock; snapshots never call play().
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejected, setRejected] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState<StoredCommand | null>(() => readSaved(key))
  const pendingRef = useRef(pending)
  const preparingAction = useRef(false)
  const mounted = useRef(true)
  const [acknowledged, setAcknowledged] = useState<string[]>(() => {
    const saved = readSaved<unknown>(`${key}.continued`)
    return Array.isArray(saved) ? saved.filter((value): value is string => typeof value === 'string') : []
  })
  const acknowledgedRef = useRef(acknowledged)
  const snapshot = lesson.snapshot
  const hold: Interaction | undefined = heldInteraction(snapshot?.interactions ?? [], acknowledged)
  const holdRef = useRef(hold)
  holdRef.current = hold

  function stop() { clock.pause(); setPlaying(false) }
  function persistPending(command: StoredCommand | null) {
    pendingRef.current = command
    save(key, command)
    if (mounted.current) setPending(command)
  }
  function make(path: string, body: Record<string, unknown>, method: 'POST' | 'PUT' = 'POST'): StoredCommand {
    return { method, path, body: { ...body, client_command_id: crypto.randomUUID() } }
  }
  function progress(intent: PlayIntent, cursor?: number): StoredCommand | null {
    const current = lesson.current.current
    if (!current?.script) return null
    return make(`/sessions/${encodeURIComponent(sessionId)}/progress`, {
      expected_version: current.progress.version, script_id: current.script.script_id,
      cursor: cursor ?? current.progress.cursor, play_intent: intent,
    }, 'PUT')
  }

  async function execute(proposed?: StoredCommand, startPlaying = false): Promise<boolean> {
    if (preparingAction.current) return false
    if (!clock.reserve()) return false
    const pauseVersion = clock.pauseVersion
    let command = pendingRef.current ?? proposed
    if (!command) { clock.release(); return false }
    command = lessonCommand(pendingRef.current, command)
    persistPending(command)
    setBusy(true)
    setError(null)
    setRejected(false)
    try {
      while (command) {
        const result = await request<LessonSnapshot | Run>(command.path, { method: command.method, body: JSON.stringify(command.body) })
        if ('progress' in result) lesson.accept(result)
        else await lesson.reload()
        if (command.continue_interaction) {
          const confirmed = acknowledgeInteraction(acknowledgedRef.current, command.continue_interaction)
          acknowledgedRef.current = confirmed
          save(`${key}.continued`, confirmed)
          if (mounted.current) setAcknowledged(confirmed)
        }
        if (command.question_after_pause && 'progress' in result) {
          const question = command.question_after_pause
          command = make(`/sessions/${encodeURIComponent(sessionId)}/questions`, {
            ...question, expected_version: result.progress.version,
            script_id: result.progress.script_id, cursor: result.progress.cursor,
          })
          persistPending(command)
        } else { command = undefined; persistPending(null) }
      }
      if (mounted.current && startPlaying && navigator.onLine && pauseVersion === clock.pauseVersion) { clock.play(); setPlaying(true) }
      return true
    } catch (cause) {
      stop()
      if (cause instanceof ApiError && cause.status === 409) {
        // Rejected version never wins against the server. Release this identity
        // only for a confirmed conflict, then read the authoritative snapshot.
        persistPending(null)
        await lesson.reload()
        setError('课堂已在其他页面更新，已重新同步。请检查当前位置后重新操作。')
      } else {
        setRejected(isInputRejection(cause))
        setError(describeError(cause))
      }
      return false
    } finally {
      clock.release()
      if (mounted.current) setBusy(false)
    }
  }

  async function advance() {
    clock.cancel()
    const current = lesson.current.current
    if (!current?.script || pendingRef.current || holdRef.current || !navigator.onLine) return
    const cursor = nextCursor(current.progress.cursor, current.script.steps.length)
    if (cursor === null) { stop(); return }
    const command = progress(clock.playing ? 'playing' : 'paused', cursor)
    if (command) await execute(command, clock.playing)
  }
  async function play() {
    if (pendingRef.current || holdRef.current) return
    const command = progress('playing')
    if (command) await execute(command, true)
  }
  async function pause() {
    stop()
    if (pendingRef.current) return
    const command = progress('paused')
    if (command) await execute(command)
  }
  async function ask(question: string) {
    if (pendingRef.current || holdRef.current || question.trim().length < 2 || question.trim().length > 2000) return false
    const wasPlaying = clock.playing
    stop()
    const command = progress('paused')
    if (!command) return false
    command.question_after_pause = { question: question.trim(), was_playing: wasPlaying }
    return execute(command)
  }
  async function continueLesson() {
    const item = holdRef.current
    if (!item || activeInteraction(item) || pendingRef.current) return
    const intent = resumeIntent(item.was_playing, true)
    const command = progress(intent)
    if (!command) return
    command.continue_interaction = interactionIdentity(item)
    await execute(command, intent === 'playing')
  }
  async function runAction(runId: string, action: 'retry' | 'cancel') {
    stop()
    if (pendingRef.current || preparingAction.current) return
    preparingAction.current = true
    setBusy(true)
    try {
      const run = await request<Run>(`/runs/${encodeURIComponent(runId)}`)
      preparingAction.current = false
      await execute(make(`/runs/${encodeURIComponent(runId)}/${action}`, { expected_version: run.version }))
    } catch (cause) { setError(describeError(cause)) }
    finally { preparingAction.current = false; if (mounted.current) setBusy(false) }
  }

  useEffect(() => {
    mounted.current = true
    const offline = () => { clock.pause(); setPlaying(false); setOnline(false) }
    const connected = () => setOnline(true)
    window.addEventListener('offline', offline)
    window.addEventListener('online', connected)
    return () => {
      mounted.current = false
      clock.pause()
      window.removeEventListener('offline', offline)
      window.removeEventListener('online', connected)
    }
  }, [clock])

  const cursor = snapshot?.progress.cursor ?? -1
  const scriptId = snapshot?.script?.script_id
  const narration = snapshot?.script?.steps[cursor]?.narration ?? ''
  const final = !!snapshot?.script && cursor === snapshot.script.steps.length - 1
  useEffect(() => {
    if (playing && !busy && !pending && !hold && online && !final) clock.schedule(readingDelay(narration), () => { void advance() })
    return () => clock.cancel()
    // Rendering diagrams/fonts and polling an unchanged snapshot never reset or
    // advance this clock. Only confirmed teaching state controls it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock, playing, busy, pending, hold?.interaction_id, hold?.run_id, online, final, cursor, scriptId, narration])
  useEffect(() => { if (final || hold || lesson.error) stop() }, [final, hold?.interaction_id, hold?.run_id, lesson.error])

  return {
    playing, busy, pending, error, rejected, hold, online, advance, play, pause, ask, continueLesson, runAction,
    retry: () => execute(),
    releaseRejected: () => { if (rejected && !busy) { persistPending(null); setRejected(false); setError(null) } },
    prepare: () => { if (!pendingRef.current) return execute(make(`/sessions/${encodeURIComponent(sessionId)}/prepare`, {})); return Promise.resolve(false) },
    complete: () => {
      stop()
      const current = lesson.current.current
      if (!current?.script || pendingRef.current) return Promise.resolve(false)
      return execute(make(`/sessions/${encodeURIComponent(sessionId)}/complete`, { expected_version: current.progress.version, script_id: current.script.script_id }))
    },
  }
}
