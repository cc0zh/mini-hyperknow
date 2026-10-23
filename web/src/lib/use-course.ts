import { useCallback, useEffect, useRef, useState } from 'react'
import { describeError, request } from './api'
import { newerCourse } from './course-state'
import type { Course } from './types'

// Own a single subscription for this course ID, independent of run status/version.
export function useCourse(courseId: string) {
  const [course, setCourse] = useState<Course | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState('正在连接课程通知…')
  const [refreshing, setRefreshing] = useState(false)
  const current = useRef<Course | null>(null)
  const refreshRef = useRef<() => Promise<Course | null>>(() => Promise.resolve(null))
  const reload = useCallback(() => refreshRef.current(), [])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnect: ReturnType<typeof setTimeout> | undefined
    let handshake: ReturnType<typeof setTimeout> | undefined
    let subscribed = false
    let fallback = false
    let dirty = false
    let inflight: Promise<Course | null> | null = null
    const controller = new AbortController()
    const topic = `course:${courseId}`
    current.current = null
    setCourse(null)
    setError(null)
    setConnection('正在连接课程通知…')

    function refresh(invalidate = false): Promise<Course | null> {
      if (stopped) return Promise.resolve(null)
      if (inflight) { if (invalidate) dirty = true; return inflight }
      setRefreshing(true)
      inflight = (async () => {
        let result: Course | null = null
        do {
          dirty = false
          try {
            const value = await request<Course>(`/courses/${encodeURIComponent(courseId)}`, { signal: controller.signal })
            if (stopped) return null
            if (value.course_id !== courseId) throw new Error('未收到属于当前课程的数据。')
            current.current = newerCourse(current.current, value)
            result = current.current
            setCourse(result)
            setError(null)
          } catch (cause) {
            result = null
            if (!stopped) setError(describeError(cause))
          }
        } while (dirty && !stopped)
        return result
      })().finally(() => {
        inflight = null
        if (!stopped) setRefreshing(false)
      })
      return inflight
    }
    refreshRef.current = () => subscribed || fallback ? refresh(true) : Promise.resolve(null)

    function connect() {
      if (stopped) return
      subscribed = false
      fallback = false
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const active = new WebSocket(`${protocol}//${location.host}/api/events`)
      socket = active
      handshake = setTimeout(() => { if (!stopped) active.close() }, 3000)
      active.onopen = () => active.send(JSON.stringify({ type: 'subscribe', topic }))
      active.onmessage = event => {
        if (stopped || active !== socket) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        if (message.type === 'subscribed' && message.topic === topic) {
          clearTimeout(handshake)
          subscribed = true
          setConnection('课程实时通知已连接')
          void refresh(true)
        } else if (message.type === 'error') {
          clearTimeout(handshake)
          fallback = true
          setConnection('课程订阅不可用 · 使用 HTTP 定期同步')
          void refresh(true)
        } else if (subscribed && message.type === 'resource_changed' && message.resource_type === 'course' &&
          message.resource_id === courseId && typeof message.version === 'number' && message.version > (current.current?.version ?? -1)) {
          void refresh(true)
        }
      }
      active.onerror = () => active.close()
      active.onclose = () => {
        clearTimeout(handshake)
        if (stopped) return
        subscribed = false
        fallback = true
        setConnection('课程通知断开 · 使用 HTTP 定期同步')
        void refresh()
        reconnect = setTimeout(connect, 3000)
      }
    }

    queueMicrotask(connect)
    const poll = setInterval(() => { if (subscribed || fallback) void refresh() }, 5000)
    const onVisible = () => { if (document.visibilityState === 'visible' && (subscribed || fallback)) void refresh(true) }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      controller.abort()
      clearInterval(poll)
      clearTimeout(reconnect)
      clearTimeout(handshake)
      document.removeEventListener('visibilitychange', onVisible)
      socket?.close()
      refreshRef.current = () => Promise.resolve(null)
    }
  }, [courseId])

  return { course, error, connection, refreshing, reload }
}
