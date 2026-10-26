import { useEffect, useId, useRef, useState } from 'react'
import katex from 'katex'
import { SafeText } from './Board'
import { AssistanceArtifactView } from './AssistanceArtifacts'
import { assistanceLabels, assistanceStatusLabels, assistanceStepLabel, clarificationText, planProgressPercent } from '../lib/assistance'
import type { AssistanceConversation, AssistanceQuestion, AssistanceRun, AssistanceStep, AssistanceSuggestion } from '../lib/assistance'

function Formula({ text, display = true }: { text: string; display?: boolean }) {
  const target = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    setError(false)
    try { if (target.current) katex.render(text, target.current, { displayMode: display, throwOnError: true, trust: false, strict: 'error', maxExpand: 500, maxSize: 20 }) }
    catch { setError(true) }
  }, [text, display])
  if (error) return display ? <pre className="assistance-math-error" role="alert">公式排版失败：{text}</pre> : <span>{text}</span>
  return <span className={display ? 'assistance-formula' : 'assistance-math-inline'} ref={target} />
}

// Inline math only when the delimiters hug their content, so ordinary prose
// such as "$5 和 $10" is not mistaken for a formula. Emphasis is limited to
// **bold**, which is the only marker the teaching prompt produces.
function withInlineMath(part: string, keyPrefix: string) {
  const pieces = part.split(/(\*\*[^*\n]+\*\*|\$[^\s$][^$\n]*?\$)/g)
  return pieces.map((piece, index) => {
    const key = `${keyPrefix}-${index}`
    if (piece.startsWith('**') && piece.endsWith('**') && piece.length > 4) return <strong key={key}>{piece.slice(2, -2)}</strong>
    if (piece.startsWith('$') && piece.endsWith('$') && piece.length > 2) return <Formula key={key} text={piece.slice(1, -1)} display={false} />
    return <SafeText key={key} text={piece} />
  })
}

export function AssistanceText({ text }: { text: string }) {
  // Model HTML stays ordinary escaped text. Only code fences, explicit $$
  // display formulas and four closed callout kinds have special renderers;
  // KaTeX never receives trust=true.
  const blocks = text.split(/(```[\s\S]*?```|\$\$[\s\S]*?\$\$|^:::(?:definition|example|warning|note)[ \t]*$[\s\S]*?^:::[ \t]*$)/gm)
  return <div className="safe-prose assistance-prose">{blocks.map((part, index) => {
    if (part.startsWith('```')) return <pre key={index}><code>{part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '')}</code></pre>
    if (part.startsWith('$$')) return <Formula key={index} text={part.slice(2, -2).trim()} />
    const callout = /^:::(definition|example|warning|note)[ \t]*\n([\s\S]*?)\n?:::[ \t]*$/.exec(part)
    if (callout) return <Callout key={index} kind={callout[1] as CalloutKind} text={callout[2] || ''} />
    return <span key={index}>{withInlineMath(part, String(index))}</span>
  })}</div>
}

type CalloutKind = 'definition' | 'example' | 'warning' | 'note'
const calloutLabels: Record<CalloutKind, string> = { definition: '定义', example: '例子', warning: '注意', note: '补充' }

function Callout({ kind, text }: { kind: CalloutKind; text: string }) {
  return <aside className={`assistance-callout callout-${kind}`}><span className="callout-label">{calloutLabels[kind]}</span><AssistanceText text={text.trim()} /></aside>
}

function TraceList({ steps, running }: { steps: AssistanceStep[]; running: boolean }) {
  return <ol className="assistance-timeline" aria-label="教学执行过程">
    {steps.map((step, index) => <li key={`${step.tool}-${index}-${step.name ?? step.title ?? ''}`} className={step.status === 'ready' ? 'done' : 'active'}>
      <span className="timeline-mark" aria-hidden="true">{step.status === 'ready' ? '✓' : '…'}</span>
      <span>{step.title ? `${assistanceStepLabel(step)} · ${step.title}` : assistanceStepLabel(step)}</span>
    </li>)}
    {running && <li className="active"><span className="timeline-mark" aria-hidden="true">…</span><span>整理教学回复</span></li>}
  </ol>
}

// Render the recorded teaching-agent trace while a turn is generating so the
// wait is legible: skill load and artifact creation each resolve to a tick.
export function AssistanceTimeline({ run }: { run: AssistanceRun }) {
  const steps = run.steps ?? []
  return <TraceList steps={steps} running />
}

// The same trace stays on a finished turn. The reply is legible as the steps
// that produced it instead of one opaque block, and it costs no new request:
// the steps were already persisted with the run.
function SavedTrace({ steps }: { steps: AssistanceStep[] }) {
  if (!steps.length) return null
  return <details className="assistance-trace"><summary>{steps.length} 步执行过程</summary><TraceList steps={steps} running={false} /></details>
}

// Lightweight progress bar for a multi-step teaching plan, driven only by the
// already-saved plan/current_step fields.
export function AssistancePlanProgress({ plan, current }: { plan: string[]; current: number }) {
  if (plan.length < 2) return null
  const percent = planProgressPercent(current, plan.length)
  const step = plan[Math.min(Math.max(current, 0), plan.length - 1)]
  return <div className="assistance-plan-progress">
    <div className="plan-progress-head"><span>{step}</span><span className="plan-progress-count">{Math.min(current + 1, plan.length)} / {plan.length} · {percent}%</span></div>
    <div className="plan-progress-track"><div className="plan-progress-fill" style={{ width: `${percent}%` }} /></div>
  </div>
}

function Clarification({ questions, disabled, onAnswer }: { questions: AssistanceQuestion[]; disabled: boolean; onAnswer: (text: string) => Promise<boolean> }) {
  const prefix = useId()
  const [selected, setSelected] = useState<Record<string, string[]>>({})
  const [custom, setCustom] = useState('')
  const answer = clarificationText(questions, selected, custom)
  const complete = questions.every(question => (selected[question.question_id]?.length ?? 0) > 0) || !!custom.trim()
  return <form className="clarification" onSubmit={event => { event.preventDefault(); if (!disabled && complete) void onAnswer(answer) }}>
    <b>需要补充的信息</b>
    {questions.map(question => <fieldset key={question.question_id} disabled={disabled}><legend><AssistanceText text={question.question} /></legend>{question.options.map(option => <label className="answer-option" key={option}><input type={question.multiple ? 'checkbox' : 'radio'} name={`${prefix}-${question.question_id}`} checked={selected[question.question_id]?.includes(option) ?? false} onChange={() => setSelected(previous => {
      const values = previous[question.question_id] ?? []
      return { ...previous, [question.question_id]: question.multiple ? values.includes(option) ? values.filter(value => value !== option) : [...values, option] : [option] }
    })} /><span><AssistanceText text={option} /></span></label>)}</fieldset>)}
    <label className="custom-answer" htmlFor={`${prefix}-custom`}>其他补充或直接回答<textarea id={`${prefix}-custom`} value={custom} onChange={event => setCustom(event.target.value)} disabled={disabled} maxLength={12000} /></label>
    <div className="clarification-actions"><button type="submit" className="button primary small" disabled={disabled || !complete || answer.length > 12000}>发送补充</button><button type="button" className="text-button" disabled={disabled} onClick={() => { if (!disabled) void onAnswer('跳过，请直接按你的判断开始讲解') }}>跳过，直接开始</button></div>
  </form>
}

// Suggestions carry an explicit turn intent; their wording never decides
// whether to advance the saved plan or send an ordinary teaching message.
function Suggestions({ suggestions, disabled, onSuggest }: { suggestions: AssistanceSuggestion[]; disabled: boolean; onSuggest: (suggestion: AssistanceSuggestion) => void }) {
  return <div className="assistance-suggestions" aria-label="下一步建议">
    <span className="eyebrow">下一步</span>
    <div className="suggestion-list">{suggestions.map((suggestion, index) => <button key={`${index}-${suggestion.label}`} type="button" className="suggestion-chip" disabled={disabled} onClick={() => onSuggest(suggestion)}>{suggestion.label}</button>)}</div>
  </div>
}

export function AssistanceTurns({ conversation, blocked, onAnswer, onRetry, onSuggest, onVote, compact = false }: {
  conversation: AssistanceConversation
  blocked: boolean
  onAnswer: (text: string) => Promise<boolean>
  onRetry: (runId: string) => void
  onSuggest?: (suggestion: AssistanceSuggestion) => void
  onVote?: (artifactId: string, vote: 'up' | 'down') => void
  compact?: boolean
}) {
  return <div className="assistance-turns">{conversation.turns.map((turn, index) => {
    const latest = index === conversation.turns.length - 1
    return <article className="assistance-turn" key={turn.turn_id}>
      <div className="turn-user"><span>你 · {assistanceLabels[turn.action]}</span><p><SafeText text={turn.user_text || (turn.action === 'continue' ? '继续' : '按当前会话生成')} /></p></div>
      <div className="turn-assistant"><div className="turn-status"><b>协助</b><span>{assistanceStatusLabels[turn.status]}</span></div>
        <SavedTrace steps={turn.steps ?? []} />
        {turn.response && <><AssistanceText text={turn.response.text} />
          {turn.response.questions.length > 0 && (latest ? <Clarification key={turn.turn_id} questions={turn.response.questions} disabled={blocked} onAnswer={onAnswer} /> : <ul className="previous-clarification">{turn.response.questions.map(question => <li key={question.question_id}><AssistanceText text={question.question} /></li>)}</ul>)}
          {turn.response.plan.length > 0 && <><AssistancePlanProgress plan={turn.response.plan} current={turn.response.current_step} /><ol className="assistance-plan">{turn.response.plan.map((step, i) => <li className={i === turn.response!.current_step ? 'current' : ''} key={`${i}-${step}`}>{step}</li>)}</ol></>}
        </>}
        {turn.error && <p role="alert" className="assistance-turn-error">{turn.error.message}</p>}
        {turn.skill_uses.length > 0 && <details className="skill-uses"><summary>本轮使用的 Skill</summary><ul>{turn.skill_uses.map(item => <li key={`${item.name}-${item.sha256}`} title={`SHA-256: ${item.sha256}`}>{item.name} · {item.version}</li>)}</ul></details>}
        {!compact && turn.artifacts.map(artifact => <AssistanceArtifactView key={artifact.artifact_id} artifact={artifact} onVote={onVote && (vote => onVote(artifact.artifact_id, vote))} />)}
        {latest && !compact && turn.status === 'ready' && onSuggest && (turn.response?.suggestions?.length ?? 0) > 0 && <Suggestions suggestions={turn.response!.suggestions!} disabled={blocked} onSuggest={onSuggest} />}
        {['failed', 'interrupted', 'cancelled'].includes(turn.status) && <button type="button" className="text-button" disabled={blocked || !latest} onClick={() => onRetry(turn.run_id)}>明确重试本轮</button>}
      </div>
    </article>
  })}</div>
}
