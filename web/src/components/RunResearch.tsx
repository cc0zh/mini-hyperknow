import type { Research } from '../lib/types'
import { dateLabel } from './ui'

// Saved activity only: opening a source or disclosure never starts a model/tool request.
export function RunResearch({ research }: { research: Research | null | undefined }) {
  return <section className="run-research" aria-labelledby="research-title">
    <div className="section-heading"><h2 id="research-title">搜索与阅读活动</h2><span>{research?.steps.length ?? 0} 条已保存</span></div>
    {!research?.steps.length ? <p className="inline-note">尚无已保存的搜索或阅读记录。这里不展示模拟活动。</p> : <ol className="research-steps">{research.steps.map((step, index) => <li key={index}><span className="kind-label">{step.tool === 'web_search' ? '网页搜索' : '网页阅读'}</span><span className={`research-step-status ${step.status}`}>{step.status === 'ready' ? '已完成' : '失败'}</span><p>{step.arguments.query ?? step.arguments.url}</p>{step.error && <p className="research-error">{step.error.code} · {step.error.message}</p>}</li>)}</ol>}
    {research?.report && <section className="research-report"><h3>调研结论</h3><p>{research.report.summary}</p>{research.report.findings.map((finding, index) => <div key={index}><h4>{finding.title}</h4><p>{finding.summary}</p><div className="finding-sources">{finding.source_ids.map(id => <a key={id} href={`#source-${encodeURIComponent(id)}`}>来源 {id}</a>)}</div></div>)}{!!research.report.suggested_sequence.length && <><h4>建议学习顺序</h4><ol>{research.report.suggested_sequence.map((item, i) => <li key={i}>{item}</li>)}</ol></>}{!!research.report.limitations.length && <><h4>调研局限</h4><ul>{research.report.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></>}</section>}
    <div className="section-heading"><h2>已保存资料</h2><span>{research?.sources.length ?? 0} 篇</span></div>
    {!research?.sources.length ? <p className="inline-note">尚未保存网页资料。已抓取正文将随真实调研结果显示。</p> : <div className="research-sources">{research.sources.map(source => <details className="research-source" id={`source-${encodeURIComponent(source.source_id)}`} key={source.source_id}><summary>{source.title || source.url}</summary><a href={source.url} target="_blank" rel="noreferrer">打开原网页 ↗</a><p className="source-meta">{source.source_id} · {dateLabel(source.fetched_at)}{source.truncated ? ' · 正文已截断' : ''}</p><p className="source-text">{source.text}</p><small className="source-hash">SHA-256 · {source.content_sha256}</small></details>)}</div>}
  </section>
}
