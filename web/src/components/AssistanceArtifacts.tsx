import { useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Mermaid } from './Board'
import { SafeText } from './Board'
import { ErrorNotice } from './ui'
import { AssistanceText } from './AssistanceTurns'
import { artifactLabels, boardArtifactPath, quizAnswerCorrect, selectQuizOption } from '../lib/assistance'
import type { AssistanceArtifact } from '../lib/assistance'
import { animationSrcDoc, ANIMATION_SANDBOX } from '../lib/assistance-animation'
import { useBoardFont } from '../lib/use-board-font'

function Flashcards({ artifact }: { artifact: Extract<AssistanceArtifact, { kind: 'flashcards' }> }) {
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const cards = artifact.data.cards
  const change = (next: number) => { setIndex(Math.max(0, Math.min(cards.length - 1, next))); setFlipped(false) }
  const key = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); change(index + (event.key === 'ArrowLeft' ? -1 : 1)) }
    // Space/Enter use the native flip button, scoped to this card. Multiple
    // artifacts must not share a global keyboard listener.
  }
  const card = cards[index]
  return <section className="artifact-pane flashcard-pane" aria-label="闪卡" onKeyDown={key}>
    <div className="artifact-heading"><h2>{artifact.title}</h2><span>{index + 1} / {cards.length}</span></div>
    <button type="button" className={`flashcard${flipped ? ' flipped' : ''}`} onClick={() => setFlipped(value => !value)} aria-label={flipped ? '显示问题' : '翻转显示答案'} aria-pressed={flipped}>
      <span className="eyebrow">{flipped ? '答案' : '问题'}</span>{flipped ? <span className="flashcard-answer"><AssistanceText text={card.answer} /></span> : <span>{card.question}</span>}<small>点击或按空格翻面，← → 切换</small>
    </button>
    <div className="artifact-controls"><button className="button secondary" type="button" disabled={index === 0} onClick={() => change(index - 1)}>上一张</button><button className="button secondary" type="button" disabled={index === cards.length - 1} onClick={() => change(index + 1)}>下一张</button></div>
  </section>
}

function Quiz({ artifact }: { artifact: Extract<AssistanceArtifact, { kind: 'quiz' }> }) {
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<string[]>([])
  const [submitted, setSubmitted] = useState(false)
  const question = artifact.data.questions[index]
  const multiple = question.correct_ids.length > 1
  const change = (next: number) => { setIndex(next); setAnswers([]); setSubmitted(false) }
  return <section className="artifact-pane quiz-pane" aria-label="即时测验">
    <div className="artifact-heading"><h2>{artifact.title}</h2><span>{index + 1} / {artifact.data.questions.length}</span></div>
    <h3><AssistanceText text={question.question} /></h3><fieldset disabled={submitted}><legend>{multiple ? '选择所有正确答案' : '选择一个答案'}</legend>
      {question.options.map(option => <label className={`answer-option${answers.includes(option.id) ? ' selected' : ''}`} key={option.id}>
        <input type={multiple ? 'checkbox' : 'radio'} name={`assistance-${artifact.artifact_id}-${question.question_id}`} checked={answers.includes(option.id)} onChange={() => setAnswers(previous => selectQuizOption(previous, option.id, question.correct_ids))} /><span><AssistanceText text={option.text} /></span>{submitted && question.correct_ids.includes(option.id) && <b>正确</b>}
      </label>)}
    </fieldset>
    {submitted ? <div className={`quiz-feedback ${quizAnswerCorrect(answers, question.correct_ids) ? 'correct' : 'incorrect'}`} role="status"><b>{quizAnswerCorrect(answers, question.correct_ids) ? '回答正确' : '再看一下'}</b><p><SafeText text={question.explanation} /></p></div> : <button className="button primary" type="button" disabled={!answers.length} onClick={() => setSubmitted(true)}>提交答案</button>}
    <div className="artifact-controls"><button className="button secondary" type="button" disabled={index === 0} onClick={() => change(index - 1)}>上一题</button><button className="button secondary" type="button" disabled={index === artifact.data.questions.length - 1} onClick={() => change(index + 1)}>下一题</button></div>
    <p className="inline-note">作答仅保留在本页；切题清空，不保存成绩。</p>
  </section>
}

function Animation({ artifact }: { artifact: Extract<AssistanceArtifact, { kind: 'animation' }> }) {
  const [reset, setReset] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const preview = useMemo(() => {
    try { return { srcDoc: animationSrcDoc(artifact.data.html), error: null } }
    catch (cause) { return { srcDoc: '', error: cause instanceof Error ? cause.message : '动画预览无法构建。' } }
  }, [artifact.data.html, reset])
  return <section className={`artifact-pane animation-pane${expanded ? ' expanded' : ''}`} aria-label="动画预览" onKeyDown={event => { if (event.key === 'Escape') setExpanded(false) }}>
    <div className="artifact-heading"><h2>{artifact.title}</h2><div className="animation-actions"><button className="button secondary small" type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>{expanded ? '收起预览' : '展开预览'}</button><button className="button secondary small" type="button" onClick={() => { setLoadError(false); setReset(value => value + 1) }}>重置动画</button></div></div>
    <p className="animation-notice">不可信教学预览 · 请勿输入敏感信息。脚本与宿主隔离、禁止第三方子资源；不保证任意脚本的预览内部导航或资源占用。重置会清空动画内部状态。</p>
    {preview.error || loadError ? <ErrorNotice title="动画预览已停止" message={preview.error || '预览无法加载，请尝试重置动画。'} /> : <iframe key={reset} title={artifact.title} sandbox={ANIMATION_SANDBOX} referrerPolicy="no-referrer" srcDoc={preview.srcDoc} onError={() => setLoadError(true)} />}
  </section>
}

function Diagram({ artifact }: { artifact: Extract<AssistanceArtifact, { kind: 'diagram' }> }) {
  const font = useBoardFont()
  return <section className="artifact-pane diagram-pane" aria-label="结构图">
    <div className="artifact-heading"><h2>{artifact.title}</h2></div>
    <Mermaid content={artifact.data.source} fontReady={font.state === 'ready'} />
    {font.state === 'error' && <p className="animation-notice">手写字体未加载；结构图等待字体就绪后绘制，未用源码替代。</p>}
    {artifact.data.caption && <p className="diagram-caption"><SafeText text={artifact.data.caption} /></p>}
  </section>
}

// The durable identity of a generated artifact: what it is, copied from the
// saved content, and one verdict. Feedback lives here rather than on the
// message because the artifact is what a learner judges.
function ArtifactHeader({ artifact, onVote }: { artifact: AssistanceArtifact; onVote?: (vote: 'up' | 'down') => void }) {
  const [copied, setCopied] = useState(false)
  const plain = artifact.kind === 'diagram' ? artifact.data.source : ''
  return <div className="artifact-identity">
    <span className="eyebrow">生成 {artifactLabels[artifact.kind]} ✓</span>
    {plain && <button type="button" className="text-button" onClick={() => { void navigator.clipboard?.writeText(plain).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500) }, () => undefined) }}>{copied ? '已复制' : '复制源码'}</button>}
    {onVote && <div className="artifact-votes"><button type="button" className={`text-button${artifact.feedback === 'up' ? ' voted' : ''}`} aria-pressed={artifact.feedback === 'up'} aria-label="这个产物有用" onClick={() => onVote('up')}>有用</button><button type="button" className={`text-button${artifact.feedback === 'down' ? ' voted' : ''}`} aria-pressed={artifact.feedback === 'down'} aria-label="这个产物没帮助" onClick={() => onVote('down')}>没帮助</button></div>}
  </div>
}

export function AssistanceArtifactView({ artifact, onVote }: { artifact: AssistanceArtifact; onVote?: (vote: 'up' | 'down') => void }) {
  const body = artifact.kind === 'flashcards' ? <Flashcards artifact={artifact} />
    : artifact.kind === 'quiz' ? <Quiz artifact={artifact} />
    : artifact.kind === 'animation' ? <Animation artifact={artifact} />
    : artifact.kind === 'diagram' ? <Diagram artifact={artifact} />
    : <section className="artifact-pane assistance-board-summary"><p>{artifact.data.steps.length} 步板书 · 已确认展示 {artifact.data.cursor + 1} 步</p><Link className="button secondary" to={boardArtifactPath(artifact.artifact_id)}>打开独立白板</Link></section>
  // The saved artifact identity is exposed so a page with several artifacts of
  // the same kind stays addressable without guessing from visible text.
  return <div className="assistance-artifact" data-artifact-id={artifact.artifact_id}><ArtifactHeader artifact={artifact} onVote={onVote} />{body}</div>
}
