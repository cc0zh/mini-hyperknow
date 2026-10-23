import { Link } from 'react-router-dom'
import { Arrow, CourseCard, EmptyState, ErrorNotice, Loading } from '../components/ui'
import { useResource } from '../lib/use-resource'
import { runLabels } from '../lib/run-state'
import { nextLearningPath } from '../lib/quiz-state'
import { structurePending } from '../lib/course-state'
import type { Course, Run } from '../lib/types'

export default function Courses() {
  const { data, loading, error, reload } = useResource<{ courses: Course[] }>('/courses')
  const runs = useResource<{ runs: Run[] }>('/runs')
  const recoverable = runs.data?.runs.filter(run => (!run.kind || run.kind === 'course') && run.status !== 'ready') ?? []
  return <div className="page">
    <div className="page-heading"><div><span className="eyebrow">YOUR LEARNING LIBRARY</span><h1>我的课程<span className="heading-dot">.</span></h1><p>每一个目标，都有一条属于你的路径。</p></div><Link className="button primary" to="/">打造新课程 <Arrow /></Link></div>
    <section className="runs-section" aria-labelledby="runs-title"><div className="section-heading"><h2 id="runs-title">课程生成记录</h2><span>最近 30 次中的未就绪运行</span></div>
      {runs.loading ? <Loading label="正在恢复生成记录…" /> : runs.error ? <ErrorNotice title="生成记录加载失败" message={runs.error} retry={runs.reload} /> : recoverable.length > 0 ? <div className="recoverable-runs">{recoverable.map(run => <Link className="recoverable-run" key={run.run_id} to={`/course-runs/${encodeURIComponent(run.run_id)}`}><span className={`run-record-status record-${run.status}`}>{runLabels[run.status]}</span><span className="run-record-goal">{run.goal}</span><span className="run-record-link">{run.status === 'awaiting_answers' ? '继续澄清' : run.status === 'awaiting_blueprint' ? '审阅蓝图' : '查看运行'} <Arrow /></span></Link>)}</div> : <p className="runs-empty">没有待查看的生成记录。已保存课程在下方。</p>}
    </section>
    {loading ? <Loading label="正在读取本地课程…" /> : error ? <ErrorNotice title="课程列表加载失败" message={error} retry={reload} /> : data?.courses.length === 0 ? <EmptyState title="你的学习旅程，尚待启程" action={<Link className="button primary" to="/">从一个目标开始 <Arrow /></Link>}>这里会保存真实生成的课程。<br />回到首页，告诉我们你想探索什么。</EmptyState> : data ? <><div className="library-count"><span>已保存的课程</span><b>{data.courses.length} 门</b></div><div className="course-grid">{data.courses.map((course, index) => <div className="course-card-wrap" key={course.course_id}><CourseCard course={course} index={index} />{course.next_item && <div className="course-continue">{nextLearningPath(course) ? <Link className="button secondary small" to={nextLearningPath(course)!}>继续：{course.next_item.title} →</Link> : <span className="aside-note">下一项：{course.next_item.title} · 项目提交尚未开放</span>}</div>}{structurePending(course) && course.creation_run_id && course.next_item?.type !== 'generation' && <div className="course-continue"><Link className="text-button" to={`/course-runs/${encodeURIComponent(course.creation_run_id)}`}>返回生成页，查看目录进展 →</Link></div>}</div>)}</div></> : <ErrorNotice message="未能读取课程列表。" retry={reload} />}
  </div>
}
