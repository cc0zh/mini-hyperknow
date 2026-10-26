import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Board } from '../components/Board'
import { AssistanceText, AssistanceTurns } from '../components/AssistanceTurns'
import { BackLink, ErrorNotice, Loading } from '../components/ui'
import { artifactPath, conversationPath, conversationRoute, isAdvanceAllowed, makeAssistanceCommand, makeBoardScript, validBoardCursor, validTurn } from '../lib/assistance'
import type { AssistanceArtifact, AssistanceConversation, WhiteboardArtifact } from '../lib/assistance'
import { PlaybackClock, readingDelay } from '../lib/lesson-state'
import { useAssistanceCommand, useAssistanceResource } from '../lib/use-assistance'
import { useBoardFont } from '../lib/use-board-font'

function BoardPlayer({ resource, initial }: { resource: ReturnType<typeof useAssistanceResource<AssistanceArtifact>>; initial: WhiteboardArtifact }) {
  const conversation = useAssistanceResource<AssistanceConversation>(conversationPath(initial.conversation_id), [`conversation:${initial.conversation_id}`])
  const command = useAssistanceCommand(initial.conversation_id, conversation.accept, resource.accept)
  const artifact = resource.snapshot?.kind === 'whiteboard' ? resource.snapshot : initial
  const font = useBoardFont()
  const clock = useRef(new PlaybackClock()).current
  const [playing, setPlaying] = useState(false)
  const [question, setQuestion] = useState(() => String(command.pending?.question_after_save?.text ?? command.pending?.body.text ?? ''))
  const [online, setOnline] = useState(navigator.onLine)
  const cursor = artifact.data.cursor
  const current = artifact.data.steps[cursor]
  const finished = cursor === artifact.data.steps.length - 1
  const inFlight = !!conversation.snapshot?.active_run
  const locked = command.busy || !!command.pending || inFlight || !conversation.snapshot || !online || !!resource.error || !!conversation.error
  const stop = () => { clock.pause(); setPlaying(false) }

  useEffect(() => {
    const offline = () => { clock.pause(); setPlaying(false); setOnline(false) }
    const online = () => setOnline(true)
    window.addEventListener('offline', offline); window.addEventListener('online', online)
    return () => { clock.pause(); window.removeEventListener('offline', offline); window.removeEventListener('online', online) }
  }, [clock])
  useEffect(() => { if (inFlight || resource.error || conversation.error || command.error || finished) stop() }, [inFlight, resource.error, conversation.error, command.error, finished])

  async function advance() {
    clock.cancel()
    const value = resource.current.current
    if (locked || value?.kind !== 'whiteboard' || !isAdvanceAllowed(value.data.cursor, value.data.steps.length, inFlight)) return
    const next = value.data.cursor + 1
    if (!validBoardCursor(value.data.cursor, next, value.data.steps.length)) return
    const ok = await command.execute(makeAssistanceCommand(value.conversation_id, `${artifactPath(value.artifact_id)}/progress`, { expected_version: value.version, cursor: next }, 'PUT'))
    if (!ok) stop()
  }
  useEffect(() => {
    if (playing && !locked && !finished) clock.schedule(readingDelay(current?.narration ?? ''), () => { void advance() })
    return () => clock.cancel()
    // Polling/diagram rendering cannot restart the single playback clock.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clock, playing, locked, finished, cursor, current?.narration])

  async function ask(text: string): Promise<boolean> {
    stop()
    const value = resource.current.current
    if (locked || value?.kind !== 'whiteboard' || !validTurn(text)) return false
    const save = makeAssistanceCommand(value.conversation_id, `${artifactPath(value.artifact_id)}/progress`, { expected_version: value.version, cursor: value.data.cursor }, 'PUT')
    save.question_after_save = { text: text.trim(), artifact_id: value.artifact_id }
    const ok = await command.execute(save)
    if (ok) setQuestion('')
    return ok
  }
  return <div className="page assistance-board-page">
    <div className="assistance-chat-top"><BackLink to={conversationRoute(artifact.conversation_id)}>返回会话</BackLink><span className="connection-label">{resource.connection}</span></div>
    <header className="page-heading"><div><span className="eyebrow">STANDALONE WHITEBOARD</span><h1>{artifact.title}</h1></div></header>
    {resource.error && <ErrorNotice title="白板同步失败 · 播放已暂停" message={resource.error} retry={() => { void resource.reload() }} />}
    {conversation.error && <ErrorNotice title="会话同步失败 · 播放已暂停" message={conversation.error} retry={() => { void conversation.reload() }} />}
    {font.state !== 'ready' && <div className="font-notice" role="status"><div><b>{font.state === 'loading' ? '正在加载手写字体…' : '手写字体未能加载'}</b><p>结构图等待字体就绪；文字暂用可读回退字体。</p></div>{font.state === 'error' && <button type="button" className="button secondary small" onClick={font.retry}>重试字体</button>}</div>}
    {command.pending && <div className="pending-command" role="status"><div><b>上次命令结果待确认 · 播放已暂停</b><p>保留请求路径、位置、问题与命令编号，不会自动重发。</p></div><button className="button secondary small" type="button" disabled={command.busy || !online} onClick={() => { stop(); void command.execute() }}>重试同一命令</button></div>}
    {command.error && <ErrorNotice title="操作尚未完成" message={command.error} />}
    {command.rejected && <button className="text-button" type="button" onClick={() => { command.releaseRejected(); void resource.reload(); void conversation.reload() }}>确认已拒绝，重新同步后修改</button>}
    {!online && <p role="alert" className="inline-note">网络已断开，已暂停；联网后需明确播放。</p>}
    <Board script={makeBoardScript(artifact)} cursor={cursor} fontReady={font.state === 'ready'} />
    <div className="player-controls assistance-player" aria-label="独立白板播放器"><div><b>{inFlight ? '会话正在回答 · 已暂停' : finished ? '板书已全部展示' : playing ? '正在播放' : '已暂停'}</b><small>已确认 {cursor + 1} / {artifact.data.steps.length} 步</small></div><div>
      {playing ? <button className="button secondary" type="button" onClick={stop}>暂停</button> : <button className="button primary" type="button" disabled={locked || finished} onClick={() => { clock.play(); setPlaying(true) }}>{cursor < 0 ? '开始播放' : '播放'}</button>}
      <button className="button secondary" type="button" disabled={locked || finished} onClick={() => { stop(); void advance() }}>下一步</button>
    </div></div>
    <p className="player-footnote">每一步保存确认后才展示。按文字阅读节奏推进；刷新和回看恢复始终暂停。</p>
    <section className="narration-panel"><span className="eyebrow">THE EXPLANATION</span><h2>{current?.title || '准备开始'}</h2><AssistanceText text={current?.narration || '点击开始播放或下一步，逐步展开讲解。'} /></section>
    <form className="assistance-ask" onSubmit={event => { event.preventDefault(); void ask(question) }}><label htmlFor="board-question">关于已确认第 {cursor + 1} 步提问</label><textarea id="board-question" value={question} disabled={locked} maxLength={12000} onChange={event => { stop(); setQuestion(event.target.value) }} placeholder="先保存当前位置，再把问题发送至当前会话…" /><button className="button primary" type="submit" disabled={locked || !validTurn(question)}>暂停并提问</button></form>
    {inFlight && <button type="button" className="text-button" disabled={command.busy || !!command.pending} onClick={() => { stop(); void command.runAction(conversation.snapshot!.active_run!.run_id, 'cancel') }}>取消当前回答</button>}
    {conversation.snapshot && <section aria-label="白板会话问答"><div className="section-heading"><h2>会话问答</h2><Link to={conversationRoute(artifact.conversation_id)}>查看完整会话</Link></div><AssistanceTurns conversation={conversation.snapshot} blocked={locked} compact onAnswer={ask} onRetry={runId => { stop(); void command.runAction(runId, 'retry') }} /></section>}
  </div>
}

export default function AssistanceBoard() {
  const { artifactId = '' } = useParams()
  return <BoardRoute key={artifactId} artifactId={artifactId} />
}
function BoardRoute({ artifactId }: { artifactId: string }) {
  const resource = useAssistanceResource<AssistanceArtifact>(artifactPath(artifactId), [`artifact:${artifactId}`])
  if (!resource.snapshot) return <div className="page"><BackLink to="/assistance">返回即时协助</BackLink>{resource.error ? <ErrorNotice title="白板读取失败" message={resource.error} retry={() => { void resource.reload() }} /> : <Loading label="正在读取已保存白板…" />}</div>
  if (resource.snapshot.kind !== 'whiteboard') return <div className="page"><ErrorNotice title="产物类型不匹配" message="此链接不指向白板。请返回所属会话查看。" /><Link to={conversationRoute(resource.snapshot.conversation_id)}>返回会话</Link></div>
  return <BoardPlayer resource={resource} initial={resource.snapshot} />
}
