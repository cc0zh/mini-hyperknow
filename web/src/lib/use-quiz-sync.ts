import { useCallback, useEffect, useRef, useState } from 'react'
import { describeError, request } from './api'

// Reads are the only automatic activity. Confirm subscriptions before reading;
// disconnected/unsupported WS falls back to HTTP without issuing any command.
export function useQuizSync<T>(path: string | null, topics: string, validate: (value: T) => boolean, merge: (current: T | null, incoming: T) => T) {
  const [snapshot, setSnapshot] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState('正在连接测验通知…')
  const current = useRef<T | null>(null)
  const revision = useRef(0)
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const accept = useCallback((value: T) => {
    if (!validate(value)) return false
    revision.current += 1
    current.current = merge(current.current, value)
    setSnapshot(current.current)
    return true
  }, [validate, merge])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let handshake: ReturnType<typeof setTimeout> | undefined
    let readable = false
    let fetching = false
    let dirty = false
    const waiting: (() => void)[] = []
    const subscribed = new Set<string>()
    const requested = topics.split('|').filter(Boolean)
    const controller = new AbortController()
    current.current = null
    setSnapshot(null)
    setError(null)
    if (!path) { refreshRef.current = async () => {}; return }
    const readPath = path

    async function refresh() {
      if (stopped || !readable || !path) return
      const confirmedRead = new Promise<void>(resolve => waiting.push(resolve))
      if (fetching) { dirty = true; return confirmedRead }
      fetching = true
      void readLoop()
      return confirmedRead
    }

    async function readLoop() {
      do {
        dirty = false
        const started = revision.current
        try {
          const value = await request<T>(readPath, { signal: controller.signal })
          if (stopped) break
          if (started !== revision.current) { dirty = true; continue }
          if (!accept(value)) throw new Error('测验不属于当前课程或活动，未展示其他课程的数据。')
          setError(null)
        } catch (cause) { if (!stopped) setError(describeError(cause)) }
        // A useful read settles its callers, even if another poll already
        // requested a follow-up. A slow connection must not keep a successful
        // mutation busy forever by making the global queue permanently dirty.
        waiting.splice(0).forEach(resolve => resolve())
      } while (dirty && !stopped)
      fetching = false
      waiting.splice(0).forEach(resolve => resolve())
    }
    refreshRef.current = refresh

    function connect() {
      if (stopped) return
      readable = false
      subscribed.clear()
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const active = new WebSocket(`${protocol}//${location.host}/api/events`)
      socket = active
      handshake = setTimeout(() => active.close(), 3000)
      active.onopen = () => requested.forEach(topic => active.send(JSON.stringify({ type: 'subscribe', topic })))
      active.onmessage = event => {
        if (stopped || active !== socket) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        if (message.type === 'subscribed' && requested.includes(String(message.topic))) {
          subscribed.add(String(message.topic))
          if (subscribed.size === requested.length) {
            clearTimeout(handshake)
            readable = true
            setConnection('测验实时通知已连接')
            void refresh()
          }
        } else if (message.type === 'error') {
          clearTimeout(handshake)
          readable = true
          setConnection('订阅不可用 · 使用真实 HTTP 同步')
          void refresh()
        } else if (readable && message.type === 'resource_changed') {
          const topic = `${String(message.resource_type)}:${String(message.resource_id)}`
          if (requested.includes(topic)) void refresh()
        }
      }
      active.onerror = () => active.close()
      active.onclose = () => {
        clearTimeout(handshake)
        if (stopped || active !== socket) return
        readable = true
        setConnection('通知断开 · 使用真实 HTTP 同步')
        void refresh()
        reconnect = setTimeout(connect, 3000)
      }
    }
    queueMicrotask(connect)
    const poll = setInterval(() => { void refresh() }, 5000)
    const onVisible = () => { if (document.visibilityState === 'visible') void refresh() }
    window.addEventListener('online', refresh)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      controller.abort()
      clearTimeout(handshake)
      clearTimeout(reconnect)
      clearInterval(poll)
      waiting.splice(0).forEach(resolve => resolve())
      window.removeEventListener('online', refresh)
      document.removeEventListener('visibilitychange', onVisible)
      socket?.close()
      refreshRef.current = async () => {}
    }
  }, [path, topics, accept])

  const reload = useCallback(() => refreshRef.current(), [])
  return { snapshot, current, error, connection, accept, reload }
}
