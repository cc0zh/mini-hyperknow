import { useEffect, useRef, useState } from 'react'
import { ApiError, describeError, request } from './api'
import { lessonStorageKey } from './lesson-state'
import type { LessonSnapshot, Run } from './types'
import type { useLesson } from './use-lesson'

interface TeacherCommand {
  path: string
  body: Record<string, unknown> & { client_command_id: string }
}

function readSaved<T>(key: string): T | null {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') as T | null } catch { return null }
}
function save(key: string, value: unknown) {
  try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* The in-memory command remains authoritative for this visit. */ }
}

export function useTeacherClassroom(sessionId: string, lesson: ReturnType<typeof useLesson>) {
  const key = `${lessonStorageKey(sessionId)}.teacher`
  const [pending, setPending] = useState<TeacherCommand | null>(() => readSaved(key))
  const pendingRef = useRef(pending)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [online, setOnline] = useState(navigator.onLine)
  const mounted = useRef(true)

  function persist(command: TeacherCommand | null) {
    pendingRef.current = command
    save(key, command)
    if (mounted.current) setPending(command)
  }
  function make(path: string, body: Record<string, unknown> = {}): TeacherCommand {
    return { path, body: { ...body, client_command_id: crypto.randomUUID() } }
  }
  async function execute(proposed?: TeacherCommand): Promise<boolean> {
    if (busy) return false
    const command = pendingRef.current ?? proposed
    if (!command) return false
    persist(command)
    setBusy(true)
    setError(null)
    try {
      const snapshot = await request<LessonSnapshot>(command.path, { method: 'POST', body: JSON.stringify(command.body) })
      lesson.accept(snapshot)
      persist(null)
      return true
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        persist(null)
        await lesson.reload()
        setError('课堂状态已在其他页面更新，已重新同步。请检查最新教学回合后再试。')
      } else setError(describeError(cause))
      return false
    } finally { if (mounted.current) setBusy(false) }
  }
  async function runAction(runId: string, action: 'retry' | 'cancel') {
    if (busy || pendingRef.current) return
    setBusy(true)
    try {
      const run = await request<Run>(`/runs/${encodeURIComponent(runId)}`)
      const result = await request<Run>(`/runs/${encodeURIComponent(runId)}/${action}`, {
        method: 'POST', body: JSON.stringify({ expected_version: run.version, client_command_id: crypto.randomUUID() }),
      })
      if (result.session_id) await lesson.reload()
    } catch (cause) { setError(describeError(cause)) }
    finally { if (mounted.current) setBusy(false) }
  }
  useEffect(() => {
    mounted.current = true
    const offline = () => setOnline(false)
    const connected = () => setOnline(true)
    window.addEventListener('offline', offline); window.addEventListener('online', connected)
    return () => { mounted.current = false; window.removeEventListener('offline', offline); window.removeEventListener('online', connected) }
  }, [])

  const snapshot = lesson.snapshot
  const teacher = snapshot?.teacher
  return {
    pending, busy, error, online,
    prepare: () => execute(make(`/sessions/${encodeURIComponent(sessionId)}/teacher/prepare`)),
    turn: (studentAnswer?: string) => {
      if (!teacher || !online) return Promise.resolve(false)
      const body: Record<string, unknown> = { expected_version: teacher.version }
      if (studentAnswer !== undefined) body.student_answer = studentAnswer.trim()
      return execute(make(`/sessions/${encodeURIComponent(sessionId)}/teacher/turns`, body))
    },
    retry: () => execute(),
    runAction,
    clearError: () => setError(null),
  }
}
