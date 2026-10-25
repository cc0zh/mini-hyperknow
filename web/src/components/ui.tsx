import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useResource } from '../lib/use-resource'
import type { Course, Health } from '../lib/types'
import { progressLabel } from '../lib/format'
import { courseProgress, structurePending } from '../lib/course-state'
import { nextLearningPath } from '../lib/quiz-state'
import {
  IconArrowRight, IconArrowUpRight, IconBook, IconChevronLeft, IconHome, IconLibrary, IconSidebar, IconSpark, IconTrash,
} from './icons'

const HealthContext = createContext<ReturnType<typeof useResource<Health>> | null>(null)
export const useHealth = () => useContext(HealthContext)!

export function Mark({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true">
    <svg viewBox="0 0 32 32" fill="none"><path d="M5 7v18M27 7v18M5 16h22M11 5v22M21 5v22" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /></svg>
  </span>
}

// Shared back link so every route uses the same chevron instead of a glyph
// that jumps in size between Windows and macOS.
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="back-link" to={to}><IconChevronLeft size={15} />{children}</Link>
}

export function Arrow() { return <IconArrowUpRight size={14} className="arrow-icon" /> }

const SIDEBAR_KEY = 'hyperknow.sidebar'

function readSidebarPreference() {
  try { return window.localStorage.getItem(SIDEBAR_KEY) === 'collapsed' } catch { return false }
}

export function Shell() {
  const health = useResource<Health>('/health')
  const { pathname } = useLocation()
  const isCreation = /^\/course-runs\/[^/]+\/?$/.test(pathname)
  const [collapsed, setCollapsed] = useState(readSidebarPreference)
  const [scrolled, setScrolled] = useState(false)

  const toggleSidebar = useCallback(() => {
    setCollapsed(previous => {
      const next = !previous
      try { window.localStorage.setItem(SIDEBAR_KEY, next ? 'collapsed' : 'open') } catch { /* private mode */ }
      return next
    })
  }, [])

  useEffect(() => { window.scrollTo(0, 0) }, [pathname])

  // A sentinel above the sticky bar avoids a scroll listener on every frame.
  useEffect(() => {
    if (isCreation) return
    const sentinel = document.getElementById('topbar-sentinel')
    if (!sentinel || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) => setScrolled(!entry.isIntersecting),
      { rootMargin: '-1px 0px 0px 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [isCreation, pathname])

  return <HealthContext.Provider value={health}>
    <a className="skip-link" href="#main">跳到主要内容</a>
    <div className={`app-shell${isCreation ? ' creation-shell' : ''}${collapsed ? ' nav-collapsed' : ''}`}>
      {!isCreation && <>
      <aside className={`sidebar${collapsed ? ' collapsed' : ''}`}>
        <Link to="/" className="brand" aria-label="Hyperknow 首页"><Mark /><span>Hyperknow<small>让知识，成为你的。</small></span></Link>
        <div className="sidebar-label">我的学习空间</div>
        <nav aria-label="主导航">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="首页"><span className="nav-icon"><IconHome /></span><span className="nav-text">首页</span></NavLink>
          <NavLink to="/assistance" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="即时协助"><span className="nav-icon"><IconSpark /></span><span className="nav-text">即时协助</span></NavLink>
          <NavLink to="/courses" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title="我的课程"><span className="nav-icon"><IconLibrary /></span><span className="nav-text">我的课程</span></NavLink>
        </nav>
        <div className="sidebar-note"><span className="note-line" /><p>每一个问题，<br />都可以是一段学习的开始。</p></div>
        <div className="sidebar-footer"><span className="avatar">我</span><div><b>个人学习空间</b><small>本地 · 单用户</small></div></div>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={toggleSidebar}
          aria-expanded={!collapsed}
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
          title={collapsed ? '展开侧栏' : '收起侧栏'}
        ><IconSidebar size={18} /></button>
      </aside></>}
      <div className="workspace">
        {!isCreation && <div id="topbar-sentinel" aria-hidden="true" />}
        {!isCreation && <header className={`topbar${scrolled ? ' is-scrolled' : ''}`}><span>LEARN SOMETHING THAT MATTERS</span><div className={`service-pill ${health.error || health.data?.model.configured === false ? 'warning' : ''}`}>
          <i aria-hidden="true" />{health.loading ? '正在连接本地服务' : health.error ? '本地服务不可用' : health.data?.model.configured ? '本地服务已连接' : '模型尚未配置'}
        </div></header>}
        <main id="main" tabIndex={-1}><Outlet /></main>
        {!isCreation && <footer className="page-footer">Hyperknow <span>·</span> 从好奇开始，循路径深入</footer>}
      </div>
      {!isCreation && <nav className="tabbar" aria-label="底部导航">
        <NavLink to="/" end className={({ isActive }) => `tab-link ${isActive ? 'active' : ''}`}><IconHome size={21} /><span>首页</span></NavLink>
        <NavLink to="/assistance" className={({ isActive }) => `tab-link ${isActive ? 'active' : ''}`}><IconSpark size={21} /><span>协助</span></NavLink>
        <NavLink to="/courses" className={({ isActive }) => `tab-link ${isActive ? 'active' : ''}`}><IconLibrary size={21} /><span>课程</span></NavLink>
      </nav>}
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
  return <div className="empty-state"><span className="empty-icon"><IconBook size={26} /></span><h2>{title}</h2><p>{children}</p>{action}</div>
}

export const difficultyLabels = { beginner: '入门', intermediate: '中级', advanced: '进阶' }
export const dateLabel = (date: string) => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(date))

export function CourseProgress({ course, compact = false }: { course: Course; compact?: boolean }) {
  const progress = courseProgress(course)
  return <><div className="progress-label"><span>课时进度</span><b>{progressLabel(progress)}</b></div>{progress === null ? <><div className="progress-incomplete" aria-hidden="true" /><p className="aside-note">目录尚未完整，暂不计算整门课程进度。</p></> : <><progress value={progress} max={100} aria-label={`${course.title}课时进度`} /><p className="aside-note">{compact ? '按已完成课时计算，不代表掌握度。' : '按服务端保存的已完成课时计算，不代表掌握度；考核不计入课时比例。'}</p></>}</>
}

// Cover art is deterministic per course_id: the same course always draws the
// same constellation, so the library reads as distinct objects, not decoration.
function coverSeed(id: string) {
  let hash = 0
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) % 100000
  return hash
}

function CoverArt({ id }: { id: string }) {
  const seed = coverSeed(id)
  const nodes = Array.from({ length: 5 }, (_, i) => {
    const angle = ((seed % 360) + i * 72 + (seed % 17)) * (Math.PI / 180)
    const radius = 26 + ((seed >> (i * 3)) % 32)
    return { x: 50 + Math.cos(angle) * radius, y: 50 + Math.sin(angle) * radius * .72 }
  })
  return <svg className="cover-art" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
    {nodes.slice(1).map((node, i) => <line key={i} x1={nodes[0].x} y1={nodes[0].y} x2={node.x} y2={node.y} />)}
    {nodes.slice(1).map((node, i) => <line key={`p${i}`} x1={node.x} y1={node.y} x2={nodes[(i + 1) % 4 + 1].x} y2={nodes[(i + 1) % 4 + 1].y} />)}
    {nodes.map((node, i) => <circle key={`c${i}`} cx={node.x} cy={node.y} r={i === 0 ? 3.4 : 1.9} />)}
  </svg>
}

export function CourseCard({ course, index = 0, onDelete, deleteDisabled = false }: {
  course: Course; index?: number; onDelete: (course: Course, trigger: HTMLButtonElement) => void; deleteDisabled?: boolean
}) {
  const overview = `/courses/${encodeURIComponent(course.course_id)}`
  const next = nextLearningPath(course)
  const nextLabel = next ? `继续：${course.next_item!.title}` : '查看学习安排'
  return <article className={`course-card tone-${index % 3}`} aria-label={course.title}>
    <Link className="course-card-content" to={overview} aria-label={`查看课程：${course.title}`}>
    <div className="ticket-cover"><CoverArt id={course.course_id} /><div className="cover-top"><Mark small /><span>{course.tags[0] || '学科未标注'}</span></div><div className="cover-title">{course.title}</div><span className="cover-motif" aria-hidden="true"><IconSpark size={56} strokeWidth={1.1} /></span></div>
    <div className="ticket-body"><span className="eyebrow">专属课程 / {difficultyLabels[course.difficulty]}</span><h2 title={course.title}>{course.title}</h2><p className="card-description">{course.description}</p><div className="structure-summary">{course.unit_count} 单元 <span>·</span> {structurePending(course) ? '已生成 ' : ''}{course.session_count} 课时 <span>·</span> {course.exam_count} 考核</div>
      <div className="course-card-progress"><CourseProgress course={course} compact /></div>
    </div>
    </Link>
    <div className="ticket-stub"><span>{dateLabel(course.created_at)} 创建</span><Link to={overview}>查看课程 <Arrow /></Link></div>
    <div className="course-card-actions">
      <Link className="button secondary small course-continue" to={next ?? overview} title={nextLabel}><span>{nextLabel}</span><IconArrowRight size={14} /></Link>
      <button type="button" className="course-delete" disabled={deleteDisabled} aria-label={`删除课程：${course.title}`} onClick={event => onDelete(course, event.currentTarget)}><IconTrash size={16} /><span>删除</span></button>
    </div>
  </article>
}
