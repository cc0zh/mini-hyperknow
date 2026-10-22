import { useEffect, useRef, useState } from 'react'
import { ApiError, describeError, isInputRejection, post } from './api'
import { prepareCommand, readPending, savePending } from './commands'
import type { PendingCommand } from './commands'

// A failed command retains the exact body and ID, including across page refresh.
// Until it is reconciled, edits and other mutations must remain disabled.
export function useCommand<T>(scope: string, onSuccess: (value: T) => void) {
  const [pending, setPending] = useState<PendingCommand | null>(() => readPending(scope))
  const pendingRef = useRef(pending)
  const busyRef = useRef(false)
  const mounted = useRef(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [rejected, setRejected] = useState(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  async function execute(path?: string, body?: Record<string, unknown>) {
    if (busyRef.current) return
    const command = prepareCommand(pendingRef.current, path, body, crypto.randomUUID())
    if (!command) return
    busyRef.current = true
    pendingRef.current = command
    setPending(command)
    savePending(scope, command)
    setBusy(true)
    setError(null)
    setConflict(false)
    setRejected(false)
    try {
      const value = await post<T>(command.path, command.body)
      savePending(scope, null)
      pendingRef.current = null
      setPending(null)
      if (mounted.current) onSuccess(value)
    } catch (cause) {
      setError(describeError(cause))
      setConflict(cause instanceof ApiError && cause.status === 409)
      setRejected(isInputRejection(cause))
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  function releaseConflict() {
    if (!conflict || busyRef.current) return
    savePending(scope, null)
    pendingRef.current = null
    setPending(null)
    setConflict(false)
    setError(null)
  }

  function releaseRejected() {
    if (!rejected || busyRef.current) return
    savePending(scope, null)
    pendingRef.current = null
    setPending(null)
    setRejected(false)
    setError(null)
  }

  return { pending, busy, error, conflict, rejected, execute, releaseConflict, releaseRejected }
}
