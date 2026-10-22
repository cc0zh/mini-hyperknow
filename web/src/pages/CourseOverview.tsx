import { Link, useParams } from 'react-router-dom'
import { ErrorNotice, Loading, difficultyLabels, dateLabel } from '../components/ui'
import { useResource } from '../lib/use-resource'
import type { Course, Session, Unit } from '../lib/types'

function SessionRow({ session, index }: { session: Session; index: number }) {
  return <li className="session-row"><span className="session-number">{String(index + 1).padStart(2, '0')}</span><div><h4>{session.title}</h4><p>{session.description}</p>{session.key_points.length > 0 && <div className="key-points">{session.key_points.map((point, i) => <span key={i}>{point}</span>)}</div>}{session.outline && <details className="session-outline"><summary>查看课时提纲</summary>{Array.isArray(session.outline) ? <ul>{session.outline.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>{session.outline}</p>}</details>}</div><span className="session-duration">预计 {session.estimated_minutes} 分钟</span></li>
}

function UnitSection({ unit, index, course }: { unit: Unit; index: number; course: Course }) {
  const sessionCount = unit.lectures.reduce((sum, lecture) => sum + lecture.sessions.length, 0)
  return <details className="unit-card" open={index === 0}>
    <summary className="unit-summary"><span className="unit-number">{String(index + 1).padStart(2, '0')}</span><span className="unit-copy"><strong>{unit.title}</strong><small>{unit.description}</small></span><span className="unit-count">{sessionCount} 课时</span><span className="unit-caret" aria-hidden="true">⌄</span></summary>
    <div className="unit-content">{unit.lectures.map(lecture => <section className="lecture-section" key={lecture.lecture_id}><div className="lecture-heading"><span className="kind-label">讲座</span><h3>{lecture.title}</h3></div><p className="lecture-description">{lecture.description}</p><ol className="sessions">{lecture.sessions.map((session, si) => <SessionRow key={session.session_id} session={session} index={si} />)}</ol></section>)}
      {unit.project_stages.map(stage => <section className="activity-card project" key={stage.stage_id}><span className="kind-label">项目阶段</span><h3>{stage.title}</h3><p className="activity-parent">{course.projects.find(project => project.project_id === stage.project_id)?.name}</p><p>{stage.description}</p><div className="deliverable"><b>阶段交付</b><p>{stage.deliverable}</p></div><span className="activity-availability">仅展示阶段要求 · 成果提交尚未开放</span></section>)}
      {unit.exams.map(exam => <section className="activity-card exam" key={exam.exam_id}><span className="kind-label">单元考核</span><h3>{exam.title}</h3><p>{exam.goal}</p><span className="activity-availability">仅展示考核目标 · 作答尚未开放</span></section>)}
    </div>
  </details>
}

function Overview({ courseId }: { courseId: string }) {
  const { data: course, loading, error, reload } = useResource<Course>(`/courses/${encodeURIComponent(courseId)}`)
  if (loading) return <div className="page"><Loading label="正在读取课程结构…" /></div>
  if (error || !course) return <div className="page"><Link className="back-link" to="/courses">← 我的课程</Link><ErrorNotice title="课程加载失败" message={error || '未收到课程数据。'} retry={reload} /></div>
  return <div className="page overview-page">
    <Link className="back-link" to="/courses">← 我的课程</Link>
    <section className="course-hero"><div className="hero-orbit" aria-hidden="true" /><div className="hero-content"><div className="tags"><span>{difficultyLabels[course.difficulty]}</span>{course.tags.map((tag, i) => <span key={i}>{tag}</span>)}</div><span className="eyebrow">YOUR PERSONAL LEARNING PATH</span><h1>{course.title}</h1><p>{course.description}</p><div className="hero-metadata"><span>{course.unit_count} 单元</span><span>{course.session_count} 课时</span><span>{course.exam_count} 考核</span>{course.projects.length > 0 && <span>{course.projects.length} 个项目</span>}</div></div></section>
    <div className="overview-layout"><div className="overview-main"><div className="section-heading"><div><span className="eyebrow">THE JOURNEY</span><h2>课程目录</h2></div><span>{course.unit_count} 个单元</span></div><p className="slice-note">当前版本可浏览课程结构。课堂、练习、考核与成果提交将在后续实现；目录活动暂不可进入。</p><div className="unit-list">{course.units.length ? course.units.map((unit, index) => <UnitSection key={unit.unit_id} unit={unit} index={index} course={course} />) : <ErrorNotice title="课程结构不完整" message="服务器没有返回课程单元。" retry={reload} />}</div></div>
      <aside className="course-aside"><section className="aside-card"><span className="eyebrow">LEARNING AT A GLANCE</span><h2>你的课程概况</h2><div className="progress-label"><span>课时进度</span><b>{course.progress}%</b></div><progress max={100} value={course.progress} aria-label="课时进度" /><p className="aside-note">课时进度由服务端保存，尚未开始学习。</p>{course.next_item && <div className="next-item"><span className="eyebrow">首个学习课时</span><p>{course.next_item.title}</p><small>课堂功能尚未开放</small></div>}<dl className="course-facts"><div><dt>适合人群</dt><dd>{course.target_learner}</dd></div><div><dt>原始目标</dt><dd>{course.goal}</dd></div><div><dt>创建日期</dt><dd>{dateLabel(course.created_at)}</dd></div></dl></section>
      {course.projects.map(project => <section className="aside-card project-aside" key={project.project_id}><span className="eyebrow">COURSE PROJECT</span><h2>{project.name}</h2><p>{project.description}</p><div className="deliverable"><b>最终交付</b><p>{project.final_deliverable}</p></div></section>)}</aside>
    </div>
  </div>
}

export default function CourseOverview() {
  const { courseId = '' } = useParams()
  return <Overview key={courseId} courseId={courseId} />
}
