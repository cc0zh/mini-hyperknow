import type { Research } from '../lib/types'
import { dateLabel } from './ui'

// Saved activity only: opening a source or disclosure never starts a model/tool request.
export function RunResearch({ research }: { research: Research | null | undefined }) {
  const failed = research?.steps.filter(step => step.status === 'failed').length ?? 0
  return <section className="run-research" aria-labelledby="research-title">
    <div className="section-heading"><h2 id="research-title">参考资料</h2><span>{research?.sources.length ?? 0} 篇已读取</span></div>
    <p className="wb-research-summary">{research?.report ? '调研已完成，课程规划将参考已读取的资料。' : research?.steps.length ? '正在收集资料，以下是已经保存的结果。' : '取得参考资料后，会显示在这里。'}</p>
    {failed > 0 && <p className="wb-source-warning">{failed} 次网页请求未完成，未作为已读资料。具体缺口见下方调研详情。</p>}
    {!!research?.report?.limitations.length && <details className="wb-source-limits"><summary>资料范围与限制 · {research.report.limitations.length} 项</summary><ul>{research.report.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></details>}
    <details className="wb-research-disclosure"><summary>查看调研过程与结论 <span>{research?.steps.length ?? 0} 条记录</span></summary>
    <h3>搜索与阅读活动</h3>
    {!research?.steps.length ? <p className="inline-note">尚无已保存的搜索或阅读记录。这里不展示模拟活动。</p> : <ol className="research-steps">{research.steps.map((step, index) => <li key={index}><span className="kind-label">{step.tool === 'web_search' ? '网页搜索' : '网页阅读'}</span><span className={`research-step-status ${step.status}`}>{step.status === 'ready' ? '已完成' : '失败'}</span><p>{step.arguments.query ?? step.arguments.url}</p>{step.error && <p className="research-error">{step.error.code} · {step.error.message}</p>}</li>)}</ol>}
    {research?.report && <section className="research-report"><h3>调研结论</h3><p>{research.report.summary}</p>{research.report.findings.map((finding, index) => <div key={index}><h4>{finding.title}</h4><p>{finding.summary}</p><div className="finding-sources">{finding.source_ids.map(id => <a key={id} href={`#source-${encodeURIComponent(id)}`} onClick={() => { const source = document.getElementById(`source-${encodeURIComponent(id)}`); if (source instanceof HTMLDetailsElement) source.open = true }}>来源 {id}</a>)}</div></div>)}{!!research.report.suggested_sequence.length && <><h4>建议学习顺序</h4><ol>{research.report.suggested_sequence.map((item, i) => <li key={i}>{item}</li>)}</ol></>}</section>}
    <div className="section-heading"><h2>已保存资料</h2><span>{research?.sources.length ?? 0} 篇</span></div>
    {!research?.sources.length ? <p className="inline-note">尚未保存网页资料。已抓取正文将随真实调研结果显示。</p> : <div className="research-sources">{research.sources.map(source => <details className="research-source" id={`source-${encodeURIComponent(source.source_id)}`} key={source.source_id}><summary>{source.title || source.url}</summary><a href={source.url} target="_blank" rel="noreferrer">打开原网页 ↗</a><p className="source-meta">{source.source_id} · {dateLabel(source.fetched_at)}{source.truncated ? ' · 正文已截断' : ''}</p><p className="source-text">{source.text}</p><small className="source-hash">SHA-256 · {source.content_sha256}</small></details>)}</div>}
    </details>
  </section>
}
