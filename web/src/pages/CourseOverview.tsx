import { IconArrowRight, IconChevronLeft } from '../components/icons'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { CourseProgress, ErrorNotice, Loading, difficultyLabels, dateLabel } from '../components/ui'
import { CourseStructure } from '../components/CourseStructure'
import { readyUnitCount, structurePending, unitGenerationLabels, unitSessionCount } from '../lib/course-state'
import { useCourse } from '../lib/use-course'
import { nextLearningPath } from '../lib/quiz-state'
import '../styles/course-overview.css'

function Overview({ courseId }: { courseId: string }) {
  const { course, error, connection, reload } = useCourse(courseId)
  const [params, setParams] = useSearchParams()
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const requestedUnit = params.get('unit')
  const unit = course?.units.find(item => item.unit_id === requestedUnit)
    ?? course?.units.find(item => item.unit_id === course.next_item?.unit_id)
    ?? course?.units[0]
  // Pin the initial selection: progress notifications must not move the unit
  // being read. The URL preserves it after refresh and browser Back.
  useEffect(() => {
    if (unit && requestedUnit !== unit.unit_id) {
      const next = new URLSearchParams(params)
      next.set('unit', unit.unit_id)
      setParams(next, { replace: true, preventScrollReset: true })
    }
  }, [unit, requestedUnit, params, setParams])
  const refresh = () => { void reload() }
  if (!course) return <div className="page overview-page"><Link className="back-link" to="/courses"><IconChevronLeft size={15} />我的课程</Link>{error ? <ErrorNotice title="课程加载失败" message={error} retry={refresh} /> : <Loading label="正在读取课程结构…" />}</div>
  const partial = structurePending(course)
  const next = nextLearningPath(course)
  const generationPath = course.creation_run_id ? `/course-runs/${encodeURIComponent(course.creation_run_id)}` : null
  const unitIndex = unit ? course.units.indexOf(unit) : -1
  const unitCount = unit ? unitSessionCount(unit) : 0
  const completedCount = unit?.lectures.flatMap(lecture => lecture.sessions).filter(session => session.completed).length ?? 0
  const unitPending = unit?.generation_status && unit.generation_status !== 'ready'
  const nextInUnit = course.next_item?.unit_id === unit?.unit_id
  const showNext = next && !partial && (!nextInUnit || course.next_item?.type === 'exam')
  const unitSearch = (id: string) => {
    const search = new URLSearchParams(params)
    search.set('unit', id)
    return `?${search.toString()}`
  }
  return <div className="page overview-page">
    <div className="ov-topline"><Link className="back-link" to="/courses"><IconChevronLeft size={15} />我的课程</Link><span>课程总览 <span aria-hidden="true">/</span> 你的学习路径</span></div>
    {error && <ErrorNotice title="暂时无法同步课程" message={error} retry={refresh} />}
    <div className="ov-workspace">
      <aside className="ov-sidebar" aria-label="课程信息与单元导航">
        <div className="ov-cover" aria-hidden="true">
          <span>YOUR LEARNING PATH</span>
          <svg viewBox="0 0 260 140" fill="none"><path d="M36 99C59 99 54 43 88 43H168C209 43 187 105 225 105" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 5" /><rect x="65" y="23" width="126" height="90" rx="12" fill="#fff" fillOpacity=".55" transform="rotate(-9 128 68)" /><rect x="72" y="17" width="126" height="90" rx="12" fill="#fafaf8" stroke="currentColor" strokeOpacity=".35" transform="rotate(5 135 62)" /><path d="M108 45C118 42 124 43 134 48C144 43 150 42 160 45V78C150 75 144 76 134 81C124 76 118 75 108 78V45ZM134 49V80M116 54L126 56M116 62L126 64M143 56L153 54M143 64L153 62" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /><circle cx="36" cy="99" r="7" fill="#fafaf8" stroke="currentColor" strokeWidth="1.5" /><circle cx="225" cy="105" r="7" fill="#fafaf8" stroke="currentColor" strokeWidth="1.5" /><path d="M32 99L35 102L40 96M222 105H228M225 102V108" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          <div><span>{difficultyLabels[course.difficulty]}</span><span>{course.unit_count} 个单元 · 循序深入</span></div>
        </div>
        <div className="ov-course-heading"><span className="ov-overline">专属于你的课程 · {difficultyLabels[course.difficulty]}</span><h1>{course.title}</h1></div>
        <div className="ov-description"><p id="course-description" className={descriptionOpen ? 'is-expanded' : ''}>{course.description}</p><button className="ov-text-button" type="button" aria-expanded={descriptionOpen} aria-controls="course-description" onClick={() => setDescriptionOpen(open => !open)}>{descriptionOpen ? '收起简介' : '展开简介'} <span aria-hidden="true">{descriptionOpen ? '−' : '+'}</span></button></div>
        <div className="ov-course-meta"><span>{partial ? '已生成 ' : ''}{course.session_count} 课时</span><span>{course.exam_count} 考核</span>{course.projects.length > 0 && <span>{course.projects.length} 项目</span>}</div>
        <section className="ov-progress" aria-label="课程进度"><CourseProgress course={course} /></section>
        <nav className="ov-units" aria-label="课程单元"><div className="ov-nav-heading"><h2>单元目录</h2><span>{course.units.length} 单元</span></div><ol>{course.units.map((item, index) => <li key={item.unit_id}><Link to={unitSearch(item.unit_id)} preventScrollReset aria-current={unit?.unit_id === item.unit_id ? 'step' : undefined} className="ov-unit-link"><span className="ov-unit-number">{String(index + 1).padStart(2, '0')}</span><span className="ov-unit-copy"><strong>{item.title}</strong><small>{item.generation_status && item.generation_status !== 'ready' ? unitGenerationLabels[item.generation_status] : `${unitSessionCount(item)} 课时`}</small></span><svg aria-hidden="true" viewBox="0 0 16 16" fill="none"><path d="m6 4 4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg></Link></li>)}</ol></nav>
        <div className="ov-unit-picker"><label htmlFor="overview-unit">当前单元</label><select id="overview-unit" value={unit?.unit_id ?? ''} onChange={event => setParams(unitSearch(event.target.value), { preventScrollReset: true })}>{course.units.map((item, index) => <option key={item.unit_id} value={item.unit_id}>{index + 1}. {item.title}</option>)}</select></div>
        <details className="ov-course-details"><summary>课程信息与标签</summary><div className="ov-tags">{course.tags.map((tag, index) => <span key={index}>{tag}</span>)}</div><dl><div><dt>适合人群</dt><dd>{course.target_learner}</dd></div><div><dt>原始目标</dt><dd>{course.goal}</dd></div><div><dt>创建日期</dt><dd>{dateLabel(course.created_at)}</dd></div></dl></details>
        <p className="ov-connection">{connection}</p>
      </aside>
      <section className="ov-main" aria-labelledby={unit ? 'current-unit-title' : undefined} aria-label={unit ? undefined : '课程内容'}>
        {unit ? <>
          <header className="ov-unit-header"><div className="ov-unit-kicker"><span>第 {unitIndex + 1} 单元 <span aria-hidden="true">/</span> 共 {course.units.length} 单元</span><span className={`ov-status${unitPending ? ' is-pending' : ''}`}>{unit.generation_status ? unitGenerationLabels[unit.generation_status] : '课程目录'}</span></div><h2 id="current-unit-title">{unit.title}</h2><p className="ov-unit-description">{unit.description}</p><div className="ov-unit-metadata"><span>{unit.lectures.length} 讲次</span><span>{unitCount} 已生成课时</span>{unitCount > 0 && <span>{completedCount} 已完成</span>}{unit.exams.length > 0 && <span>{unit.exams.length} 单元考核</span>}</div>
            {(!!unit.learning_objectives?.length || unit.estimated_sessions != null || unit.exam_goal || !!unit.project_keys?.length) && <details className="ov-objectives" key={unit.unit_id}><summary>查看学习目标与单元安排</summary>{!!unit.learning_objectives?.length && <ul>{unit.learning_objectives.map((objective, index) => <li key={index}>{objective}</li>)}</ul>}{unit.estimated_sessions != null && <p>计划规模：约 {unit.estimated_sessions} 课时（不计入已生成数量）</p>}{unit.exam_goal && <p><b>考核目标：</b>{unit.exam_goal}</p>}{!!unit.project_keys?.length && <p><b>关联项目：</b>{unit.project_keys.map(key => course.projects.find(project => project.project_key === key || project.project_id === key)?.name ?? key).join('、')}</p>}</details>}
          </header>
          {partial && <section className="ov-command is-pending" aria-label="课程生成状态"><div><b>{course.structure_status === 'blueprint' ? '蓝图已保存，等待你的确认' : '课程目录尚未完整'}</b><p>{readyUnitCount(course.units)} / {course.units.length} 单元已就绪；{course.structure_status === 'blueprint' ? '确认蓝图后，才会开始生成讲次与课时。' : '已保存的课时可以先学，其余内容请在生成页查看。'}</p></div>{generationPath && <Link className="button primary small" to={generationPath}>{course.structure_status === 'blueprint' ? '审阅课程蓝图' : '查看生成状态'} <IconArrowRight size={14} /></Link>}</section>}
          {showNext && <section className="ov-command" aria-label="下一项学习活动"><div><span className="ov-overline">接着上次的进度</span><b>{course.next_item?.title}</b></div><Link className="button primary small" to={next}>继续学习 <IconArrowRight size={14} /></Link></section>}
          <div className="ov-path-heading"><h3>{unitPending ? '本单元的学习安排' : '本单元的学习路径'}</h3><span>按自己的节奏，逐步深入</span></div>
          <CourseStructure key={unit.unit_id} course={course} unit={unit} />
          <nav className="ov-unit-pagination" aria-label="相邻单元">{unitIndex > 0 ? <Link to={unitSearch(course.units[unitIndex - 1].unit_id)} preventScrollReset><span>← 上一单元</span><strong>{course.units[unitIndex - 1].title}</strong></Link> : <span />}{unitIndex + 1 < course.units.length && <Link to={unitSearch(course.units[unitIndex + 1].unit_id)} preventScrollReset><span>下一单元 <IconArrowRight size={13} /></span><strong>{course.units[unitIndex + 1].title}</strong></Link>}</nav>
        </> : <ErrorNotice title="课程结构不完整" message="服务器没有返回课程单元。" retry={refresh} />}
      </section>
    </div>
  </div>
}

export default function CourseOverview() {
  const { courseId = '' } = useParams()
  return <Overview key={courseId} courseId={courseId} />
}
