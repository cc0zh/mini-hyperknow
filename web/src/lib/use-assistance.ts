import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, describeError, request } from './api'
import {
  commandScope, getConversation, makeAssistanceCommand, makeTurnCommand, mergeArtifact, mergeConversation,
  ownsAssistanceCommand, prepareAssistanceCommand, readAssistanceCommand, saveAssistanceCommand, matchesAssistanceResource,
} from './assistance'
import type { AssistanceArtifact, AssistanceConversation, AssistanceRun, PendingAssistanceCommand } from './assistance'

type Resource = AssistanceConversation | AssistanceArtifact
function mergeResource<T extends Resource>(current: T | null, incoming: T): T {
  return ('turns' in incoming ? mergeConversation(current as AssistanceConversation | null, incoming)
    : mergeArtifact(current as AssistanceArtifact | null, incoming as AssistanceArtifact)) as T
}

// Events invalidate saved resources. HTTP is the authority and is also polled
// to recover dropped events, reconnects and unsupported subscriptions.
export function useAssistanceResource<T extends Resource>(path: string, topics: string[]) {
  const [snapshot, setSnapshot] = useState<T | null>(null)
  const current = useRef<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState('正在读取已保存快照…')
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const accept = useCallback((value: T) => {
    if (!matchesAssistanceResource(path, value)) return
    current.current = mergeResource(current.current, value); setSnapshot(current.current)
  }, [path])
  const artifactTopics = snapshot && 'turns' in snapshot ? snapshot.turns.flatMap(turn => turn.artifacts).map(artifact => `artifact:${artifact.artifact_id}`) : []
  const topicKey = [...new Set([...topics, ...artifactTopics])].join('|')

  useEffect(() => {
    let stopped = false
    let fetching: Promise<void> | null = null
    let dirty = false
    const controller = new AbortController()
    async function refresh() {
      if (stopped) return
      if (fetching) { dirty = true; return fetching }
      fetching = (async () => {
        do {
          dirty = false
          try {
            const value = await request<T>(path, { signal: controller.signal })
            if (!stopped) { accept(value); setError(null) }
          } catch (cause) { if (!stopped) setError(describeError(cause)) }
        } while (dirty && !stopped)
      })()
      await fetching
      fetching = null
    }
    refreshRef.current = refresh
    void refresh()
    const poll = window.setInterval(() => { void refresh() }, 5000)
    const visible = () => { if (document.visibilityState === 'visible') void refresh() }
    window.addEventListener('online', refresh)
    document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; controller.abort(); window.clearInterval(poll); window.removeEventListener('online', refresh); document.removeEventListener('visibilitychange', visible) }
  }, [path, accept])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let handshake: ReturnType<typeof setTimeout> | undefined
    const subscribed = new Set<string>()
    const subscribedTopics = topicKey.split('|').filter(Boolean)
    function connect() {
      if (stopped || !subscribedTopics.length) return
      subscribed.clear()
      const active = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/events`)
      socket = active
      handshake = setTimeout(() => active.close(), 3000)
      active.onopen = () => subscribedTopics.forEach(topic => active.send(JSON.stringify({ type: 'subscribe', topic })))
      active.onmessage = event => {
        if (stopped || active !== socket) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        if (message.type === 'subscribed' && subscribedTopics.includes(String(message.topic))) {
          subscribed.add(String(message.topic))
          if (subscribed.size === subscribedTopics.length) { clearTimeout(handshake); setConnection('实时通知已连接 · 快照同步'); void refreshRef.current() }
        } else if (message.type === 'resource_changed' && subscribedTopics.includes(`${message.resource_type}:${message.resource_id}`)) void refreshRef.current()
        else if (message.type === 'error') { setConnection('订阅不可用 · HTTP 定期同步'); void refreshRef.current(); active.close() }
      }
      active.onerror = () => active.close()
      active.onclose = () => {
        clearTimeout(handshake)
        if (stopped) return
        setConnection('通知已断开 · HTTP 定期同步')
        void refreshRef.current()
        retry = setTimeout(connect, 5000)
      }
    }
    queueMicrotask(connect)
    return () => { stopped = true; clearTimeout(retry); clearTimeout(handshake); socket?.close() }
  }, [topicKey])
  return { snapshot, current, accept, error, connection, reload: useCallback(() => refreshRef.current(), []) }
}

export function useAssistanceCommand(conversationId: string, acceptConversation: (value: AssistanceConversation) => void, acceptArtifact?: (value: AssistanceArtifact) => void) {
  const scope = conversationId ? commandScope(conversationId) : 'create'
  const [pending, setPending] = useState(() => readAssistanceCommand(scope))
  const pendingRef = useRef(pending)
  const reserved = useRef(false)
  const visit = useRef<object | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejected, setRejected] = useState(false)
  const handlers = useRef({ acceptConversation, acceptArtifact })
  handlers.current = { acceptConversation, acceptArtifact }
  useEffect(() => { const owner = {}; visit.current = owner; return () => { if (visit.current === owner) visit.current = null } }, [])

  function persist(command: PendingAssistanceCommand | null) {
    pendingRef.current = command; saveAssistanceCommand(scope, command); setPending(command)
  }
  async function execute(proposed?: PendingAssistanceCommand | (() => Promise<PendingAssistanceCommand>)): Promise<boolean> {
    if (reserved.current || !visit.current) return false
    reserved.current = true
    const owner = visit.current
    const alive = () => visit.current === owner
    let committed = false
    setBusy(true); setError(null); setRejected(false)
    try {
      let command = prepareAssistanceCommand(pendingRef.current, typeof proposed === 'function' ? null : proposed ?? null)
      if (!command && typeof proposed === 'function') command = await proposed()
      if (!command || !alive()) return false
      persist(command)
      while (command) {
        committed = false
        const result = await request<AssistanceConversation | AssistanceArtifact | AssistanceRun>(command.path, { method: command.method, body: JSON.stringify(command.body) })
        committed = true
        // Old pages keep the receipt for an exact retry. Their response cannot
        // clear a later page's pending command, busy flag or saved snapshot.
        if (!alive()) return false
        if ('turns' in result) handlers.current.acceptConversation(result)
        else if ('artifact_id' in result) handlers.current.acceptArtifact?.(result)
        if (command.question_after_save) {
          const conversation = await getConversation(command.conversationId)
          if (!alive()) return false
          handlers.current.acceptConversation(conversation)
          const question = command.question_after_save
          command = makeTurnCommand(conversation, question.text, 'message', question.artifact_id)
          persist(command)
        } else {
          if (command.conversationId) {
            const conversation = await getConversation(command.conversationId)
            if (!alive()) return false
            handlers.current.acceptConversation(conversation)
          }
          if (ownsAssistanceCommand(pendingRef.current, command)) persist(null)
          command = null
        }
      }
      return true
    } catch (cause) {
      if (alive()) {
        setError(describeError(cause))
        setRejected(!committed && cause instanceof ApiError && [400, 404, 409, 422].includes(cause.status))
        if (cause instanceof ApiError && cause.status === 409 && conversationId) {
          try { const value = await getConversation(conversationId); if (alive()) handlers.current.acceptConversation(value) } catch { /* original conflict stays visible */ }
        }
      }
      return false
    } finally { if (alive()) { reserved.current = false; setBusy(false) } }
  }
  function releaseRejected() { if (rejected && !reserved.current) { persist(null); setRejected(false); setError(null) } }
  const runAction = (id: string, action: 'cancel' | 'retry') => execute(async () => {
    const run = await request<AssistanceRun>(`/runs/${encodeURIComponent(id)}`)
    return makeAssistanceCommand(conversationId, `/runs/${encodeURIComponent(id)}/${action}`, { expected_version: run.version })
  })
  return { busy, pending, error, rejected, execute, runAction, releaseRejected }
}
