import { IconArrowRight, IconCheck, IconChevronLeft, IconSpark } from '../components/icons'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Board, SafeText } from '../components/Board'
import { EmptyState, ErrorNotice, Loading } from '../components/ui'
import { activeInteraction, activeRun } from '../lib/lesson-state'
import { runLabels } from '../lib/run-state'
import { useBoardFont } from '../lib/use-board-font'
import { useLesson } from '../lib/use-lesson'
import { useLessonPlayer } from '../lib/use-lesson-player'
import type { Interaction } from '../lib/types'

const interactionLabels: Record<Interaction['status'], string> = { pending: '正在回答', ready: '回答已保存', failed: '回答失败', cancelled: '回答已取消', interrupted: '回答已中断' }

function SessionClassroom({ courseId, sessionId }: { courseId: string; sessionId: string }) {
  const lesson = useLesson(sessionId, courseId)
  const player = useLessonPlayer(sessionId, lesson)
  const font = useBoardFont()
  const [question, setQuestion] = useState('')
  const snapshot = lesson.snapshot
  const back = `/courses/${encodeURIComponent(courseId)}`
  if (!snapshot) return <div className="page"><Link className="back-link" to={back}><IconChevronLeft size={15} />返回课程</Link>{lesson.error ? <ErrorNotice title="课堂读取失败" message={lesson.error} retry={() => { void lesson.reload() }} /> : <Loading label="正在读取已保存讲义与课堂位置…" />}</div>
  const script = snapshot.script
  const generation = snapshot.generation_run
  const current = script?.steps[snapshot.progress.cursor]
  const finished = !!script && snapshot.progress.cursor === script.steps.length - 1
  const locked = player.busy || !!player.pending || !player.online
  const pendingQuestion = player.hold && activeInteraction(player.hold)
  const lessonActionsDisabled = locked || !!player.hold || !script

  return <div className="page classroom-page">
    <div className="classroom-top"><Link className="back-link" to={back}><IconChevronLeft size={15} />返回课程</Link><span className="connection-label">{lesson.connection}</span><span className="completion-label">{snapshot.completed ? <><IconCheck size={14} />课时已完成</> : '课时未标记完成'}</span></div>
    <header className="classroom-heading"><div><span className="eyebrow">{snapshot.unit_title} / {snapshot.lecture_title}</span><h1>{snapshot.session.title}</h1><p>{snapshot.course_title}</p></div><span className="classroom-ticket">PERSONAL<br />CLASSROOM <b><IconSpark size={14} /></b></span></header>
    {lesson.error && <ErrorNotice title="同步失败 · 自动播放已暂停" message={lesson.error} retry={() => { void lesson.reload() }} />}
    {!player.online && <div className="pending-command" role="alert"><div><b>网络已断开，课堂已暂停</b><p>保留最后确认位置与原命令。联网后不会自动播放，也不会自动重新生成。</p></div></div>}
    {player.pending && <div className="pending-command" role="status"><div><b>{player.busy ? '正在串行保存，请稍候…' : '上次写入结果待确认'}</b><p>保留原请求内容和命令编号；重试不会生成另一份命令。</p></div><button type="button" className="button secondary small" disabled={player.busy || !player.online} onClick={() => { void player.retry() }}>重试同一命令</button></div>}
    {player.error && <div className="error-notice" role="alert"><div><b>操作尚未完成 · 已暂停</b><p>{player.error}</p></div>{player.rejected && <button type="button" className="button secondary small" onClick={player.releaseRejected}>修改被拒绝的输入</button>}</div>}

    {!script ? <section className="lesson-preparation">
      {activeRun(generation) ? <><Loading label={`讲义${generation ? runLabels[generation.status] : '准备中'}…`} /><p>只显示服务端真实状态；刷新不会重新收费生成。</p>{generation && <button type="button" className="button secondary" disabled={locked} onClick={() => { void player.runAction(generation.run_id, 'cancel') }}>取消讲义生成</button>}</>
        : generation ? <EmptyState title={`讲义${runLabels[generation.status]}`} action={<button type="button" className="button primary" disabled={locked} onClick={() => { void player.runAction(generation.run_id, 'retry') }}>明确重试讲义生成</button>}>{generation.error?.message || '讲义尚未保存成功。重新生成可能产生模型费用。'}</EmptyState>
          : <EmptyState title="为这一课准备板书" action={<button type="button" className="button primary" disabled={locked} onClick={() => { void player.prepare() }}>准备本课讲义</button>}>按需生成本课讲义并保存。此操作会调用已配置模型，可能产生费用。<br />只有明确点击才会开始；进入、刷新和重连都不会生成。</EmptyState>}
    </section> : <>
      {font.state !== 'ready' && <div className="font-notice" role="status"><div><b>{font.state === 'loading' ? '正在加载 Excalifont 与小赖字体…' : '指定手写字体未能加载'}</b><p>{font.state === 'loading' ? '结构图等待字体完成后再测量，文字暂用可读回退字体。' : '当前回退字体不等于指定字体已满足。请检查 /fonts/Excalifont-Regular.woff2 与 /fonts/Xiaolai-Regular.ttf；图形暂不排版。'}</p></div>{font.state === 'error' && <button type="button" className="button secondary small" onClick={font.retry}>重试字体</button>}</div>}
      <div className="classroom-layout"><div className="classroom-main">
        <Board script={script} cursor={snapshot.progress.cursor} fontReady={font.state === 'ready'} />
        <div className="player-controls" aria-label="课堂播放器"><div><span className={`player-dot ${player.playing ? 'playing' : ''}`} /><b>{player.hold ? pendingQuestion ? '插话回答中' : '回答已保留 · 等待明确继续' : finished ? '板书已全部展示' : player.playing ? '正在播放' : '已暂停'}</b><small>已确认 {snapshot.progress.cursor + 1} / {script.steps.length} 步</small></div><div>{player.playing ? <button type="button" className="button secondary" disabled={locked} onClick={() => { void player.pause() }}>暂停</button> : <button type="button" className="button primary" disabled={lessonActionsDisabled || finished} onClick={() => { void player.play() }}>{snapshot.progress.cursor < 0 ? '开始播放' : '播放'}</button>}<button type="button" className="button secondary" disabled={lessonActionsDisabled || finished} onClick={() => { void player.advance() }}>下一步 <IconArrowRight size={13} /></button></div></div>
        <p className="player-footnote">按文字阅读节奏推进，不是语音时长。每一步保存确认后才展示；刷新始终暂停。</p>
        <section className="narration-panel" aria-labelledby="narration-title"><span className="eyebrow">THE EXPLANATION</span><h2 id="narration-title">{current?.title || '准备开始'}</h2><div className="safe-prose"><SafeText text={current?.narration || '可以逐步播放，或使用下一步手动阅读。左侧页栏回看不会改变教学位置。'} /></div></section>
        <section className="lesson-finish"><div><h2>{snapshot.completed ? '本课已记入课时进度' : '由你决定何时完成这一课'}</h2><p>板书展示完不自动代表掌握。可以练习巩固；提交练习后由服务端完成本课。项目成果提交尚未开放。</p></div><Link className="button primary" to={`${back}/sessions/${encodeURIComponent(sessionId)}/practice`}>课后练习 <IconArrowRight size={13} /></Link>{snapshot.completed ? <Link className="button secondary" to={back}>返回课程目录</Link> : <button type="button" className="button secondary" disabled={locked || !!player.hold} onClick={() => { void player.complete() }}>标记本课完成</button>}</section>
      </div><aside className="classroom-aside">
        <section className="lesson-question-card"><span className="eyebrow">ASK IN THIS CLASS</span><h2>停一下，我想问</h2><p>先暂停并保存，问题锚定当前已确认的第 {snapshot.progress.cursor + 1} 步，不因回看切页而改变。</p><form onSubmit={event => { event.preventDefault(); void player.ask(question).then(ok => { if (ok) setQuestion('') }) }}><label htmlFor="lesson-question">你的问题</label><textarea id="lesson-question" value={question} onChange={event => setQuestion(event.target.value)} minLength={2} maxLength={2000} disabled={locked || !!player.hold} placeholder="结合当前讲解，写下你的疑惑…" /><small>{question.trim().length} / 2000 字 · 回答会调用模型</small><button type="submit" className="button primary" disabled={lessonActionsDisabled || question.trim().length < 2}>暂停并提问</button></form>
          {player.hold && <div className="answer-hold"><b>{interactionLabels[player.hold.status]}</b><p>{pendingQuestion ? '回答完成后仍保持暂停；需要你明确继续。' : player.hold.was_playing ? '回答不会自动覆盖。继续后恢复提问前的播放意图。' : '提问前为暂停；继续后仍保持暂停。'}</p>{!pendingQuestion && <button type="button" className="button secondary" disabled={locked} onClick={() => { void player.continueLesson() }}>继续课堂</button>}</div>}
        </section>
        <section className="interaction-history" aria-labelledby="history-title"><div className="section-heading"><h2 id="history-title">课堂问答</h2><span>{snapshot.interactions.length} 条</span></div>{snapshot.interactions.length ? snapshot.interactions.map(item => <article key={item.interaction_id} className="interaction-card"><div className="interaction-meta"><span>第 {item.cursor + 1} 步</span><span>{interactionLabels[item.status]}</span></div><h3><SafeText text={item.question} /></h3>{item.answer !== null && <div className="safe-prose answer-text"><SafeText text={item.answer} /></div>}{item.error && <p className="interaction-error" role="alert">{item.error.message}</p>}{item.status === 'pending' ? <button type="button" className="text-button" disabled={locked} onClick={() => { void player.runAction(item.run_id, 'cancel') }}>取消本次回答</button> : item.status !== 'ready' && <button type="button" className="text-button" disabled={locked || pendingQuestion === true} onClick={() => { void player.runAction(item.run_id, 'retry') }}>明确重试这个问题</button>}</article>) : <p className="aside-note">还没有课堂问答。保存后的问题与回答会保留在这里。</p>}</section>
      </aside></div>
    </>}
  </div>
}

export default function Classroom() {
  const { courseId = '', sessionId = '' } = useParams()
  return <SessionClassroom key={`${courseId}:${sessionId}`} courseId={courseId} sessionId={sessionId} />
}
