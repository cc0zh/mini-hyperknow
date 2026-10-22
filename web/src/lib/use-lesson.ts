import { useCallback, useEffect, useRef, useState } from 'react'
import { describeError, request } from './api'
import { mergeLesson } from './lesson-state'
import type { LessonSnapshot } from './types'

export function useLesson(sessionId: string, courseId: string) {
  const [snapshot, setSnapshot] = useState<LessonSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState('正在连接课堂通知…')
  const current = useRef<LessonSnapshot | null>(null)
  const revision = useRef(0)
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const accept = useCallback((incoming: LessonSnapshot) => {
    if (incoming.session.session_id !== sessionId || incoming.course_id !== courseId) return
    revision.current += 1
    current.current = mergeLesson(current.current, incoming)
    setSnapshot(current.current)
  }, [sessionId, courseId])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let handshake: ReturnType<typeof setTimeout> | undefined
    let fetching = false
    let dirty = false
    const waiting: (() => void)[] = []
    let readable = false
    const subscriptions = new Set<string>()
    const topics = [`session:${sessionId}`, `course:${courseId}`]
    const controller = new AbortController()
    current.current = null
    setSnapshot(null)
    setError(null)

    async function refresh() {
      if (stopped || !readable) return
      if (fetching) { dirty = true; return new Promise<void>(resolve => waiting.push(resolve)) }
      fetching = true
      do {
        dirty = false
        const started = revision.current
        try {
          const value = await request<LessonSnapshot>(`/sessions/${encodeURIComponent(sessionId)}`, { signal: controller.signal })
          if (stopped) break
          // A mutation accepted while GET was in flight wins. Read again rather
          // than letting a stale retry run or answer overwrite that mutation.
          if (started !== revision.current) { dirty = true; continue }
          accept(value)
          setError(null)
        } catch (cause) {
          if (!stopped) setError(describeError(cause))
        }
      } while (dirty && !stopped)
      fetching = false
      waiting.splice(0).forEach(resolve => resolve())
    }
    refreshRef.current = refresh

    function connect() {
      if (stopped) return
      readable = false
      subscriptions.clear()
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const active = new WebSocket(`${protocol}//${location.host}/api/events`)
      socket = active
      handshake = setTimeout(() => active.close(), 3000)
      active.onopen = () => topics.forEach(topic => active.send(JSON.stringify({ type: 'subscribe', topic })))
      active.onmessage = event => {
        if (stopped || active !== socket) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        if (message.type === 'subscribed' && topics.includes(String(message.topic))) {
          subscriptions.add(String(message.topic))
          if (subscriptions.size === topics.length) {
            clearTimeout(handshake)
            readable = true
            setConnection('课堂实时通知已连接')
            void refresh()
          }
        } else if (message.type === 'error') {
          clearTimeout(handshake)
          readable = true
          setConnection('订阅不可用 · 使用真实 HTTP 同步')
          void refresh()
        } else if (readable && message.type === 'resource_changed' &&
          ((message.resource_type === 'session' && message.resource_id === sessionId) ||
           (message.resource_type === 'course' && message.resource_id === courseId))) void refresh()
      }
      active.onerror = () => active.close()
      active.onclose = () => {
        clearTimeout(handshake)
        if (stopped) return
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
      clearTimeout(reconnect)
      clearTimeout(handshake)
      clearInterval(poll)
      window.removeEventListener('online', refresh)
      document.removeEventListener('visibilitychange', onVisible)
      socket?.close()
      refreshRef.current = async () => {}
    }
  }, [sessionId, courseId, accept])

  return { snapshot, current, error, connection, accept, reload: () => refreshRef.current() }
}
