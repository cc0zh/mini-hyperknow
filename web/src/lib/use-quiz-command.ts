import { useEffect, useRef, useState } from 'react'
import { ApiError, describeError, request } from './api'
import { ownsQuizCommand, preserveQuizCommand, quizFailure, readQuizCommand } from './quiz-state'
import type { QuizCommand } from './quiz-state'
import type { AttemptSnapshot, QuizSnapshot, Run } from './types'

export type QuizCommandResult = AttemptSnapshot | QuizSnapshot | Run
export function savedQuizCommand(key: string): QuizCommand | null {
  try { return readQuizCommand(sessionStorage.getItem(key)) } catch { return null }
}
function save(key: string, command: QuizCommand | null) {
  try {
    if (command) sessionStorage.setItem(key, JSON.stringify(command))
    else sessionStorage.removeItem(key)
  } catch { /* Keep the exact identity in memory if storage is unavailable. */ }
}

export function useQuizCommand(key: string, onSuccess: (value: QuizCommandResult) => Promise<void>, onConflict: () => Promise<void>) {
  const [pending, setPending] = useState(() => savedQuizCommand(key))
  const pendingRef = useRef(pending)
  const busyRef = useRef(false)
  const mounted = useRef(true)
  const [busy, setBusy] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [error, setError] = useState<string | null>(null)
  const [rejected, setRejected] = useState(false)

  function persist(command: QuizCommand | null) {
    pendingRef.current = command
    save(key, command)
    if (mounted.current) setPending(command)
  }
  function clearOwned(command: QuizCommand) {
    if (!mounted.current) return
    try {
      if (ownsQuizCommand(savedQuizCommand(key), command)) sessionStorage.removeItem(key)
    } catch { /* Preserve a newer page's command if storage cannot be read. */ }
    if (ownsQuizCommand(pendingRef.current, command)) {
      pendingRef.current = null
      setPending(null)
    }
  }
  async function execute(proposed?: QuizCommand) {
    if (busyRef.current || !navigator.onLine) return false
    const command = proposed ? preserveQuizCommand(pendingRef.current, proposed) : pendingRef.current
    if (!command) return false
    busyRef.current = true
    persist(command)
    setBusy(true)
    setError(null)
    setRejected(false)
    try {
      const value = await request<QuizCommandResult>(command.path, { method: command.method, body: JSON.stringify(command.body) })
      if (mounted.current) await onSuccess(value)
      clearOwned(command)
      return true
    } catch (cause) {
      const failure = cause instanceof ApiError ? quizFailure(cause.status, cause.code) : 'unknown'
      if (failure === 'conflict') {
        clearOwned(command)
        if (mounted.current) {
          await onConflict()
          setError(`${describeError(cause)}。已重新读取服务端状态，请确认后再操作。`)
        }
      } else if (mounted.current) {
        setError(describeError(cause))
        // Only definite input rejection can release an unconfirmed command.
        setRejected(failure === 'rejected')
      }
      return false
    } finally {
      busyRef.current = false
      if (mounted.current) setBusy(false)
    }
  }
  useEffect(() => {
    mounted.current = true
    const connected = () => setOnline(true)
    const disconnected = () => setOnline(false)
    window.addEventListener('online', connected)
    window.addEventListener('offline', disconnected)
    return () => {
      mounted.current = false
      window.removeEventListener('online', connected)
      window.removeEventListener('offline', disconnected)
    }
  }, [])

  return { pending, busy, online, error, rejected, execute,
    releaseRejected: () => { if (rejected && !busyRef.current && pendingRef.current) { clearOwned(pendingRef.current); setRejected(false); setError(null) } },
  }
}
