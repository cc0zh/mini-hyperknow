import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { BackLink, ErrorNotice, Loading } from '../components/ui'
import { IconArrowRight } from '../components/icons'
import { AssistanceTurns, AssistanceTimeline } from '../components/AssistanceTurns'
import { artifactPath, assistanceStatusLabels, boardArtifactPath, conversationPath, conversationRoute, makeAssistanceCommand, makeTurnCommand, mergeArtifact, validTurn } from '../lib/assistance'
import type { AssistanceAction, AssistanceConversation, AssistanceSummary } from '../lib/assistance'
import { useAssistanceCommand, useAssistanceResource } from '../lib/use-assistance'
import { useResource } from '../lib/use-resource'

function AssistanceHome() {
  const history = useResource<{ conversations: AssistanceSummary[] }>('/assistance/conversations')
  const navigate = useNavigate()
  const [seed, setSeed] = useState<{ draft?: string }>({})
  const command = useAssistanceCommand('', value => navigate(conversationRoute(value.conversation_id), { state: seed.draft ? { draft: seed.draft } : undefined }))
  const start = (next: { draft?: string } = {}) => { setSeed(next); void command.execute(makeAssistanceCommand('', '/assistance/conversations', {})) }
  return <div className="page assistance-home">
    <header className="page-heading"><div><span className="eyebrow">INSTANT ASSISTANCE</span><h1>即时协助</h1><p>围绕一个问题展开讲解，按需生成学习产物。</p></div><button className="button primary" type="button" disabled={command.busy} onClick={() => start()}>{command.busy ? '正在创建…' : command.pending ? '重试同一创建请求' : '开始新会话'}<IconArrowRight size={15} /></button></header>
    {history.error && <ErrorNotice message={history.error} title="会话列表读取失败" retry={history.reload} />}
    {command.error && <ErrorNotice message={command.error} title="创建请求未确认" />}
    {command.rejected && <button className="text-button" type="button" onClick={command.releaseRejected}>确认已拒绝，修改后重试</button>}
    {command.pending && <p className="inline-note" role="status">保留了上次创建的完整请求与命令编号；只在明确重试后发送。</p>}
    {!history.loading && (!history.data || history.data.conversations.length === 0) && !history.error &&
      <section className="assistance-starters" aria-label="快速开始">
        <div className="starters-group"><span className="eyebrow">从一个问题开始</span><div className="starter-list">{ASSISTANCE_EXAMPLES.map(example => <button key={example} type="button" className="starter-chip" disabled={command.busy} onClick={() => start({ draft: example })}>{example}<IconArrowRight size={14} /></button>)}</div></div>
        <div className="starters-group"><span className="eyebrow">或直接要一种学习产物</span><div className="starter-list">{ARTIFACT_STARTERS.map(item => <button key={item.label} type="button" className="starter-chip artifact" disabled={command.busy} onClick={() => start({ draft: item.draft })}>{item.label}</button>)}</div></div>
      </section>}
    {history.loading ? <Loading label="正在读取会话历史…" /> : history.data && history.data.conversations.length > 0 ? <section className="assistance-history" aria-label="会话历史">{history.data.conversations.map(item => <Link key={item.conversation_id} to={conversationRoute(item.conversation_id)}><span><b>{item.title}</b><small>{new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(item.updated_at))}</small></span><IconArrowRight size={16} /></Link>)}</section> : null}
  </div>
}

const ASSISTANCE_EXAMPLES = [
  '用通俗的方式讲解什么是导数',
  '帮我理解快速排序的分治思路',
  '牛顿第二定律在生活中有哪些例子？',
]
const ARTIFACT_STARTERS: { label: string; draft: string }[] = [
  { label: '要一组概念闪卡', draft: '围绕微积分基础概念做一组闪卡' },
  { label: '要一份自测题', draft: '出一份数据结构基础自测题' },
  { label: '要看一块讲解白板', draft: '用白板分步讲解二分查找' },
]

function ConversationPage({ conversationId }: { conversationId: string }) {
  const location = useLocation()
  const navigationState = location.state as { draft?: string; artifact_id?: string } | null
  const [text, setText] = useState(navigationState?.draft ?? '')
  const [artifactId, setArtifactId] = useState(navigationState?.artifact_id)
  const resource = useAssistanceResource<AssistanceConversation>(conversationPath(conversationId), [`conversation:${conversationId}`])
  // An artifact verdict returns the artifact, not the conversation; accept it
  // by keeping the newer artifact version inside the turn that owns it.
  const command = useAssistanceCommand(conversationId, resource.accept, artifact => {
    const snapshot = resource.current.current
    if (!snapshot) return
    resource.accept({ ...snapshot, turns: snapshot.turns.map(turn => ({ ...turn, artifacts: turn.artifacts.map(item => item.artifact_id === artifact.artifact_id ? mergeArtifact(item, artifact) : item) })) })
  })
  const conversation = resource.snapshot
  const inFlight = !!conversation?.active_run
  const blocked = command.busy || !!command.pending || inFlight
  const savedText = command.pending?.body.action ? String(command.pending.body.text ?? '') : null
  // The learner writes what they want; the model decides how to teach and
  // whether an artifact is the right move. `continue` is the only second
  // intent and it stays bound to a saved plan waiting for that advance.
  async function send(overrideText = text, overrideAction: AssistanceAction = 'message'): Promise<boolean> {
    const current = resource.current.current
    if (!current || blocked || !validTurn(overrideText)) return false
    if (overrideAction === 'continue' && current.turns.at(-1)?.response?.waiting_for !== 'continue') return false
    const ok = await command.execute(makeTurnCommand(current, overrideText.trim(), overrideAction, artifactId))
    if (ok) { setText(''); setArtifactId(undefined) }
    return ok
  }
  const keyboard = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() }
  }
  // A verdict is its own command on the artifact version, so it never depends
  // on the conversation version and never turns into a model call.
  function vote(artifactId: string, value: 'up' | 'down') {
    const artifact = conversation?.turns.flatMap(turn => turn.artifacts).find(item => item.artifact_id === artifactId)
    if (!artifact) return
    void command.execute(makeAssistanceCommand(conversationId, `${artifactPath(artifactId)}/feedback`, { expected_version: artifact.version, vote: value }, 'PUT'))
  }
  if (!conversation) return <div className="page"><BackLink to="/assistance">会话历史</BackLink>{resource.error ? <ErrorNotice title="会话读取失败" message={resource.error} retry={() => { void resource.reload() }} /> : <Loading label="正在读取已保存会话…" />}</div>
  const waiting = conversation.turns.at(-1)?.response?.waiting_for
  return <div className="page assistance-chat-page">
    <div className="assistance-chat-top"><BackLink to="/assistance">会话历史</BackLink><span className="connection-label">{resource.connection}</span></div>
    <header className="assistance-chat-heading"><span className="eyebrow">INSTANT ASSISTANCE</span><h1>{conversation.title}</h1></header>
    {resource.error && <ErrorNotice title="快照同步失败" message={resource.error} retry={() => { void resource.reload() }} />}
    {command.error && <ErrorNotice title="操作尚未确认" message={command.error} />}
    {command.pending && <div className="pending-command" role="status"><div><b>{command.busy ? '正在提交同一命令…' : '请求结果待确认'}</b><p>保留原路径、正文、版本与命令编号，不会自动发起新一轮。</p></div><button className="button secondary small" type="button" disabled={command.busy} onClick={() => { void command.execute() }}>重试同一命令</button></div>}
    {command.rejected && <button className="text-button" type="button" onClick={() => { if (savedText !== null) setText(savedText); command.releaseRejected(); void resource.reload() }}>确认已拒绝，重新同步后修改</button>}
    {!conversation.turns.length && <p className="assistance-start-note">写下问题，或选择生成一种学习产物。进入与刷新仅展示已保存内容。</p>}
    <AssistanceTurns conversation={conversation} blocked={blocked} onAnswer={answer => send(answer)} onRetry={runId => { void command.runAction(runId, 'retry') }} onSuggest={suggestion => { void send(suggestion.text, suggestion.action) }} onVote={vote} />
    {inFlight && <div className="assistance-inflight" role="status"><div className="pending-command"><div><b>本轮{assistanceStatusLabels[conversation.active_run!.status]}</b><p>通过真实服务端快照同步，完成后展示保存的回复。</p></div><button className="button secondary small" type="button" disabled={command.busy || !!command.pending} onClick={() => { void command.runAction(conversation.active_run!.run_id, 'cancel') }}>取消当前回答</button></div>{conversation.active_run!.status === 'generating' && <AssistanceTimeline run={conversation.active_run!} />}</div>}
    {waiting === 'continue' && <button className="button primary continue-assistance" type="button" disabled={blocked} onClick={() => { void send('继续下一步', 'continue') }}>继续讲解<IconArrowRight size={15} /></button>}
    {artifactId && <div className="assistance-board-context"><span>问题关联已确认的白板步骤</span><Link to={boardArtifactPath(artifactId)}>回到白板</Link><button className="text-button" type="button" disabled={blocked} onClick={() => setArtifactId(undefined)}>取消关联</button></div>}
    <form className="assistance-composer" onSubmit={event => { event.preventDefault(); void send() }}>
      <label htmlFor="assistance-input">你的问题</label><textarea id="assistance-input" value={savedText ?? text} onChange={event => setText(event.target.value)} onKeyDown={keyboard} rows={3} maxLength={12000} placeholder="写下你的问题…（Enter 发送，Shift+Enter 换行）" disabled={blocked} />
      <div className="composer-options"><button className="button primary" type="submit" disabled={blocked || !validTurn(text)}>{command.busy ? '正在提交…' : '发送'}<IconArrowRight size={15} /></button>
      </div><small>教学方式与是否产出闪卡、测验、白板、动画、结构图由模型按内容判断；想要某一种就直接说。仅明确发送或重试会调用模型。</small>
    </form>
  </div>
}

export default function Assistance() {
  const { conversationId } = useParams()
  return conversationId ? <ConversationPage key={conversationId} conversationId={conversationId} /> : <AssistanceHome />
}
