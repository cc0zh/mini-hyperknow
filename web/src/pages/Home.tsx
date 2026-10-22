import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Arrow, ErrorNotice, useHealth } from '../components/ui'
import { useCommand } from '../lib/use-command'
import { readPending } from '../lib/commands'
import type { Run } from '../lib/types'

export default function Home() {
  const navigate = useNavigate()
  const health = useHealth()
  const [goal, setGoal] = useState(() => String(readPending('create')?.body.goal ?? ''))
  const command = useCommand<Run>('create', run => navigate(`/course-runs/${encodeURIComponent(run.run_id)}`))
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if ((!command.pending && (goal.trim().length < 2 || goal.trim().length > 4000)) || command.busy) return
    void command.execute('/course-runs', { goal: goal.trim() })
  }

  return <div className="home-page">
    <div className="home-grid" aria-hidden="true" />
    <div className="home-content">
      <div className="welcome-label"><span />好奇心，是最好的起点</div>
      <h1>让一个学习目标，<br />长成你的<span className="brush">专属课程</span>。</h1>
      <p className="home-subtitle">告诉 Hyperknow 你想学什么。一起厘清方向，<br />把零散的好奇，整理成循序渐进的学习路径。</p>
      <form className="goal-composer" onSubmit={submit}>
        <label htmlFor="learning-goal">你想探索什么？</label>
        <textarea id="learning-goal" placeholder="例如：我想理解线性代数，能从几何直觉看懂矩阵与线性变换。" rows={4} minLength={2} maxLength={4000} value={goal} onChange={event => setGoal(event.target.value)} disabled={command.busy || !!command.pending} />
        <div className="composer-bottom"><span><span aria-hidden="true">✦</span> 从你的目标出发</span><button className="button primary" disabled={(!command.pending && (goal.trim().length < 2 || goal.trim().length > 4000)) || command.busy} type="submit">{command.busy ? '正在提交…' : command.pending ? '重试同一请求' : '打造课程'}<Arrow /></button></div>
      </form>
      {command.error && <ErrorNotice message={command.error} title="创建请求未确认" />}
      {command.rejected && <button className="text-button" type="button" onClick={command.releaseRejected}>修改目标后重新提交</button>}
      {command.pending && !command.busy && <p className="inline-note" role="status">保留了上次请求的内容与编号。重试不会创建一份重复课程。</p>}
      {health.error ? <ErrorNotice message={health.error} title="无法连接本地后端" retry={health.reload} /> : health.data?.model.configured === false ? <div className="configuration-note" role="status"><b>模型尚未配置</b><p>请在后端配置真实模型服务。当前无法生成课程，不会使用示例课程或模拟内容代替。</p><button className="text-button" type="button" onClick={health.reload}>重新检查服务</button></div> : health.data ? <p className="model-note">后端模型：{health.data.model.name || '未返回名称'} <span>· 已配置，尚未验证本次调用</span></p> : null}
      <div className="home-steps" aria-label="课程创建流程"><div><span>01</span><b>说出目标</b><p>主题、基础与期望，<br />从一段文字开始。</p></div><div><span>02</span><b>一起澄清</b><p>补充适合你的方向，<br />也可以选择跳过。</p></div><div><span>03</span><b>展开路径</b><p>浏览单元、课时与考核，<br />看见知识的完整结构。</p></div></div>
      <div className="home-library-link">已经有自己的课程？<Link to="/courses">打开我的课程 <Arrow /></Link></div>
    </div>
  </div>
}
