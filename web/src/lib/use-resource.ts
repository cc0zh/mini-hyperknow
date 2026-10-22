import { useCallback, useEffect, useState } from 'react'
import { describeError, request } from './api'

export function useResource<T>(path: string) {
  const [attempt, setAttempt] = useState(0)
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => setAttempt(value => value + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setLoading(true)
    setError(null)
    void request<T>(path, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setData(value)
    }).catch(cause => {
      if (!controller.signal.aborted) setError(describeError(cause))
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [path, attempt])

  return { data, loading, error, reload }
}
