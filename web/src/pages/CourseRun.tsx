import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { BackLink, ErrorNotice, Loading, Mark, dateLabel } from '../components/ui'
import { IconArrowRight, IconBoard, IconCheck, IconChevronLeft } from '../components/icons'
import { BlueprintExplorer } from '../components/BlueprintExplorer'
import { RunResearch } from '../components/RunResearch'
import { blueprintDecision, hasAnswers, isTerminal, isWorking, needsClarificationAnswers, supersedingCourseRunId, toggleOption } from '../lib/run-state'
import { canReviewBlueprint } from '../lib/course-state'
import { savedPreferences, savedStructureCounts, workbenchStatus, workbenchSteps } from '../lib/workbench-state'
import { useRun } from '../lib/use-run'
import { useCourse } from '../lib/use-course'
import { useCommand } from '../lib/use-command'
import { useMediaQuery } from '../lib/use-media-query'
import { readPending } from '../lib/commands'
import type { Answer, Course, Question, Run } from '../lib/types'
import '../styles/workbench.css'

function QuestionField({ question, answer, change, index, disabled }: { question: Question; answer: Answer; change: (value: Answer) => void; index: number; disabled: boolean }) {
  return <fieldset className="question-field" disabled={disabled}>
    <legend><span className="question-number">{String(index + 1).padStart(2, '0')}</span>{question.question}<span className="question-kind">{question.type === 'multi' ? '多选' : '单选'}</span></legend>
    <div className="question-options">{question.options.map(option => <label className={`answer-option ${answer.option_ids.includes(option.id) ? 'selected' : ''}`} key={option.id}>
      <input type={question.type === 'multi' ? 'checkbox' : 'radio'} name={question.id} checked={answer.option_ids.includes(option.id)} onChange={() => change(toggleOption(question, answer, option.id))} />
      <span><b>{option.label}</b>{option.description && <small>{option.description}</small>}</span>
    </label>)}</div>
    {question.allow_custom && <label className="custom-answer" htmlFor={`custom-${question.id}`}>补充你的想法{question.type === 'multi' ? '（可与选项一起提交）' : '（将替代选项）'}<textarea id={`custom-${question.id}`} rows={2} value={answer.custom_text} maxLength={2000} placeholder="用自己的话描述…" onChange={event => change({ ...answer, custom_text: event.target.value, option_ids: question.type === 'single' && event.target.value.trim() ? [] : answer.option_ids })} /></label>}
  </fieldset>
}

function Preferences({ run }: { run: Run }) {
  const preferences = savedPreferences(run)
  return <section className="wb-brief" aria-labelledby="brief-title">
    <h2 id="brief-title">我的学习需求</h2><p className="wb-goal-preview">{run.goal}</p>
    <details><summary>查看完整需求{preferences.length ? '与选择' : ''}</summary><p className="wb-full-text">{run.goal}</p>{preferences.map((item, index) => <div className="wb-answer-detail" key={index}><h3>{item.question}</h3><p>{item.values.join('、')}</p></div>)}</details>
    {!!preferences.length && <div className="wb-preference-tags" aria-label="已提交的学习偏好">{preferences.flatMap((item, index) => item.values.map((value, i) => <span key={`${index}-${i}`} title={value}>{value}</span>))}</div>}
    {run.skipped && <p className="wb-small-note">你已跳过补充问题，按原始目标规划。</p>}
    {run.blueprint_feedback && <details className="wb-feedback-history"><summary>最近的调整意见</summary><p className="wb-full-text">{run.blueprint_feedback}</p></details>}
  </section>
}

function RevisionDialog({ feedback, setFeedback, locked, reviewable, close, submit, returnFocusTo }: { feedback: string; setFeedback: (value: string) => void; locked: boolean; reviewable: boolean; close: () => void; submit: () => void; returnFocusTo: HTMLButtonElement | null }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { const element = dialog.current!; element.showModal(); return () => { element.close(); if (returnFocusTo?.isConnected) returnFocusTo.focus() } }, [returnFocusTo])
  return <dialog className="wb-revision-dialog" ref={dialog} aria-labelledby="revision-title" onCancel={event => { event.preventDefault(); close() }}>
    <form onSubmit={event => { event.preventDefault(); if (feedback.trim() && !locked && reviewable) submit() }}>
      <div className="wb-dialog-heading"><h2 id="revision-title">调整课程方向</h2><button className="wb-icon-button" type="button" aria-label="关闭调整面板" onClick={close}>×</button></div>
      <p>告诉我们哪里需要调整。将根据已有资料重新安排蓝图，之后再请你确认。</p>
      <label className="custom-answer" htmlFor="blueprint-feedback">修改意见<textarea autoFocus id="blueprint-feedback" rows={6} maxLength={6000} value={feedback} disabled={locked} placeholder="例如：减少入门内容，把第二单元的重点放在实践…" onChange={event => setFeedback(event.target.value)} /></label>
      {!reviewable && <p className="wb-source-warning">正在同步课程方向，暂时不能提交。请关闭面板后检查当前状态。</p>}
      <div className="form-actions"><button className="button secondary" type="button" onClick={close}>暂不调整</button><button className="button primary" type="submit" disabled={locked || !feedback.trim() || !reviewable}>提交修改意见</button></div>
    </form>
  </dialog>
}

type RunCommand = ReturnType<typeof useCommand<Run>>
interface WorkspaceProps {
  run: Run; command: RunCommand; error: string | null; reload: () => void; connection: string
  draft: Record<string, Answer>; setDraft: (value: Record<string, Answer>) => void
  feedback: string; setFeedback: (value: string) => void
}

function Workspace({ run, command, error, reload, connection, draft, setDraft, feedback, setFeedback,
  course, courseError, courseConnection, reloadCourse }: WorkspaceProps & { course: Course | null; courseError: string | null; courseConnection: string; reloadCourse: () => void }) {
  // The research list lives in the right rail, or inline when that rail is hidden.
  const narrowRail = useMediaQuery('(max-width: 1100px)')
  const [adjusting, setAdjusting] = useState(false)
  const adjustButton = useRef<HTMLButtonElement>(null)
  const [params] = useSearchParams()
  const historical = params.get('history') === '1'
  const locked = command.busy || !!command.pending
  const reviewable = canReviewBlueprint(run, course) && !courseError && !error
  const status = workbenchStatus(run, course)
  const counts = savedStructureCounts(course)
  const awaitingAnswers = needsClarificationAnswers(run)
  const answers = run.questions.map(question => draft[question.id] ?? run.answers.find(answer => answer.question_id === question.id) ?? { question_id: question.id, option_ids: [], custom_text: '' })
  const submitAnswers = (event: FormEvent) => {
    event.preventDefault()
    if (locked || !awaitingAnswers || !hasAnswers(run.questions, answers)) return
    void command.execute(`/runs/${encodeURIComponent(run.run_id)}/answers`, { expected_version: run.version, skip: false, answers: answers.map(answer => ({ ...answer, custom_text: answer.custom_text.trim() })) })
  }
  const decide = (approve: boolean) => {
    const body = blueprintDecision(run, approve, approve ? '' : feedback, locked)
    if (!body || !reviewable) return
    setAdjusting(false)
    void command.execute(`/runs/${encodeURIComponent(run.run_id)}/blueprint`, body)
  }
  const mutate = (action: 'cancel' | 'retry') => { void command.execute(`/runs/${encodeURIComponent(run.run_id)}/${action}`, { expected_version: run.version }) }
  const firstSession = course?.units.flatMap(unit => unit.lectures.flatMap(lecture => lecture.sessions))[0]
  const nextPath = course && firstSession ? `/courses/${encodeURIComponent(course.course_id)}/sessions/${encodeURIComponent(firstSession.session_id)}` : null
  const latestRunId = supersedingCourseRunId(run, course)
  const ownerChanged = !!latestRunId
  const actionNote = ownerChanged ? '这份课程已有后续生成任务，请前往最新状态。' : command.pending ? '请先确认上次操作的结果，避免重复提交。' :
    run.status === 'awaiting_blueprint' ? reviewable ? '确认后将自动完善全部单元，无需逐单元确认。' : '正在同步本次课程方向，请稍候。' :
    awaitingAnswers ? '选择偏好或填写答案，也可以跳过。' : run.status === 'ready' ? '从第一课开始，或先查看完整课程。' : run.error?.retryable === false ? '请先处理显示的问题；直接重试相同输入不保证解决。已保存内容仍保留。' :
      isTerminal(run.status) ? '已保存的内容不会丢失，可继续未完成部分。' : '内容会持续保存，你可以稍后回来查看。'

  return <div className="creation-workbench">
    <header className="wb-header"><Link to="/courses" className="wb-back"><IconChevronLeft size={15} />我的课程</Link><Link to="/" className="wb-brand" aria-label="Hyperknow 首页"><Mark small /><span>Hyperknow</span></Link><h1>{course?.title ?? '设计你的课程'}</h1><span className="wb-header-state">{historical ? '历史生成记录' : run.status === 'ready' ? '课程已保存' : run.status === 'awaiting_blueprint' ? '等待你确认' : isTerminal(run.status) ? '生成已停止' : '课程设计'}</span></header>
    <div className="wb-body">
      <aside className="wb-context" aria-label="学习需求与生成进展">
        <Preferences run={run} />
        <section className="wb-progress" aria-labelledby="progress-title"><h2 id="progress-title">课程设计进展</h2><ol>{workbenchSteps(run).map((step, i) => <li className={`wb-step is-${step.state}`} key={step.stage} aria-current={step.state === 'active' || step.state === 'waiting' ? 'step' : undefined}><span aria-hidden="true">{step.state === 'done' ? <IconCheck size={13} /> : String(i + 1).padStart(2, '0')}</span><span>{step.label}</span><small>{({ done: '已完成', pending: '待开始', waiting: '待确认', active: '进行中', stopped: '已停止' } as Record<string, string>)[step.state]}</small></li>)}</ol>
          <div className="wb-current" role="status"><h3>{isWorking(run.status) && <span className="wb-busy-dot" aria-hidden="true" />}{status.title}</h3><p>{status.description}</p></div>
          {course && <p className="wb-saved-counts">已保存 <b>{counts.units}</b> / {course.units.length} 单元 · <b>{counts.lectures}</b> 讲次 · <b>{counts.sessions}</b> 小节</p>}
        </section>
        {error && <ErrorNotice title="状态暂时无法同步" message={error} retry={reload} />}
        {run.error && <ErrorNotice title="生成需要处理" message={run.error.message} />}
        {command.error && <ErrorNotice title="上次操作尚未确认" message={command.error} />}
        {awaitingAnswers && <form id="course-preferences" className="wb-questions" onSubmit={submitAnswers}><h2>补充你的偏好</h2>{run.questions.map((question, index) => <QuestionField key={question.id} question={question} index={index} answer={answers[index]} disabled={locked} change={answer => setDraft({ ...draft, [question.id]: answer })} />)}</form>}
        {narrowRail && <div className="wb-research-inline"><RunResearch research={run.research} /></div>}
      </aside>
      <section className="wb-result" aria-label="课程蓝图工作区"><div className="wb-result-heading"><h2>课程蓝图</h2><span>{course ? `${course.units.length} 单元 · ${counts.sessions} 已生成小节` : '单元顺序与学习路径'}</span></div>
        {courseError && <ErrorNotice title="课程结构暂时无法同步" message={courseError} retry={reloadCourse} />}
        {course ? <BlueprintExplorer course={course} currentUnitId={isWorking(run.status) && run.stage === 'units' ? run.current_unit_id : null} /> : run.course_id ? !courseError && <Loading label="正在读取已保存的课程方向…" /> : <div className="wb-empty-blueprint"><span aria-hidden="true"><IconBoard size={38} strokeWidth={1.2} /></span><h3>先定方向，再安排每一步</h3><p>{run.status === 'awaiting_answers' ? '补充左侧偏好后，我们会结合参考资料设计课程。' : '完成需求与资料调研后，全部单元会一起出现在这里。'}</p><div><span>你的目标</span><i aria-hidden="true" /><span>单元路径</span><i aria-hidden="true" /><span>讲次与小节</span></div><small>这是流程说明，尚未生成课程内容。</small></div>}
      </section>
      <aside className="wb-rail" aria-label="资料调研与运行详情">
        <h2>资料与依据</h2>
        <p className="wb-rail-note">课程设计实际使用的网页资料与限制。</p>
        <RunResearch research={run.research} />
        <details className="run-details"><summary>运行详情</summary><p>{connection} · {courseConnection}</p><dl><div><dt>运行编号</dt><dd>{run.run_id}</dd></div><div><dt>模型</dt><dd>{run.model}</dd></div><div><dt>创建时间</dt><dd>{dateLabel(run.created_at)}</dd></div><div><dt>状态版本</dt><dd>{run.version}</dd></div>{course?.blueprint_version != null && <div><dt>蓝图版本</dt><dd>{course.blueprint_version}</dd></div>}{run.parent_run_id && <div><dt>重试来源</dt><dd><Link to={`/course-runs/${encodeURIComponent(run.parent_run_id)}?history=1`}>查看上次运行</Link></dd></div>}</dl>{run.usage && <pre>{JSON.stringify(run.usage, null, 2)}</pre>}<button className="text-button" type="button" onClick={() => { reload(); reloadCourse() }}>刷新状态</button></details>
      </aside>
    </div>
    <footer className="wb-actionbar" role="region" aria-label="当前阶段操作"><div className="wb-action-caption"><strong>{status.title}</strong><p>{actionNote}</p></div><div className="wb-action-buttons">
      {command.pending ? command.conflict ? <button className="button primary" disabled={command.busy} onClick={() => { command.releaseConflict(); reload(); reloadCourse() }}>同步最新状态</button> : command.rejected ? <button className="button primary" disabled={command.busy} onClick={command.releaseRejected}>修改后重新提交</button> : <button className="button primary" disabled={command.busy} onClick={() => { void command.execute() }}>{command.busy ? '正在确认…' : '确认上次操作'}</button> : latestRunId ? <Link className="button primary" to={`/course-runs/${encodeURIComponent(latestRunId)}`}>查看最新生成状态</Link> : <>
      {awaitingAnswers && <><button className="button secondary" disabled={locked} onClick={() => { void command.execute(`/runs/${encodeURIComponent(run.run_id)}/answers`, { expected_version: run.version, skip: true, answers: [] }) }}>跳过补充</button><button className="button primary" type="submit" form="course-preferences" disabled={locked || !hasAnswers(run.questions, answers)}>提交偏好并继续</button></>}
      {run.status === 'awaiting_blueprint' && <><button ref={adjustButton} className="button secondary" disabled={locked || !reviewable} onClick={() => setAdjusting(true)}>调整方向</button><button className="button primary" disabled={locked || !reviewable} onClick={() => decide(true)}>确认并完善课程</button></>}
      {run.status === 'ready' && course && <><Link className="button secondary" to={`/courses/${encodeURIComponent(course.course_id)}`}>查看课程总览</Link>{nextPath && <Link className="button primary" to={nextPath}>开始学习 <IconArrowRight size={13} /></Link>}</>}
      {['failed', 'cancelled', 'interrupted'].includes(run.status) && <>{course && <Link className="button secondary" to={`/courses/${encodeURIComponent(course.course_id)}`}>查看已保存内容</Link>}<button className="button primary" disabled={locked} onClick={() => mutate('retry')}>继续生成剩余内容</button></>}
      {!isTerminal(run.status) && run.status !== 'awaiting_answers' && run.status !== 'awaiting_blueprint' && <button className="button secondary" disabled={locked} onClick={() => mutate('cancel')}>停止生成</button>}
      </>}
      {(!isTerminal(run.status) && ['awaiting_answers', 'awaiting_blueprint'].includes(run.status)) && !command.pending && !ownerChanged && <button className="text-button danger wb-stop" disabled={locked} onClick={() => mutate('cancel')}>停止</button>}
    </div></footer>
    {adjusting && <RevisionDialog feedback={feedback} setFeedback={setFeedback} locked={locked} reviewable={reviewable} close={() => setAdjusting(false)} submit={() => decide(false)} returnFocusTo={adjustButton.current} />}
  </div>
}

function WithCourse(props: WorkspaceProps) {
  const { course, error, connection, reload } = useCourse(props.run.course_id!)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const latestRunId = supersedingCourseRunId(props.run, course)
  const redirect = !error && params.get('history') !== '1' && !props.command.pending ? latestRunId : null
  useEffect(() => {
    if (redirect) navigate(`/course-runs/${encodeURIComponent(redirect)}`, { replace: true })
  }, [redirect, navigate])
  if (redirect) return <div className="wb-loading"><Loading label="正在打开最新生成状态…" /></div>
  return <Workspace {...props} course={course} courseError={error} courseConnection={connection} reloadCourse={() => { void reload() }} />
}

function RunContent({ runId }: { runId: string }) {
  const { run, error, reload, connection, accept } = useRun(runId)
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Record<string, Answer>>(() => {
    const saved = readPending(`run:${runId}`)?.body.answers
    return Array.isArray(saved) ? Object.fromEntries((saved as Answer[]).map(answer => [answer.question_id, answer])) : {}
  })
  const [feedback, setFeedback] = useState(() => String(readPending(`run:${runId}`)?.body.feedback ?? ''))
  const command = useCommand<Run>(`run:${runId}`, value => {
    if (value.run_id !== runId) navigate(`/course-runs/${encodeURIComponent(value.run_id)}`)
    else { accept(value); reload() }
  })
  if (!run) return <div className="wb-loading"><BackLink to="/courses">我的课程</BackLink>{error ? <ErrorNotice title="运行加载失败" message={error} retry={reload} /> : <Loading label="正在恢复课程设计状态…" />}</div>
  const props = { run, error, reload, connection, command, draft, setDraft, feedback, setFeedback }
  return run.course_id ? <WithCourse key={run.course_id} {...props} /> : <Workspace {...props} course={null} courseError={null} courseConnection="尚未创建课程结构" reloadCourse={() => {}} />
}

export default function CourseRun() {
  const { runId = '' } = useParams()
  return <RunContent key={runId} runId={runId} />
}
