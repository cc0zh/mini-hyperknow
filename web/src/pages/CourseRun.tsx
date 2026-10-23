import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Arrow, ErrorNotice, Loading, dateLabel } from '../components/ui'
import { RunBlueprint } from '../components/RunBlueprint'
import { RunResearch } from '../components/RunResearch'
import { blueprintDecision, hasAnswers, isTerminal, isWorking, runHeading, stageLabels, toggleOption } from '../lib/run-state'
import { useRun } from '../lib/use-run'
import { useCommand } from '../lib/use-command'
import { readPending } from '../lib/commands'
import type { Answer, Question, Run } from '../lib/types'

const explanations = {
  queued: '学习目标已保存，等待本地模型执行槽。你可以离开页面，稍后回来查看。',
  clarifying: '模型正在分析你的学习需求，准备需要确认的问题。',
  awaiting_answers: '补充你的偏好，让课程更贴合你。也可以跳过，直接根据原始目标生成。',
  awaiting_blueprint: '全局蓝图已保存。请审阅课程方向，批准后自动逐单元展开；也可提交修改意见。等待期间不占用模型槽。',
  generating: '模型正在根据学习目标与已提交答案生成课程结构。结构校验并保存后即可查看。',
  ready: '课程结构已校验并保存。现在可以打开总览，查看完整的学习路径。',
  failed: '本次生成失败。已保存的调研、蓝图和单元内容会保留，可手动重试未完成阶段。',
  cancelled: '这次运行已取消。已保存的部分内容会保留，可手动重试。',
  interrupted: '上次运行被进程中断，不会自动重新调用模型。你可以手动重试。',
}

const stageExplanations = {
  clarifying: explanations.clarifying,
  research: '正在搜索和阅读真实网页；左侧显示已保存的活动、资料与调研结论。',
  blueprint: '正在根据学习目标、澄清答案与调研资料规划课程骨架。保存后等待你批准，不会提前展开单元。',
  units: '蓝图已确认，正在按顺序自动展开各单元的讲次、小节、项目阶段与考核。已就绪单元随时保存。',
}

function QuestionField({ question, answer, change, index, disabled }: { question: Question; answer: Answer; change: (value: Answer) => void; index: number; disabled: boolean }) {
  return <fieldset className="question-field" disabled={disabled}>
    <legend><span className="question-number">{String(index + 1).padStart(2, '0')}</span>{question.question}<span className="question-kind">{question.type === 'multi' ? '多选' : '单选'}</span></legend>
    <div className="question-options">{question.options.map(option => <label className={`answer-option ${answer.option_ids.includes(option.id) ? 'selected' : ''}`} key={option.id}>
      <input type={question.type === 'multi' ? 'checkbox' : 'radio'} name={question.id} checked={answer.option_ids.includes(option.id)} onChange={() => change(toggleOption(question, answer, option.id))} />
      <span><b>{option.label}</b>{option.description && <small>{option.description}</small>}</span>
    </label>)}</div>
    {question.allow_custom && <label className="custom-answer" htmlFor={`custom-${question.id}`}>或补充你的想法{question.type === 'multi' ? '（可与选项一起提交）' : '（填写后替代上方选项）'}<textarea id={`custom-${question.id}`} rows={2} value={answer.custom_text} maxLength={2000} placeholder="用自己的话描述…" onChange={event => change({ ...answer, custom_text: event.target.value, option_ids: question.type === 'single' && event.target.value.trim() ? [] : answer.option_ids })} /></label>}
  </fieldset>
}

function RunContent({ runId }: { runId: string }) {
  const { run, error, reload, connection, accept } = useRun(runId)
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Record<string, Answer>>(() => {
    const saved = readPending(`run:${runId}`)?.body.answers
    return Array.isArray(saved) ? Object.fromEntries((saved as Answer[]).map(answer => [answer.question_id, answer])) : {}
  })
  const command = useCommand<Run>(`run:${runId}`, value => {
    if (value.run_id !== runId) navigate(`/course-runs/${encodeURIComponent(value.run_id)}`)
    else { accept(value); reload() }
  })
  if (!run) return <div className="page narrow"><Link className="back-link" to="/">← 回到首页</Link>{error ? <ErrorNotice title="运行加载失败" message={error} retry={reload} /> : <Loading label="正在连接并恢复运行状态…" />}</div>

  const answers = run.questions.map(question => draft[question.id] ?? run.answers.find(answer => answer.question_id === question.id) ?? { question_id: question.id, option_ids: [], custom_text: '' })
  const locked = command.busy || !!command.pending
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!hasAnswers(run.questions, answers) || locked) return
    void command.execute(`/runs/${encodeURIComponent(runId)}/answers`, { expected_version: run.version, skip: false, answers: answers.map(answer => ({ ...answer, custom_text: answer.custom_text.trim() })) })
  }
  const mutate = (action: 'cancel' | 'retry') => {
    void command.execute(`/runs/${encodeURIComponent(runId)}/${action}`, { expected_version: run.version })
  }
  const active = !isTerminal(run.status)
  const retryAllowed = ['failed', 'cancelled', 'interrupted'].includes(run.status)
  const decide = (approve: boolean, feedback: string) => {
    const body = blueprintDecision(run, approve, feedback, locked)
    if (body) void command.execute(`/runs/${encodeURIComponent(runId)}/blueprint`, body)
  }

  return <div className="page run-page">
    <div className="run-page-top"><Link className="back-link" to="/">← 首页</Link><span className="connection-label">{connection}</span></div>
    <div className="run-heading"><span className="eyebrow">CRAFT YOUR COURSE</span><h1>把目标，变成路径<span className="heading-dot">.</span></h1></div>
    <div className="run-workspace"><div className="run-activity">
    <div className="goal-bubble"><span className="eyebrow">你的学习目标</span><p>{run.goal}</p></div>
    <section className={`run-status status-${run.status}`} aria-live="polite" aria-atomic="true"><span className={`status-symbol ${isWorking(run.status) ? 'working' : ''}`} aria-hidden="true">{run.status === 'ready' ? '✓' : run.status === 'failed' || run.status === 'interrupted' ? '!' : '✳'}</span><div><h2>{runHeading(run)}</h2><p>{run.status === 'generating' && run.stage ? stageExplanations[run.stage] : explanations[run.status]}</p>{run.stage && <p className="run-stage">当前阶段：{stageLabels[run.stage]}</p>}</div></section>
    {error && <ErrorNotice title="暂时无法同步状态" message={error} retry={reload} />}
    {run.error && <ErrorNotice title={`运行错误 · ${run.error.code}`} message={run.error.message} />}
    {command.error && <ErrorNotice title="命令未确认" message={command.error} />}
    {command.rejected && <button className="text-button" type="button" onClick={command.releaseRejected}>修改内容后重新提交</button>}
    {command.pending && <div className="pending-command" role="status"><div><b>{command.conflict ? '请求版本已过期' : '有一条尚未确认的请求'}</b><p>{command.conflict ? '服务器明确拒绝了这次写入，请同步当前状态后再操作。' : '重试会复用相同请求内容、版本和编号，避免重复写入。'}</p></div>{command.conflict ? <button className="button secondary small" onClick={() => { command.releaseConflict(); reload() }}>同步当前状态</button> : <button className="button secondary small" disabled={command.busy} onClick={() => { void command.execute() }}>{command.busy ? '正在确认…' : '重试同一命令'}</button>}</div>}
    {run.status === 'awaiting_answers' && <form className="clarification-form" onSubmit={submit}>
      <div className="section-heading"><h2>先了解你一点</h2><span>{run.questions.length} 个问题</span></div>
      {run.questions.length === 0 ? <p className="inline-note">本次没有需要回答的问题，可以直接继续。</p> : run.questions.map((question, index) => <QuestionField key={question.id} question={question} index={index} answer={answers[index]} disabled={locked} change={answer => setDraft(previous => ({ ...previous, [question.id]: answer }))} />)}
      <div className="form-actions"><button className="button secondary" type="button" disabled={locked} onClick={() => { void command.execute(`/runs/${encodeURIComponent(runId)}/answers`, { expected_version: run.version, skip: true, answers: [] }) }}>跳过，直接生成</button><button className="button primary" type="submit" disabled={locked || !hasAnswers(run.questions, answers)}>提交并生成 <Arrow /></button></div>
      {!hasAnswers(run.questions, answers) && <p className="form-hint">请为每个问题选择选项或填写答案，也可以明确跳过全部问题。</p>}
    </form>}
    <RunResearch research={run.research} />
    {run.status === 'ready' && (run.course_id ? <div className="ready-card"><div><span className="eyebrow">YOUR PATH IS READY</span><h2>下一段探索，已铺好路径。</h2><p>查看课程结构、课时安排与项目目标。</p></div><Link className="button primary" to={`/courses/${encodeURIComponent(run.course_id)}`}>进入课程总览 <Arrow /></Link></div> : <ErrorNotice title="课程数据不完整" message="运行已就绪，但没有返回课程编号。请重新读取状态。" retry={reload} />)}
    <div className="run-bottom-actions">{active && <button className="text-button danger" disabled={locked} onClick={() => mutate('cancel')}>取消本次运行</button>}{retryAllowed && <button className="button primary" disabled={locked} onClick={() => mutate('retry')}>重新尝试 <Arrow /></button>}{!active && <Link className="text-button" to="/">用新的目标创建课程</Link>}<button className="text-button" type="button" onClick={reload}>刷新状态</button></div>
    <details className="run-details"><summary>运行详情</summary><dl><div><dt>运行编号</dt><dd>{run.run_id}</dd></div><div><dt>模型</dt><dd>{run.model || '未配置'}</dd></div><div><dt>创建时间</dt><dd>{dateLabel(run.created_at)}</dd></div><div><dt>状态版本</dt><dd>{run.version}</dd></div>{run.parent_run_id && <div><dt>重试来源</dt><dd><Link to={`/course-runs/${encodeURIComponent(run.parent_run_id)}`}>查看原运行</Link></dd></div>}</dl>{run.usage && Object.keys(run.usage).length > 0 && <><h3>模型实际返回的用量</h3><pre>{JSON.stringify(run.usage, null, 2)}</pre></>}</details>
    </div><aside className="run-structure">{run.course_id ? <RunBlueprint key={run.course_id} run={run} locked={locked} decide={decide} /> : <section className="blueprint-placeholder"><span className="eyebrow">COURSE BLUEPRINT</span><h2>课程蓝图</h2><p>完成澄清与真实调研后，这里将显示已保存的课程目标、全局项目与单元路径。</p><p className="inline-note">目前尚未保存课程骨架，不展示示例目录。全局蓝图经你批准后才会自动展开。</p></section>}</aside></div>
  </div>
}

export default function CourseRun() {
  const { runId = '' } = useParams()
  return <RunContent key={runId} runId={runId} />
}
