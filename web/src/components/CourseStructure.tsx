import { Link } from 'react-router-dom'
import { depthLabels, unitGenerationLabels, unitSessionCount } from '../lib/course-state'
import type { Course, Session, Unit } from '../lib/types'

function SessionRow({ session, index, courseId }: { session: Session; index: number; courseId: string }) {
  return <li className="session-row"><span className="session-number">{String(index + 1).padStart(2, '0')}</span><div><h4><Link to={`/courses/${encodeURIComponent(courseId)}/sessions/${encodeURIComponent(session.session_id)}`}>{session.title} ↗</Link>{session.completed && <span className="session-completed">✓ 已完成</span>}</h4><p>{session.description}</p>
    {!!session.depths?.length && <div className="depth-tags" aria-label="教学深度">{session.depths.map(depth => <span key={depth}>{depthLabels[depth]}</span>)}</div>}
    {session.key_points.length > 0 && <div className="key-points">{session.key_points.map((point, i) => <span key={i}>{point}</span>)}</div>}{session.outline && <details className="session-outline"><summary>查看课时提纲</summary>{Array.isArray(session.outline) ? <ul>{session.outline.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p>{session.outline}</p>}</details>}</div><span className="session-duration">预计 {session.estimated_minutes} 分钟</span></li>
}

function UnitSection({ unit, index, course }: { unit: Unit; index: number; course: Course }) {
  const sessionCount = unitSessionCount(unit)
  const pending = unit.generation_status && unit.generation_status !== 'ready'
  return <details className="unit-card" open={index === 0}>
    <summary className="unit-summary"><span className="unit-number">{String(index + 1).padStart(2, '0')}</span><span className="unit-copy"><strong>{unit.title}</strong><small>{unit.description}</small></span><span className="unit-count">{unit.generation_status && <span className={`unit-state unit-state-${unit.generation_status}`}>{unitGenerationLabels[unit.generation_status]}</span>}{sessionCount} 已生成课时</span><span className="unit-caret" aria-hidden="true">⌄</span></summary>
    <div className="unit-content">
      <div className="unit-blueprint">
        <p><b>范围与边界：</b>{unit.description}</p>
        {!!unit.learning_objectives?.length && <><h3>学习目标</h3><ul>{unit.learning_objectives.map((objective, i) => <li key={i}>{objective}</li>)}</ul></>}
        {unit.estimated_sessions != null && <p>计划规模：约 {unit.estimated_sessions} 课时（非已生成数量）</p>}
        {!!unit.project_keys?.length && <p>关联全局项目：{unit.project_keys.map(key => course.projects.find(project => project.project_key === key || project.project_id === key)?.name ?? key).join('、')}</p>}
        {unit.exam_goal && <p><b>考核目标：</b>{unit.exam_goal}</p>}
        {pending && <p className="inline-note">{unit.generation_status === 'generating' ? '正在生成本单元的讲次、小节、项目阶段与考核。' : '本单元尚未就绪；已保存内容会保留，展开进度可在生成页查看。'}</p>}
      </div>
      {unit.lectures.map(lecture => <section className="lecture-section" key={lecture.lecture_id}><div className="lecture-heading"><span className="kind-label">讲次</span><h3>{lecture.title}</h3></div><p className="lecture-description">{lecture.description}</p><ol className="sessions">{lecture.sessions.map((session, si) => <SessionRow key={session.session_id} session={session} index={si} courseId={course.course_id} />)}</ol></section>)}
      {unit.project_stages.map(stage => <section className="activity-card project" key={stage.stage_id}><span className="kind-label">项目阶段</span><h3>{stage.title}</h3><p className="activity-parent">{course.projects.find(project => project.project_id === stage.project_id)?.name}</p><p>{stage.description}</p><div className="deliverable"><b>阶段交付</b><p>{stage.deliverable}</p></div><span className="activity-availability">仅展示阶段要求 · 成果提交尚未开放</span></section>)}
      {unit.exams.map(exam => <section className="activity-card exam" key={exam.exam_id}><span className="kind-label">单元考核</span><h3>{exam.title}{exam.completed && <span className="session-completed">✓ 已完成</span>}</h3><p>{exam.goal}</p><Link className="button secondary small" to={`/courses/${encodeURIComponent(course.course_id)}/exams/${encodeURIComponent(exam.exam_id)}`}>{exam.completed ? '查看结果 / 再练一次' : '进入单元考核'} →</Link><span className="activity-availability">真实出题与作答 · 只有明确点击准备题组才调用模型</span></section>)}
    </div>
  </details>
}

export function CourseStructure({ course }: { course: Course }) {
  return <div className="unit-list">{course.units.map((unit, index) => <UnitSection key={unit.unit_id} unit={unit} index={index} course={course} />)}</div>
}

export function CourseGoals({ course }: { course: Course }) {
  return <div className="blueprint-goals"><span className="eyebrow">COURSE BLUEPRINT</span><h2>{course.title}</h2><p>{course.description}</p><dl className="course-facts"><div><dt>课程目标</dt><dd>{course.goal}</dd></div><div><dt>适合人群</dt><dd>{course.target_learner}</dd></div></dl>
    <div className="blueprint-projects"><h3>全局项目</h3>{course.projects.length ? course.projects.map(project => <section className="activity-card project" key={project.project_id}><h4>{project.name}</h4><p>{project.description}</p><div className="deliverable"><b>最终交付</b><p>{project.final_deliverable}</p></div></section>) : <p className="inline-note">这份蓝图没有安排全局项目。</p>}</div>
  </div>
}
