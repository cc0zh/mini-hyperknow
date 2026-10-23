import { Link, useParams } from 'react-router-dom'
import { CourseProgress, ErrorNotice, Loading, difficultyLabels, dateLabel } from '../components/ui'
import { CourseStructure } from '../components/CourseStructure'
import { readyUnitCount, structurePending } from '../lib/course-state'
import { useCourse } from '../lib/use-course'
import { nextLearningPath } from '../lib/quiz-state'

function Overview({ courseId }: { courseId: string }) {
  const { course, error, connection, reload } = useCourse(courseId)
  const refresh = () => { void reload() }
  if (!course) return <div className="page"><Link className="back-link" to="/courses">← 我的课程</Link>{error ? <ErrorNotice title="课程加载失败" message={error} retry={refresh} /> : <Loading label="正在读取课程结构…" />}</div>
  const next = nextLearningPath(course)
  const partial = structurePending(course)
  const generationPath = course.creation_run_id ? `/course-runs/${encodeURIComponent(course.creation_run_id)}` : null
  return <div className="page overview-page">
    <Link className="back-link" to="/courses">← 我的课程</Link>
    {error && <ErrorNotice title="暂时无法同步课程" message={error} retry={refresh} />}
    <section className="course-hero"><div className="hero-orbit" aria-hidden="true" /><div className="hero-content"><div className="tags"><span>{difficultyLabels[course.difficulty]}</span>{course.tags.map((tag, i) => <span key={i}>{tag}</span>)}</div><span className="eyebrow">YOUR PERSONAL LEARNING PATH</span><h1>{course.title}</h1><p>{course.description}</p><div className="hero-metadata"><span>{course.unit_count} 单元</span><span>{partial ? '已生成 ' : ''}{course.session_count} 课时</span><span>{course.exam_count} 考核</span>{course.projects.length > 0 && <span>{course.projects.length} 个项目</span>}</div></div></section>
    {partial && <section className="pending-command"><div><b>{course.structure_status === 'blueprint' ? '课程蓝图已保存 · 等待确认' : '目录逐单元完善中'}</b><p>已就绪 {readyUnitCount(course.units)} / {course.units.length} 单元。计划课时不计入已生成数量，完整目录保存前不计算整门课程进度。</p></div>{generationPath && <Link className="button secondary small" to={generationPath}>{course.structure_status === 'blueprint' ? '审阅课程蓝图' : '返回生成页'} →</Link>}</section>}
    <div className="overview-layout"><div className="overview-main"><div className="section-heading"><div><span className="eyebrow">THE JOURNEY</span><h2>{partial ? '课程蓝图与已保存目录' : '课程目录'}</h2></div><span>{course.unit_count} 个单元</span></div><p className="slice-note">点击已生成课时进入白板课堂，按需准备讲义和课后练习；单元考核独立保存结果。项目成果提交尚未开放。</p>{course.units.length ? <CourseStructure course={course} /> : <ErrorNotice title="课程结构不完整" message="服务器没有返回课程单元。" retry={refresh} />}</div>
      <aside className="course-aside"><section className="aside-card"><span className="eyebrow">LEARNING AT A GLANCE</span><h2>你的课程概况</h2><CourseProgress course={course} />{course.next_item && <div className="next-item"><span className="eyebrow">{course.next_item.type === 'generation' ? '继续完善课程' : '下一项学习活动'}</span><p>{course.next_item.title}</p>{next ? <Link className="button primary small" to={next}>{course.next_item.type === 'generation' ? '返回生成页' : '继续学习'} →</Link> : <small>此项目仅展示要求，成果提交尚未开放。</small>}</div>}<dl className="course-facts"><div><dt>适合人群</dt><dd>{course.target_learner}</dd></div><div><dt>原始目标</dt><dd>{course.goal}</dd></div><div><dt>创建日期</dt><dd>{dateLabel(course.created_at)}</dd></div></dl><p className="aside-note">{connection}</p></section>
      {course.projects.map(project => <section className="aside-card project-aside" key={project.project_id}><span className="eyebrow">COURSE PROJECT</span><h2>{project.name}</h2><p>{project.description}</p><div className="deliverable"><b>最终交付</b><p>{project.final_deliverable}</p></div></section>)}</aside>
    </div>
  </div>
}

export default function CourseOverview() {
  const { courseId = '' } = useParams()
  return <Overview key={courseId} courseId={courseId} />
}
