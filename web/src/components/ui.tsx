import { createContext, useContext, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useResource } from '../lib/use-resource'
import type { Course, Health } from '../lib/types'
import { progressLabel } from '../lib/format'
import { courseProgress, structurePending } from '../lib/course-state'

const HealthContext = createContext<ReturnType<typeof useResource<Health>> | null>(null)
export const useHealth = () => useContext(HealthContext)!

export function Mark({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true">
    <svg viewBox="0 0 32 32" fill="none"><path d="M5 7v18M27 7v18M5 16h22M11 5v22M21 5v22" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /></svg>
  </span>
}

export function Arrow() { return <span aria-hidden="true">↗</span> }

export function Shell() {
  const health = useResource<Health>('/health')
  const { pathname } = useLocation()
  const isCreation = /^\/course-runs\/[^/]+\/?$/.test(pathname)
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return <HealthContext.Provider value={health}>
    <a className="skip-link" href="#main">跳到主要内容</a>
    <div className={`app-shell${isCreation ? ' creation-shell' : ''}`}>
      {!isCreation && <>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="Hyperknow 首页"><Mark /><span>Hyperknow<small>让知识，成为你的。</small></span></Link>
        <div className="sidebar-label">我的学习空间</div>
        <nav aria-label="主导航">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span aria-hidden="true">⌂</span>首页</NavLink>
          <NavLink to="/courses" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span aria-hidden="true">▤</span>我的课程</NavLink>
        </nav>
        <div className="sidebar-note"><span className="note-line" /><p>每一个问题，<br />都可以是一段学习的开始。</p></div>
        <div className="sidebar-footer"><span className="avatar">我</span><div><b>个人学习空间</b><small>本地 · 单用户</small></div></div>
      </aside></>}
      <div className="workspace">
        {!isCreation && <header className="topbar"><span>LEARN SOMETHING THAT MATTERS</span><div className={`service-pill ${health.error || health.data?.model.configured === false ? 'warning' : ''}`}>
          <i aria-hidden="true" />{health.loading ? '正在连接本地服务' : health.error ? '本地服务不可用' : health.data?.model.configured ? '本地服务已连接' : '模型尚未配置'}
        </div></header>}
        <main id="main" tabIndex={-1}><Outlet /></main>
        {!isCreation && <footer className="page-footer">Hyperknow <span>·</span> 从好奇开始，循路径深入</footer>}
      </div>
    </div>
  </HealthContext.Provider>
}

export function Loading({ label = '正在加载…' }: { label?: string }) {
  return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{label}</div>
}

export function ErrorNotice({ message, retry, title = '暂时无法完成' }: { message: string; retry?: () => void; title?: string }) {
  return <div className="error-notice" role="alert"><div><b>{title}</b><p>{message}</p></div>{retry && <button type="button" className="button secondary small" onClick={retry}>重新加载</button>}</div>
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon" aria-hidden="true">▤</span><h2>{title}</h2><p>{children}</p>{action}</div>
}

export const difficultyLabels = { beginner: '入门', intermediate: '中级', advanced: '进阶' }
export const dateLabel = (date: string) => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(date))

export function CourseProgress({ course }: { course: Course }) {
  const progress = courseProgress(course)
  return <><div className="progress-label"><span>课时进度</span><b>{progressLabel(progress)}</b></div>{progress === null ? <><div className="progress-incomplete" aria-hidden="true" /><p className="aside-note">目录尚未完整，暂不计算整门课程进度。</p></> : <><progress value={progress} max={100} aria-label={`${course.title}课时进度`} /><p className="aside-note">按服务端保存的已完成课时计算，不代表掌握度；考核不计入课时比例。</p></>}</>
}

export function CourseCard({ course, index = 0 }: { course: Course; index?: number }) {
  return <Link className={`course-card tone-${index % 3}`} to={`/courses/${encodeURIComponent(course.course_id)}`}>
    <div className="ticket-cover"><div className="cover-top"><Mark small /><span>{course.tags[0] || '学科未标注'}</span></div><div className="cover-title">{course.title}</div><span className="cover-motif" aria-hidden="true">✳</span></div>
    <div className="ticket-body"><span className="eyebrow">专属课程 / {difficultyLabels[course.difficulty]}</span><h2>{course.title}</h2><p className="card-description">{course.description}</p><div className="structure-summary">{course.unit_count} 单元 <span>·</span> {structurePending(course) ? '已生成 ' : ''}{course.session_count} 课时 <span>·</span> {course.exam_count} 考核</div>
      <CourseProgress course={course} />
    </div>
    <div className="ticket-stub"><span>{dateLabel(course.created_at)} 创建</span><b>查看课程 <Arrow /></b></div>
  </Link>
}
