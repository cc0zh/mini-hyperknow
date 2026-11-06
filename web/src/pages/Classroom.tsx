import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { IconArrowRight, IconChevronLeft } from '../components/icons'
import { Board, SafeText } from '../components/Board'
import { EmptyState, ErrorNotice, Loading } from '../components/ui'
import { activeInteraction, activeRun, questionAnchor, summaryIsShown } from '../lib/lesson-state'
import { confirmedCursor } from '../lib/board-scene'
import { isBoardScriptV2 } from '../lib/board-protocol'
import { runLabels } from '../lib/run-state'
import { useBoardFont } from '../lib/use-board-font'
import { useLesson } from '../lib/use-lesson'
import { useLessonPlayer } from '../lib/use-lesson-player'
import type { BoardStep, Interaction } from '../lib/types'

const interactionLabels: Record<Interaction['status'], string> = { pending: '正在回答', ready: '回答已保存', failed: '回答失败', cancelled: '回答已取消', interrupted: '回答已中断' }
const stageLabels: Record<BoardStep['stage'], string> = { opening: '本课路线图', explain: '要点解释', example: '一起看例子', check: '停下来想一想', summary: '回扣与总结' }

function SessionClassroom({ courseId, sessionId }: { courseId: string; sessionId: string }) {
  const lesson = useLesson(sessionId, courseId)
  const player = useLessonPlayer(sessionId, lesson)
  const font = useBoardFont()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [review, setReview] = useState<{ scriptId: string; cursor: number } | null>(null)
  const [selection, setSelection] = useState<string | null>(null)
  const [focusRequest, setFocusRequest] = useState(0)
  const [asideOpen, setAsideOpen] = useState(true)
  const [tab, setTab] = useState<'narration' | 'ask' | 'history'>('narration')
  const [regenerateScriptId, setRegenerateScriptId] = useState<string | null>(null)
  const snapshot = lesson.snapshot
  const sidebarScroll = useRef<HTMLDivElement>(null)
  const viewedCursor = review && review.scriptId === snapshot?.script?.script_id ? review.cursor : snapshot?.progress.cursor
  useEffect(() => {
    if (tab === 'narration' && sidebarScroll.current) sidebarScroll.current.scrollTop = 0
  }, [snapshot?.script?.script_id, viewedCursor, focusRequest, tab])
  const back = "/courses/" + encodeURIComponent(courseId)
  if (!snapshot) return <main className="classroom-loading"><Link className="back-link" to={back}><IconChevronLeft size={15} />返回课程</Link>{lesson.error ? <ErrorNotice title="课堂读取失败" message={lesson.error} retry={() => { void lesson.reload() }} /> : <Loading label="正在读取已保存讲义与课堂位置…" />}</main>
  const script = isBoardScriptV2(snapshot.script) ? snapshot.script : null
  const unsupported = !!snapshot.format_error || snapshot.script !== null && !script
  const generation = snapshot.generation_run
  const teachingCursor = snapshot.progress.cursor
  const viewCursor = confirmedCursor(review && review.scriptId === script?.script_id ? review.cursor : teachingCursor, teachingCursor)
  const current = script?.steps[viewCursor]
  const teaching = script?.steps[teachingCursor]
  const finished = summaryIsShown(script, teachingCursor)
  const locked = player.busy || !!player.pending || !player.online || !!lesson.error
  const pendingQuestion = !!player.hold && activeInteraction(player.hold)
  const lessonActionsDisabled = locked || !!player.hold || !script || activeRun(generation)
  const anchor = script ? questionAnchor(script, teachingCursor, viewCursor, selection) : null

  function view(cursor: number, objectId: string | null = null) {
    if (!script || cursor < 0 || cursor > teachingCursor) return
    player.pauseLocal()
    setReview({ scriptId: script.script_id, cursor })
    setSelection(objectId)
    setFocusRequest(value => value + 1)
  }
  function returnCurrent() {
    setReview(null); setSelection(null); setFocusRequest(value => value + 1)
  }
  function selectObject(id: string) {
    if (!script) return
    const selected = questionAnchor(script, teachingCursor, viewCursor, id)
    if (!selected) return
    const owner = script.steps.findIndex(step => step.step_id === selected.anchor_step_id)
    view(owner, id)
  }
  function submitQuestion(text: string, clear: () => void) {
    if (!anchor) return
    void player.ask(text, anchor).then(ok => { if (ok) { clear(); setTab('history') } })
  }
  function play() { returnCurrent(); void player.play() }
  function next() { returnCurrent(); void player.advance() }

  return <main className={"classroom-screen " + (asideOpen ? '' : 'aside-collapsed')}>
    <header className="classroom-header">
      <Link className="classroom-exit" to={back} onClick={player.pauseLocal}><IconChevronLeft size={17} /><span>课程</span></Link>
      <div className="classroom-identity"><span>{snapshot.unit_title} / {snapshot.lecture_title}</span><h1>{snapshot.session.title}</h1></div>
      <span className="classroom-progress-label">{snapshot.completed ? '课时已完成 · 不代表掌握' : '退出保留进度'}</span>
      <button type="button" className="classroom-toggle" aria-expanded={asideOpen} aria-controls="classroom-sidebar" onClick={() => setAsideOpen(value => !value)}>{asideOpen ? '收起讲解' : '展开讲解'}</button>
    </header>
    {script && <details className="classroom-roadmap"><summary>本课路线图 <span>{script.roadmap.length} 个要点 · 已确认 {Math.max(0, teachingCursor + 1)} / {script.steps.length} 步</span></summary><div className="roadmap-content"><ul className="classroom-objectives">{script.objectives.map((objective, index) => <li key={index}>{objective}</li>)}</ul><nav aria-label="本课要点">{script.roadmap.map((point, index) => { const step = script.steps.findIndex(item => item.keypoint_id === point.keypoint_id); const available = step >= 0 && step <= teachingCursor; return <button key={point.keypoint_id} type="button" disabled={!available} onClick={() => view(step)} aria-current={current?.keypoint_id === point.keypoint_id ? 'step' : undefined}><span>{String(index + 1).padStart(2, '0')}</span><b>{point.title}</b><small>{available ? point.question : '讲到这里后可回看'}</small></button> })}</nav></div></details>}
    <div className="classroom-notices">
      {lesson.error && <ErrorNotice title="同步失败 · 自动播放已暂停" message={lesson.error} retry={() => { void lesson.reload() }} />}
      {!player.online && <p className="classroom-alert" role="alert">网络已断开，课堂已暂停。联网后不会自动播放或重新生成。</p>}
      {player.pending && <div className="classroom-alert" role="status"><span>{player.busy ? '正在串行保存…' : '上次写入结果待确认。保留原请求与命令编号。'}</span><button type="button" disabled={player.busy || !player.online} onClick={() => { void player.retry() }}>重试同一命令</button></div>}
      {player.error && <div className="classroom-alert error" role="alert"><span>{player.error}</span>{player.rejected && <button type="button" onClick={player.releaseRejected}>修改被拒绝的输入</button>}</div>}
      {script && activeRun(generation) && <div className="classroom-alert" role="status"><span>正在重新生成整课讲义；当前保存的版本仍保留，新版本成功后才替换。</span><button type="button" disabled={locked} onClick={() => { if (generation) void player.runAction(generation.run_id, 'cancel') }}>取消重新生成</button></div>}
      {script && generation && !activeRun(generation) && generation.status !== 'ready' && <div className="classroom-alert" role="status"><span>讲义生成{runLabels[generation.status]}，当前保存版本仍可查看。{generation.error?.message}</span><button type="button" disabled={lessonActionsDisabled} onClick={() => { void player.runAction(generation.run_id, 'retry') }}>明确重试讲义生成</button></div>}
      {script && font.state !== 'ready' && <div className="classroom-alert font-notice" role="status"><span>{font.state === 'loading' ? '正在加载 Excalifont 与小赖字体；结构图等待字体就绪。' : '指定手写字体未加载，文字使用可读回退；结构图暂停排版。'}</span>{font.state === 'error' && <button type="button" onClick={font.retry}>重试字体</button>}</div>}
    </div>
    <div className="classroom-workspace">
      <div className="classroom-canvas">
        {script ? <Board key={script.script_id} script={script} cursor={viewCursor} fontReady={font.state === 'ready'} selectedObjectId={selection} focusRequest={focusRequest} onSelectObject={selectObject} onReturnCurrent={returnCurrent} /> : <section className="classroom-unprepared" aria-label="课堂白板尚未准备">
          <div className="unprepared-heading"><span>PERSONAL CLASSROOM</span><h2>{snapshot.session.title}</h2><p>路线图 → 要点与例子 → 理解检查 → 回扣总结</p></div>
          {activeRun(generation) ? <><Loading label={"讲义" + (generation ? runLabels[generation.status] : '准备中') + '…'} /><p>仅显示真实服务端状态；刷新不会重新收费。</p>{generation && <button type="button" className="button secondary" disabled={locked} onClick={() => { void player.runAction(generation.run_id, 'cancel') }}>取消讲义生成</button>}</>
            : unsupported ? <EmptyState title="此讲义格式不受支持" action={<button type="button" className="button primary" disabled={locked} onClick={() => { void player.regenerate() }}>明确重新生成完整课堂</button>}>旧讲义保留，不清空、不转换。只有点击重生成才调用真实模型，可能产生费用。</EmptyState>
              : generation && generation.status !== 'ready' ? <EmptyState title={"讲义" + runLabels[generation.status]} action={<button type="button" className="button primary" disabled={locked} onClick={() => { void player.runAction(generation.run_id, 'retry') }}>明确重试讲义生成</button>}>{generation.error?.message || '讲义尚未保存成功。重试可能产生模型费用。'}</EmptyState>
                : <EmptyState title="准备本课讲义" action={<button type="button" className="button primary" disabled={locked} onClick={() => { void player.prepare() }}>准备本课讲义</button>}>当前只读取已保存状态。点击后使用真实模型生成完整课堂，可能产生费用；进入、刷新与重连不会生成。</EmptyState>}
        </section>}
      </div>
      {asideOpen && <aside id="classroom-sidebar" className="classroom-sidebar" aria-label="同步讲解与课堂提问">
        <nav className="classroom-sidebar-tabs" aria-label="课堂侧栏">{(['narration', 'ask', 'history'] as const).map(value => <button key={value} type="button" aria-pressed={tab === value} onClick={() => setTab(value)}>{value === 'narration' ? '同步讲解' : value === 'ask' ? '插问' : '问答历史'}{value === 'history' && snapshot.interactions.length > 0 ? ' · ' + snapshot.interactions.length : ''}</button>)}</nav>
        <div className="classroom-sidebar-scroll" ref={sidebarScroll}>
          {tab === 'narration' && <section className="classroom-narration" aria-labelledby="narration-title"><span className="classroom-stage">{current ? stageLabels[current.stage] : '准备开始'}{review ? ' · 回看' : ''}</span><h2 id="narration-title">{current?.title || '一块白板，一步一步讲清楚'}</h2><div className="classroom-prose classroom-teacher-talk">{(current?.narration || '开始播放后，我们会沿着白板上的顺序，一步一步把问题讲清楚。你也可以随时回看或插问。').split(/\n\s*\n/).map((paragraph, index) => <p key={index}><SafeText text={paragraph} /></p>)}</div>
            {current?.check && <section className="classroom-check" key={current.step_id}><h3>先用自己的话回答</h3><p><SafeText text={current.check.question} /></p><form onSubmit={event => { event.preventDefault(); submitQuestion('理解检查：' + current.check!.question + '\n我的回答：' + answer, () => setAnswer('')) }}><label htmlFor="check-answer">你的思考</label><textarea id="check-answer" value={answer} onChange={event => setAnswer(event.target.value)} maxLength={1400} disabled={lessonActionsDisabled} /><button type="submit" className="button primary" disabled={lessonActionsDisabled || answer.trim().length < 2}>提交回答，获得真实反馈</button><small>反馈会保存到问答历史并调用模型；不作评分或掌握判定。</small></form><details><summary>显式展开参考答案</summary><div className="classroom-prose"><SafeText text={current.check.expected_answer} /></div></details></section>}
            <nav className="confirmed-history" aria-label="已确认讲解历史"><h3>已讲内容</h3>{script?.steps.slice(0, teachingCursor + 1).map((step, index) => <button key={step.step_id} type="button" aria-current={index === viewCursor ? 'step' : undefined} onClick={() => view(index)}><span>{index + 1}</span>{step.title}</button>)}</nav>
            {script && <details className="classroom-script-settings"><summary>讲义生成说明与更新</summary><p>本课先一次性生成，再按步骤展开；不是每点下一步都请求模型。新版讲解风格只对新生成的讲义生效，已保存的内容不会自动改写。</p>{regenerateScriptId === script.script_id ? <div role="group" aria-label="确认重新生成讲义"><p>重新生成会调用真实模型，可能收费。成功后替换整课讲义并从头播放；旧原文保留，已有完成记录与问答不会撤销。</p><button type="button" className="button secondary" disabled={lessonActionsDisabled} onClick={() => { setRegenerateScriptId(null); void player.regenerate() }}>确认重新生成（可能收费）</button><button type="button" className="text-button" onClick={() => setRegenerateScriptId(null)}>保留当前讲义</button></div> : <button type="button" className="text-button" disabled={lessonActionsDisabled} onClick={() => setRegenerateScriptId(script.script_id)}>使用新版讲解重新生成</button>}</details>}
          </section>}
          {tab === 'ask' && <section className="classroom-question"><span className="classroom-stage">停一下，我想问</span><h2>针对正在看的内容提问</h2><p>{current ? '当前查看：第 ' + (viewCursor + 1) + ' 步 · ' + current.title : '先展开一个已确认的讲解步骤。'}{selection && <><br />已锚定板书对象 <code>{selection}</code> <button type="button" className="text-button" onClick={() => setSelection(null)}>取消对象选择</button></>}</p><form onSubmit={event => { event.preventDefault(); submitQuestion(question, () => setQuestion('')) }}><label htmlFor="lesson-question">你的问题</label><textarea id="lesson-question" value={question} onChange={event => setQuestion(event.target.value)} minLength={2} maxLength={2000} disabled={lessonActionsDisabled || !anchor} placeholder="这一步为什么这样做？" /><small>{question.trim().length} / 2000 字 · 会调用真实模型</small><button type="submit" className="button primary" disabled={lessonActionsDisabled || !anchor || question.trim().length < 2}>暂停并提问</button></form><p className="classroom-helper">先保存暂停，再提交问题；教学位置不回退。选中板书或图节点可为问题添加精确锚点。</p></section>}
          {tab === 'history' && <section className="classroom-interactions"><h2>课堂问答</h2>{snapshot.interactions.length ? snapshot.interactions.map(item => { const anchorCursor = script?.steps.findIndex(step => step.step_id === (item.anchor_step_id || item.step_id)) ?? -1; return <article key={item.interaction_id} className="classroom-interaction"><div><span>{interactionLabels[item.status]}</span>{anchorCursor >= 0 && anchorCursor <= teachingCursor && <button type="button" onClick={() => { view(anchorCursor, item.anchor_object_id); setTab('narration') }}>定位第 {anchorCursor + 1} 步</button>}</div><h3><SafeText text={item.question} /></h3>{item.answer !== null && <div className="classroom-prose"><SafeText text={item.answer} /></div>}{item.error && <p role="alert">{item.error.message}</p>}{item.status === 'pending' ? <button type="button" className="text-button" disabled={locked} onClick={() => { void player.runAction(item.run_id, 'cancel') }}>取消本次回答</button> : item.status !== 'ready' && <button type="button" className="text-button" disabled={locked || pendingQuestion} onClick={() => { void player.runAction(item.run_id, 'retry') }}>明确重试这个问题</button>}</article> }) : <p className="classroom-helper">你的问题、理解检查回答和反馈将持久保存在这里。</p>}</section>}
        </div>
        {player.hold && <div className="classroom-hold" data-interaction-id={player.hold.interaction_id} role="status"><b>{interactionLabels[player.hold.status]} · 课堂暂停</b><p>{pendingQuestion ? '回答结束后也不会自动播放。' : '回答已保留。明确继续将返回教学位置。'}</p><button type="button" className="button secondary" disabled={locked || pendingQuestion} onClick={() => { returnCurrent(); void player.continueLesson() }}>继续课堂</button></div>}
      </aside>}
    </div>
    <footer className="classroom-player" aria-label="课堂播放器"><div className="classroom-play-state"><b>{player.hold ? '插问后等待明确继续' : finished ? '最终总结已展示' : teaching?.stage === 'check' ? '理解检查 · 自动暂停' : player.playing ? '正在讲解' : '已暂停'}</b><span>{script ? '已确认 ' + Math.max(0, teachingCursor + 1) + ' / ' + script.steps.length : lesson.connection}</span><small>文字阅读节奏，非语音时长 · 刷新暂停</small></div><div className="classroom-play-actions">{review && <button type="button" className="button secondary" onClick={returnCurrent}>返回教学位置</button>}{player.playing ? <button type="button" className="button secondary" disabled={locked} onClick={() => { void player.pause() }}>暂停</button> : <button type="button" className="button primary" disabled={lessonActionsDisabled || finished} onClick={play}>{teachingCursor < 0 ? '开始播放' : teaching?.stage === 'check' ? '继续讲解' : '播放'}</button>}<button type="button" className="button secondary" disabled={lessonActionsDisabled || finished} onClick={next}>下一步 <IconArrowRight size={13} /></button>{finished && !snapshot.completed && <button type="button" className="button secondary" disabled={lessonActionsDisabled} onClick={() => { void player.complete() }}>确认完成本课</button>}<Link className="classroom-practice" to={back + '/sessions/' + encodeURIComponent(sessionId) + '/practice'} onClick={player.pauseLocal}>课后练习</Link></div></footer>
  </main>
}

export default function Classroom() {
  const { courseId = '', sessionId = '' } = useParams()
  return <SessionClassroom key={courseId + ':' + sessionId} courseId={courseId} sessionId={sessionId} />
}
