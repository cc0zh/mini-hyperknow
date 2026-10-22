import { useCallback, useEffect, useRef, useState } from 'react'
import { describeError, request } from './api'
import { isTerminal, newerRun } from './run-state'
import type { Run } from './types'

export function useRun(runId: string) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState('正在连接状态通知…')
  const refreshRef = useRef<() => void>(() => {})
  const current = useRef<Run | null>(null)
  const accept = useCallback((value: Run) => {
    if (value.run_id !== runId) return
    current.current = newerRun(current.current, value)
    setRun(current.current)
  }, [runId])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let handshake: ReturnType<typeof setTimeout> | undefined
    let fetching = false
    let dirty = false
    let subscribed = false
    let fallback = false
    const controller = new AbortController()
    const topic = `run:${runId}`
    current.current = null
    setRun(null)
    setError(null)
    setConnection('正在连接状态通知…')

    async function refresh() {
      if (stopped) return
      if (fetching) { dirty = true; return }
      fetching = true
      do {
        dirty = false
        try {
          const value = await request<Run>(`/runs/${encodeURIComponent(runId)}`, { signal: controller.signal })
          if (stopped) return
          accept(value)
          setError(null)
        } catch (cause) {
          if (!stopped) setError(describeError(cause))
        }
      } while (dirty && !stopped)
      fetching = false
    }
    refreshRef.current = () => { if (subscribed || fallback) void refresh() }

    function connect() {
      if (stopped) return
      subscribed = false
      fallback = false
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const active = new WebSocket(`${protocol}//${location.host}/api/events`)
      socket = active
      // If the handshake cannot complete, switch explicitly to real HTTP reads.
      handshake = setTimeout(() => { if (!stopped) active.close() }, 3000)
      active.onopen = () => active.send(JSON.stringify({ type: 'subscribe', topic }))
      active.onmessage = event => {
        if (stopped || active !== socket) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        if (message.type === 'subscribed' && message.topic === topic) {
          clearTimeout(handshake)
          subscribed = true
          setConnection('实时状态已连接')
          // Subscribe acknowledgement always precedes this recovery snapshot.
          void refresh()
        } else if (message.type === 'error') {
          // A real subscription rejection (for example a missing run) must not
          // leave the page waiting for an acknowledgement that cannot arrive.
          clearTimeout(handshake)
          fallback = true
          setConnection('实时订阅不可用 · 使用 HTTP 定期同步')
          void refresh()
        } else if (subscribed && message.type === 'resource_changed' && message.resource_type === 'run' &&
          message.resource_id === runId && typeof message.version === 'number' &&
          message.version > (current.current?.version ?? -1)) {
          void refresh()
        }
      }
      active.onerror = () => active.close()
      active.onclose = () => {
        clearTimeout(handshake)
        if (stopped) return
        subscribed = false
        fallback = true
        setConnection('实时通知断开 · 使用 HTTP 定期同步')
        void refresh()
        if (!current.current || !isTerminal(current.current.status)) reconnect = setTimeout(connect, 3000)
      }
    }

    // React StrictMode replays effect setup/cleanup. Defer opening until its
    // replay has settled so the discarded effect never opens a phantom socket.
    queueMicrotask(connect)
    // Polling also covers a dropped invalidation while the socket looks connected.
    const poll = setInterval(() => {
      if ((subscribed || fallback) && (!current.current || !isTerminal(current.current.status))) void refresh()
    }, 5000)
    const onVisible = () => { if (document.visibilityState === 'visible' && (subscribed || fallback)) void refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      controller.abort()
      clearInterval(poll)
      clearTimeout(reconnect)
      clearTimeout(handshake)
      document.removeEventListener('visibilitychange', onVisible)
      socket?.close()
      refreshRef.current = () => {}
    }
  }, [runId, accept])

  return { run, error, connection, accept, reload: () => refreshRef.current() }
}
