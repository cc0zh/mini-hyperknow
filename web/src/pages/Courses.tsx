import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Arrow, CourseCard, EmptyState, ErrorNotice, Loading } from '../components/ui'
import { CourseDeleteDialog } from '../components/CourseDeleteDialog'
import type { CourseDeletion } from '../components/CourseDeleteDialog'
import { useCommand } from '../lib/use-command'
import { useResource } from '../lib/use-resource'
import { recoverableCourseRuns, runLabels } from '../lib/run-state'
import type { Course, Run } from '../lib/types'

export default function Courses() {
  const { data, loading, error, reload } = useResource<{ courses: Course[] }>('/courses')
  const runs = useResource<{ runs: Run[] }>('/runs')
  const [deleting, setDeleting] = useState<Course | null>(null)
  const [notice, setNotice] = useState('')
  const deleteTrigger = useRef<HTMLButtonElement | null>(null)
  const libraryHeading = useRef<HTMLHeadingElement>(null)
  // One pending deletion for the library, not one per card: even if a response
  // is lost and the card is already gone after refresh, its command is retryable.
  const deletion = useCommand<CourseDeletion>('course-delete', () => {
    setDeleting(null)
    setNotice('课程及其关联学习记录已删除。')
    reload()
    runs.reload()
  })
  // Wait until the native dialog has closed and its cleanup has restored the
  // old trigger, then move focus to a stable heading rather than a removed card.
  useEffect(() => {
    if (!deleting && notice) libraryHeading.current?.focus()
  }, [deleting, notice])
  const refreshDeletion = () => {
    deletion.releaseConflict()
    deletion.releaseRejected()
    setDeleting(null)
    reload()
    runs.reload()
  }
  const recoverable = recoverableCourseRuns(runs.data?.runs ?? [], data?.courses ?? [])
  return <div className="page">
    <div className="page-heading"><div><span className="eyebrow">YOUR LEARNING LIBRARY</span><h1 ref={libraryHeading} tabIndex={-1}>我的课程<span className="heading-dot">.</span></h1><p>每一个目标，都有一条属于你的路径。</p></div><Link className="button primary" to="/">打造新课程 <Arrow /></Link></div>
    <p className="library-notice" role="status">{notice}</p>
    {deletion.pending && !deleting && <section className="deletion-recovery" aria-label="待确认的课程删除">
      <div><b>{deletion.busy ? '正在确认删除结果…' : deletion.conflict || deletion.rejected ? '上次删除未执行' : '上次删除结果尚未确认'}</b><p>{deletion.error ?? '重试会复用原课程、版本和命令编号，不会删除其他课程。'}</p></div>
      {deletion.conflict || deletion.rejected ? <button type="button" className="button secondary small" onClick={refreshDeletion}>刷新课程列表</button> : <button type="button" className="button secondary small" disabled={deletion.busy} onClick={() => { void deletion.execute() }}>重试同一删除请求</button>}
    </section>}
    <section className="runs-section" aria-labelledby="runs-title"><div className="section-heading"><h2 id="runs-title">课程生成记录</h2><span>最近 30 次中的未就绪运行</span></div>
      {runs.loading ? <Loading label="正在恢复生成记录…" /> : runs.error ? <ErrorNotice title="生成记录加载失败" message={runs.error} retry={runs.reload} /> : recoverable.length > 0 ? <div className="recoverable-runs">{recoverable.map(run => <Link className="recoverable-run" key={run.run_id} to={`/course-runs/${encodeURIComponent(run.run_id)}`}><span className={`run-record-status record-${run.status}`}>{runLabels[run.status]}</span><span className="run-record-goal">{run.goal}</span><span className="run-record-link">{run.status === 'awaiting_answers' ? '继续澄清' : run.status === 'awaiting_blueprint' ? '审阅蓝图' : '查看运行'} <Arrow /></span></Link>)}</div> : <p className="runs-empty">没有待查看的生成记录。已保存课程在下方。</p>}
    </section>
    {loading ? <Loading label="正在读取本地课程…" /> : error ? <ErrorNotice title="课程列表加载失败" message={error} retry={reload} /> : data?.courses.length === 0 ? <EmptyState title="你的学习旅程，尚待启程" action={<Link className="button primary" to="/">从一个目标开始 <Arrow /></Link>}>这里会保存真实生成的课程。<br />回到首页，告诉我们你想探索什么。</EmptyState> : data ? <><div className="library-count"><span>已保存的课程</span><b>{data.courses.length} 门</b></div><div className="course-grid">{data.courses.map((course, index) => <CourseCard course={course} index={index} key={course.course_id} deleteDisabled={!!deletion.pending || deletion.busy} onDelete={(selected, trigger) => {
      if (deletion.pending || deletion.busy) return
      deleteTrigger.current = trigger
      setNotice('')
      setDeleting(selected)
    }} />)}</div></> : <ErrorNotice message="未能读取课程列表。" retry={reload} />}
    {deleting && <CourseDeleteDialog course={deleting} trigger={deleteTrigger.current} command={deletion} close={() => setDeleting(null)} refresh={refreshDeletion} />}
  </div>
}
