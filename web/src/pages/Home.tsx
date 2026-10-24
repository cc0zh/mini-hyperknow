import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Arrow, ErrorNotice, useHealth } from '../components/ui'
import { IconArrowRight, IconBook, IconCheck, IconSpark } from '../components/icons'
import { useCommand } from '../lib/use-command'
import { readPending } from '../lib/commands'
import { useResource } from '../lib/use-resource'
import { nextLearningPath } from '../lib/quiz-state'
import type { Course } from '../lib/types'
import type { Run } from '../lib/types'

export default function Home() {
  const navigate = useNavigate()
  const health = useHealth()
  // Deliberately not the .course-card component: the library owns that class,
  // and /courses asserts its card count against the real API.
  const library = useResource<{ courses: Course[] }>('/courses')
  const recent = (library.data?.courses ?? []).slice(0, 3)
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
      <h1>让一个学习目标，<br />长成你的<span className="brush">专属课程</span><span className="heading-dot">。</span></h1>
      <p className="home-subtitle">告诉 Hyperknow 你想学什么。一起厘清方向，<br />把零散的好奇，整理成循序渐进的学习路径。</p>
      <form className="goal-composer" onSubmit={submit}>
        <label htmlFor="learning-goal"><IconSpark size={16} />你想探索什么？</label>
        <textarea id="learning-goal" placeholder="例如：我想理解线性代数，能从几何直觉看懂矩阵与线性变换。" rows={4} minLength={2} maxLength={4000} value={goal} onChange={event => setGoal(event.target.value)} disabled={command.busy || !!command.pending} />
        <div className="composer-bottom"><span className="composer-hint"><IconBook size={15} /> 从你的目标出发，其余交给课堂</span><button className="button primary" disabled={(!command.pending && (goal.trim().length < 2 || goal.trim().length > 4000)) || command.busy} type="submit">{command.busy ? '正在提交…' : command.pending ? '重试同一请求' : '打造课程'}<IconArrowRight size={16} /></button></div>
      </form>
      {command.error && <ErrorNotice message={command.error} title="创建请求未确认" />}
      {command.rejected && <button className="text-button" type="button" onClick={command.releaseRejected}>修改目标后重新提交</button>}
      {command.pending && !command.busy && <p className="inline-note" role="status">保留了上次请求的内容与编号。重试不会创建一份重复课程。</p>}
      {health.error ? <ErrorNotice message={health.error} title="无法连接本地后端" retry={health.reload} /> : health.data?.model.configured === false ? <div className="configuration-note" role="status"><b>模型尚未配置</b><p>请在后端配置真实模型服务。当前无法生成课程，不会使用示例课程或模拟内容代替。</p><button className="text-button" type="button" onClick={health.reload}>重新检查服务</button></div> : health.data ? <p className="model-note">后端模型：{health.data.model.name || '未返回名称'} <span>· 已配置，尚未验证本次调用</span></p> : null}
      <div className="home-steps" aria-label="课程创建流程"><div><span>01</span><b>说出目标</b><p>主题、基础与期望，从一段文字开始。</p></div><div><span>02</span><b>澄清与调研</b><p>补充学习方向，结合真实网页资料规划。</p></div><div><span>03</span><b>确认蓝图</b><p>审阅整门课程方向，批准后自动逐单元展开。</p></div></div>
      <div className="home-library-link">已经有自己的课程？<Link to="/courses">打开我的课程 <Arrow /></Link></div>
      {recent.length > 0 && <section className="home-recent" aria-label="最近课程">
        <div className="home-recent-heading"><span>继续上次的进度</span><Link to="/courses">全部课程 <IconArrowRight size={13} /></Link></div>
        <ul>{recent.map(course => {
          const next = nextLearningPath(course) ?? `/courses/${encodeURIComponent(course.course_id)}`
          return <li key={course.course_id}><Link to={next}>
            <span className="home-recent-title">{course.title}</span>
            <span className="home-recent-next">{course.next_item?.title ?? `${course.unit_count} 个单元 · ${course.session_count} 课时`}</span>
            <span className="home-recent-go"><IconCheck size={14} /></span>
          </Link></li>
        })}</ul>
      </section>}
    </div>
  </div>
}
