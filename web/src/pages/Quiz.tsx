import { IconArrowRight, IconCheck, IconChevronLeft, IconStar } from '../components/icons'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorNotice, Loading, dateLabel, useHealth } from '../components/ui'
import { describeError, request } from '../lib/api'
import { activeRun } from '../lib/lesson-state'
import { answerCommand, attemptTransition, commandAttemptId, followLatestAttempt, matchesQuizScope, nextLearningPath, quizStorageKey, quizTargetPath, selectedQuizOptions } from '../lib/quiz-state'
import type { QuizScope, QuizCommand } from '../lib/quiz-state'
import { runLabels } from '../lib/run-state'
import type { AttemptSnapshot, QuizAnswer, QuizAttempt, QuizQuestion, Run } from '../lib/types'
import { useAttempt } from '../lib/use-attempt'
import { savedQuizCommand, useQuizCommand } from '../lib/use-quiz-command'
import { useQuizTarget } from '../lib/use-quiz-target'

const kinds = { single: '单选题 · 点击即提交', multiple: '多选题 · 选择后确认', boolean: '判断题 · 点击即提交' }
const elapsedLabel = (ms: number) => `${(ms / 1000).toFixed(1)} 秒`

function Feedback({ question, answer }: { question: QuizQuestion; answer: QuizAnswer }) {
  return <div className={`quiz-feedback ${answer.correct ? 'correct' : ''}`} role="status">
    <b>{answer.skipped ? '已保存：跳过本题' : answer.correct ? '回答正确' : '回答不正确'}</b>
    <p>{answer.points} 分 · 用时 {elapsedLabel(answer.elapsed_ms)}{answer.fast ? ' · 快答' : ''}</p>
    <p>正确选项：{question.options.filter(option => question.correct_option_ids.includes(option.id)).map(option => option.text).join('；')}</p>
    <div className="quiz-prose">{question.explanation}</div>
  </div>
}

function AnswerCard({ snapshot, locked, send }: { snapshot: AttemptSnapshot; locked: boolean; send: (options: string[], skipped: boolean) => void }) {
  const { quiz, attempt } = snapshot
  const question = quiz.questions[attempt.cursor]
  const [draft, setDraft] = useState<string[]>([])
  if (!question) return <ErrorNotice title="题目位置异常" message="当前保存位置不在题组范围内，请重新读取服务端状态。" />
  const answer = attempt.answers.find(item => item.question_id === question.question_id)
  const selected = selectedQuizOptions(question.question_id, draft, attempt)
  return <section className="question-card quiz-question" aria-labelledby="quiz-question-title">
    <div className="question-heading"><span className="question-index">{String(attempt.cursor + 1).padStart(2, '0')}</span><span className="question-kind">{kinds[question.kind]}</span></div>
    <h2 id="quiz-question-title" className="quiz-prose">{question.prompt}</h2>
    <fieldset disabled={locked || !!answer} className="quiz-options"><legend className="sr-only">选择答案</legend><div className="question-options">
      {question.options.map(option => <label className={`answer-option ${selected.includes(option.id) ? 'selected' : ''}`} key={option.id}>
        <input type={question.kind === 'multiple' ? 'checkbox' : 'radio'} name={`answer-${attempt.attempt_id}-${question.question_id}`} value={option.id} checked={selected.includes(option.id)} onChange={() => {
          if (question.kind === 'multiple') setDraft(previous => previous.includes(option.id) ? previous.filter(id => id !== option.id) : [...previous, option.id])
          else send([option.id], false)
        }} /><span className="quiz-prose">{option.text}</span>
      </label>)}
    </div></fieldset>
    {answer ? <Feedback question={question} answer={answer} /> : <div className="quiz-actions">
      <button type="button" className="button secondary" disabled={locked} onClick={() => send([], true)}>跳过本题</button>
      {question.kind === 'multiple' && <button type="button" className="button primary" disabled={locked || !draft.length} onClick={() => send(draft, false)}>确认答案</button>}
    </div>}
    <p className="form-hint">只有服务端保存确认后才展示判定与解释。用时取自已保存的本题起点，刷新不会重置；单题超过24小时按24小时记录。这是学习记录，不是防作弊考试。</p>
  </section>
}

function Results({ snapshot }: { snapshot: AttemptSnapshot }) {
  const { quiz, attempt, course } = snapshot
  const result = attempt.result
  if (!result) return <ErrorNotice title="结果数据不完整" message="服务端已提交，但没有返回结果，请重新读取。" />
  const next = nextLearningPath(course)
  return <>
    <section className="aside-card quiz-result" aria-labelledby="quiz-result-title"><span className="eyebrow">YOUR SAVED RESULT</span><h2 id="quiz-result-title">本次结果已保存</h2><div className="quiz-stars" aria-label={`${result.stars} 颗星`} style={{ animationDelay: '60ms' }}>{Array.from({ length: 3 }, (_, i) => <IconStar key={i} size={20} filled={i < result.stars} />)}</div><p className="quiz-score">{result.total_score}<small> / {result.max_score} 分</small></p>
      <dl className="quiz-statistics"><div><dt>答对</dt><dd>{result.correct_count} / {result.question_count}</dd></div><div><dt>跳过</dt><dd>{result.skipped_count}</dd></div><div><dt>快答</dt><dd>{result.fast_count}</dd></div><div><dt>最高连击</dt><dd>{result.best_streak}</dd></div><div><dt>总用时</dt><dd>{elapsedLabel(result.total_elapsed_ms)}</dd></div></dl>
      <p className="aside-note">结果由服务端计分并保存，不设通过线。{attempt.target_type === 'practice' ? '所属课时完成情况' : '考核完成情况'}由后端提交事务确认；课程进度仍只计算课时。</p>
      <div className="quiz-actions"><Link className="button secondary" to={`/courses/${encodeURIComponent(course.course_id)}`}>返回课程目录</Link>{next && <Link className="button primary" to={next}>继续：{course.next_item?.title} <IconArrowRight size={13} /></Link>}</div>
      {course.next_item && !next && <p className="form-hint">下一项：{course.next_item.title} · 项目成果提交尚未开放。</p>}
    </section>
    <section className="quiz-review"><div className="section-heading"><h2>本次作答回顾</h2><span>历史结果只读</span></div>{quiz.questions.map((question, index) => {
      const answer = attempt.answers.find(item => item.question_id === question.question_id)
      return <article className="question-card" key={question.question_id}><h3 className="quiz-prose">{index + 1}. {question.prompt}</h3><p className="quiz-prose">你的答案：{answer?.skipped ? '跳过' : question.options.filter(option => answer?.option_ids.includes(option.id)).map(option => option.text).join('；')}</p>{answer && <Feedback question={question} answer={answer} />}</article>
    })}</section>
  </>
}

function TargetQuiz(scope: QuizScope) {
  const { courseId, targetType, targetId } = scope
  const [search, setSearch] = useSearchParams()
  const storageKey = quizStorageKey(scope)
  const [recoveredAttempt] = useState(() => commandAttemptId(savedQuizCommand(storageKey)))
  const selectedId = search.get('attempt') || recoveredAttempt
  const target = useQuizTarget(scope)
  const attempt = useAttempt(selectedId, scope)
  const health = useHealth()
  const [localError, setLocalError] = useState<string | null>(null)
  const [history, setHistory] = useState<QuizAttempt[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [readingRun, setReadingRun] = useState(false)
  const back = `/courses/${encodeURIComponent(courseId)}`
  const targetPath = quizTargetPath(targetType, targetId)
  const selectAttempt = (id: string) => setSearch({ attempt: id })
  const command = useQuizCommand(storageKey, async value => {
    if ('attempt' in value) {
      if (!matchesQuizScope(value.attempt, scope) || !matchesQuizScope(value.quiz, scope) || value.course.course_id !== courseId) throw new Error('服务器返回了不属于当前课程的作答，未展示。请保留原命令并重试确认。')
      attempt.accept(value)
      selectAttempt(value.attempt.attempt_id)
      setHistoryRevision(revision => revision + 1)
    } else if ('target_type' in value && 'latest_attempt' in value) {
      if (!target.accept(value)) throw new Error('服务器返回了不属于当前课程的题组，未展示。')
    }
    // Run replay is deliberately re-read instead of assuming it is a target.
    await target.reload()
  }, async () => { await Promise.all([target.reload(), attempt.reload()]); setHistoryRevision(revision => revision + 1) })
  const locked = command.busy || !!command.pending || !command.online || readingRun || !!target.error || !!attempt.error
  const snapshot = target.snapshot
  const liveAttempt = attempt.snapshot
  const quizId = snapshot?.quiz?.quiz_id

  useEffect(() => {
    // Pin the chosen attempt in the URL. Later attempts in another tab must not
    // replace this result, including after refresh and browser history navigation.
    const next = followLatestAttempt(selectedId, snapshot?.latest_attempt ?? null)
    if (!selectedId && next && snapshot?.latest_attempt && matchesQuizScope(snapshot.latest_attempt, scope)) selectAttempt(next)
  }, [selectedId, snapshot?.latest_attempt?.attempt_id])

  useEffect(() => {
    setHistory([])
    setHistoryError(null)
    if (!quizId) return
    const controller = new AbortController()
    void request<{ attempts: QuizAttempt[] }>(`/quizzes/${encodeURIComponent(quizId)}/attempts`, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return
      if (value.attempts.some(item => !matchesQuizScope(item, scope) || item.quiz_id !== quizId)) throw new Error('历史记录与当前活动不匹配，未展示。')
      setHistory(value.attempts)
    }).catch(cause => { if (!controller.signal.aborted) setHistoryError(describeError(cause)) })
    return () => controller.abort()
  }, [quizId, snapshot?.version, historyRevision])

  function make(path: string, body: Record<string, unknown> = {}): QuizCommand {
    return { method: 'POST', path, body: { ...body, client_command_id: crypto.randomUUID() } }
  }
  function sendAnswer(options: string[], skipped: boolean) {
    const current = attempt.current.current
    if (locked || !current) return
    const question = current.quiz.questions[current.attempt.cursor]
    if (!question) return
    const next = answerCommand(current.attempt, question, options, skipped, crypto.randomUUID())
    if (!next) { setLocalError('无法读取有效的已保存计时起点或答案。请重新同步，不会提交空答案。'); return }
    setLocalError(null)
    void command.execute(next)
  }
  async function runAction(run: Run, action: 'cancel' | 'retry') {
    if (locked) return
    setReadingRun(true)
    setLocalError(null)
    try {
      const latest = await request<Run>(`/runs/${encodeURIComponent(run.run_id)}`)
      await command.execute(make(`/runs/${encodeURIComponent(run.run_id)}/${action}`, { expected_version: latest.version }))
    } catch (cause) { setLocalError(describeError(cause)) }
    finally { setReadingRun(false) }
  }
  function transition(action: 'next' | 'submit') {
    const current = attempt.current.current
    if (!current || locked || attemptTransition(current.attempt, current.quiz.questions.length) !== action) return
    void command.execute(make(`/attempts/${encodeURIComponent(current.attempt.attempt_id)}/${action}`, { expected_version: current.attempt.version }))
  }

  if (!snapshot) return <div className="page"><Link className="back-link" to={back}><IconChevronLeft size={15} />返回课程</Link>{target.error ? <ErrorNotice title="测验读取失败" message={target.error} retry={() => { void target.reload() }} /> : <Loading label="正在读取已保存题组…" />}</div>
  const generation = snapshot.generation_run
  const modelUnavailable = health.data?.model.configured === false
  const transitionType = liveAttempt ? attemptTransition(liveAttempt.attempt, liveAttempt.quiz.questions.length) : null

  return <div className="page quiz-page">
    <div className="run-page-top"><Link className="back-link" to={back}><IconChevronLeft size={15} />返回课程</Link><span className="connection-label">{target.connection}</span></div>
    <header className="page-heading"><div><span className="eyebrow">{targetType === 'practice' ? 'PRACTICE AFTER CLASS' : 'UNIT EXAM'}</span><h1>{snapshot.title}</h1><p>{snapshot.description}</p></div><span className="completion-label">{targetType === 'practice' ? (snapshot.completed ? <><IconCheck size={14} />课时已完成</> : '课时尚未完成') : (snapshot.completed ? <><IconCheck size={14} />考核已提交</> : '考核尚未提交')}</span></header>
    {target.error && <ErrorNotice title="活动同步失败" message={target.error} retry={() => { void target.reload() }} />}
    {!command.online && <ErrorNotice title="网络已断开" message="保留最后确认状态与原命令；联网不会自动出题、作答或提交。" />}
    {command.pending && <div className="pending-command" role="status"><div><b>{command.busy ? '正在保存，请稍候…' : '上次命令结果待确认'}</b><p>保留原方法、路径、请求体、用时和命令编号；不会自动重试或新建另一份请求。</p></div><button type="button" className="button secondary small" disabled={command.busy || !command.online} onClick={() => { void command.execute() }}>重试同一命令</button></div>}
    {(command.error || localError) && <div className="error-notice" role="alert"><div><b>操作尚未完成</b><p>{command.error || localError}</p></div>{command.rejected && <button type="button" className="button secondary small" onClick={command.releaseRejected}>解除已拒绝命令</button>}</div>}

    {!snapshot.quiz ? <section className="lesson-preparation">
      {modelUnavailable && <ErrorNotice title="模型尚未配置" message="请先在本地配置模型；不会假装题组已经生成。" />}
      {activeRun(generation) ? <><Loading label={generation?.status === 'generating' ? '正在生成题组…' : `题组${generation ? runLabels[generation.status] : '准备中'}…`} /><p>刷新只读取运行，不会重新出题。</p>{generation && <button type="button" className="button secondary" disabled={locked} onClick={() => { void runAction(generation, 'cancel') }}>取消出题</button>}</>
        : generation ? <EmptyState title={`出题${runLabels[generation.status]}`} action={generation.status !== 'ready' ? <button type="button" className="button primary" disabled={locked || modelUnavailable} onClick={() => { void runAction(generation, 'retry') }}>明确重试出题</button> : <button type="button" className="button secondary" onClick={() => { void target.reload() }}>重新读取题组</button>}>{generation.error?.message || '尚未读取到已保存题组。重试会调用模型，可能产生费用。'}</EmptyState>
          : <EmptyState title={targetType === 'practice' ? '准备本课练习' : '准备单元考核'} action={<button type="button" className="button primary" disabled={locked || modelUnavailable} onClick={() => { void command.execute(make(`${targetPath}/prepare`)) }}>准备题组</button>}>{targetType === 'practice' ? <>仅使用本课已有真实讲义。若还没有讲义，请先<Link to={`${back}/sessions/${encodeURIComponent(targetId)}`}>进入课堂准备讲义</Link>，这里不会自动生成讲义。</> : '基于所属单元的真实课时提纲、要点与已缓存讲义出题，不会先生成整单元讲义。'}<br />明确点击才调用模型，可能产生费用；题组保存后再次练习复用，不重新出题。</EmptyState>}
    </section> : <>
      <details className="quiz-sources aside-card"><summary>本题组实际来源 · {snapshot.quiz.source_refs.length} 项</summary><ul>{snapshot.quiz.source_refs.map(ref => <li key={ref}>{ref}</li>)}</ul></details>
      {selectedId ? attempt.error ? <ErrorNotice title="作答读取失败" message={attempt.error} retry={() => { void attempt.reload() }} /> : !liveAttempt || liveAttempt.attempt.attempt_id !== selectedId ? <Loading label="正在读取所选作答与持久题目起点…" /> : liveAttempt.attempt.status === 'submitted' ? <Results snapshot={liveAttempt} /> : <>
        <div className="section-heading"><h2>第 {liveAttempt.attempt.cursor + 1} / {liveAttempt.quiz.questions.length} 题</h2><span>已保存 {liveAttempt.attempt.answers.length} 题</span></div>
        <div className="quiz-progress" role="progressbar" aria-valuemin={0} aria-valuemax={liveAttempt.quiz.questions.length} aria-valuenow={liveAttempt.attempt.answers.length} aria-label="已保存作答进度">
          <div className="quiz-progress-track">{liveAttempt.quiz.questions.map((question, index) => <i key={question.question_id} className={index < liveAttempt.attempt.answers.length ? 'is-done' : index === liveAttempt.attempt.cursor ? 'is-current' : ''} />)}</div>
        </div>
        <AnswerCard key={`${liveAttempt.attempt.attempt_id}:${liveAttempt.attempt.cursor}`} snapshot={liveAttempt} locked={locked || !!attempt.error} send={sendAnswer} />
        {transitionType === 'next' && <div className="quiz-actions"><button type="button" className="button primary" disabled={locked || !!attempt.error} onClick={() => transition('next')}>下一题 <IconArrowRight size={13} /></button></div>}
        {transitionType === 'submit' && <div className="quiz-actions"><p className="form-hint">全部作答已保存。点击后提交结果并更新完成情况。</p><button type="button" className="button primary" disabled={locked || !!attempt.error} onClick={() => transition('submit')}>看结果 · 提交本次作答</button></div>}
      </> : <EmptyState title="题组已保存，准备好了吗？" action={<button type="button" className="button primary" disabled={locked} onClick={() => { void command.execute(make(`/quizzes/${encodeURIComponent(snapshot.quiz!.quiz_id)}/attempts`)) }}>开始作答</button>}>开始后才创建本次作答并记录第一题起点。进入或刷新页面不会创建尝试。</EmptyState>}
      {liveAttempt?.attempt.status === 'submitted' && <div className="quiz-actions"><button type="button" className="button primary" disabled={locked} onClick={() => { void command.execute(make(`/quizzes/${encodeURIComponent(snapshot.quiz!.quiz_id)}/attempts`)) }}>再练一次 · 复用本题组</button></div>}
      <section className="quiz-history aside-card"><div className="section-heading"><h2>作答历史</h2><span>旧结果不会被再练覆盖</span></div>{historyError ? <ErrorNotice title="历史记录读取失败" message={historyError} retry={() => setHistoryRevision(revision => revision + 1)} /> : history.length ? <ul>{history.map(item => <li key={item.attempt_id}><div><b>{item.status === 'submitted' ? '已提交结果' : '进行中的作答'}</b><small>{dateLabel(item.created_at)}{item.result ? ` · ${item.result.total_score} 分` : ` · 已保存 ${item.answers.length} 题`}</small></div><button type="button" className="button secondary small" disabled={locked || item.attempt_id === selectedId} onClick={() => selectAttempt(item.attempt_id)}>{item.attempt_id === selectedId ? '当前记录' : item.status === 'submitted' ? '查看历史结果' : '继续本次作答'}</button></li>)}</ul> : <p className="aside-note">还没有保存的作答记录。</p>}</section>
    </>}
  </div>
}

export default function QuizPage() {
  const { courseId = '', sessionId, examId } = useParams()
  const targetType = sessionId ? 'practice' : 'exam'
  const targetId = sessionId || examId || ''
  return <TargetQuiz key={`${courseId}:${targetType}:${targetId}`} courseId={courseId} targetType={targetType} targetId={targetId} />
}
