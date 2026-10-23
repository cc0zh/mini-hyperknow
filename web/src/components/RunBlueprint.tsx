import { useState } from 'react'
import { Link } from 'react-router-dom'
import { readPending } from '../lib/commands'
import { canReviewBlueprint, readyUnitCount } from '../lib/course-state'
import { useCourse } from '../lib/use-course'
import type { Run } from '../lib/types'
import { CourseGoals, CourseStructure } from './CourseStructure'
import { ErrorNotice, Loading } from './ui'

export function RunBlueprint({ run, locked, decide }: { run: Run; locked: boolean; decide: (approve: boolean, feedback: string) => void }) {
  // The parent only mounts this once a real course ID exists. Run version changes
  // update props, not this course subscription or the disclosure state.
  const { course, error, connection, reload } = useCourse(run.course_id!)
  const [feedback, setFeedback] = useState(() => String(readPending(`run:${run.run_id}`)?.body.feedback ?? ''))
  const reviewable = canReviewBlueprint(run, course) && !error

  return <section className="run-blueprint" aria-labelledby="blueprint-title">
    <div className="section-heading"><h2 id="blueprint-title">课程实时蓝图</h2>{course && <span>蓝图 v{course.blueprint_version ?? 1} · 已就绪 {readyUnitCount(course.units)} / {course.units.length} 单元</span>}</div>
    <p className="connection-label">{connection}</p>
    {error && <ErrorNotice title="课程结构同步失败" message={error} retry={() => { void reload() }} />}
    {!course ? !error && <Loading label="正在读取已保存的课程蓝图…" /> : <>
      <CourseGoals course={course} />
      <div className="section-heading"><h2>单元路径</h2><span>{course.session_count} 已生成课时 · {course.exam_count} 考核</span></div>
      <p className="slice-note">审阅每个单元的范围、学习目标与项目分工。展开和折叠仅查看已保存结构，不调用模型。</p>
      <CourseStructure course={course} />
      {run.status === 'awaiting_blueprint' && course.structure_status === 'blueprint' && <form className="blueprint-review" onSubmit={event => { event.preventDefault(); if (feedback.trim() && !locked && reviewable) decide(false, feedback) }}>
        <h3>确认整门课程的方向</h3><p>只需批准一次。确认后将自动依次展开所有单元，无需逐单元确认。等待审阅期间不占用模型执行槽。</p>
        <label className="custom-answer" htmlFor="blueprint-feedback">修改意见（调整蓝图时必填）<textarea id="blueprint-feedback" rows={3} maxLength={6000} value={feedback} disabled={locked} placeholder="例如：减少入门内容，把项目实践放在第二单元之后…" onChange={event => setFeedback(event.target.value)} /></label>
        {!reviewable && <p className="inline-note">正在同步本次待审阅的蓝图，读取后即可确认。</p>}
        <div className="form-actions"><button className="button secondary" type="submit" disabled={locked || !feedback.trim() || !reviewable}>提交修改意见</button><button className="button primary" type="button" disabled={locked || !reviewable} onClick={() => decide(true, '')}>确认蓝图并展开课程</button></div>
      </form>}
      {course.structure_status === 'expanding' && <p className="blueprint-saved-note" role="status">蓝图已确认，单元按顺序自动展开。已保存内容可查看；失败、取消或中断后重试会保留部分成果。</p>}
      <Link className="button secondary small" to={`/courses/${encodeURIComponent(course.course_id)}`}>查看已保存的课程总览 ↗</Link>
    </>}
  </section>
}
