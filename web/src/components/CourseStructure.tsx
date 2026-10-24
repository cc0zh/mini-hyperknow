import { IconArrowRight } from './icons'
import { Link } from 'react-router-dom'
import { depthLabels, unitGenerationLabels } from '../lib/course-state'
import { quizTargetPath } from '../lib/quiz-state'
import type { Course, Session, Unit } from '../lib/types'
import '../styles/course-path.css'

function PathIcon({ kind }: { kind: 'lecture' | 'project' | 'exam' }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {kind === 'lecture' && <><path d="M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Z" /><path d="M12 6v14" /></>}
    {kind === 'project' && <><path d="M4 7h16v13H4zM8 7V4h8v3M4 12h16M10 12v3h4v-3" /></>}
    {kind === 'exam' && <><path d="M8 5H5v16h14V5h-3M8 3h8v4H8zM8 14l3 3 5-6" /></>}
  </svg>
}

function SessionRow({ session, index, course }: { session: Session; index: number; course: Course }) {
  const base = `/courses/${encodeURIComponent(course.course_id)}`
  const next = course.next_item?.session_id === session.session_id
  return <li className="cp-session">
    <div className="cp-session-row">
      <span className="cp-session-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
      <div className="cp-session-copy">
        <h4 className="cp-session-title">{session.title}</h4>
        <div className="cp-session-meta">
          <span>预计 {session.estimated_minutes} 分钟</span>
          {session.completed && <span className="cp-status cp-status-complete">已完成</span>}
          {next && <span className="cp-status cp-status-next">下一课</span>}
        </div>
      </div>
      <div className="cp-actions">
        <Link className={`cp-button${next ? ' cp-button-primary' : ''}`} to={`${base}/sessions/${encodeURIComponent(session.session_id)}`} aria-label={`${next ? '继续学习' : session.completed ? '回看' : '学习'}：${session.title}`}>
          {next ? '继续学习' : session.completed ? '回看' : '学习'}
        </Link>
        <Link className="cp-button" to={`${base}${quizTargetPath('practice', session.session_id)}`} aria-label={`课后练习：${session.title}`}>课后练习</Link>
      </div>
    </div>
    <details className="cp-details cp-session-details">
      <summary>课时详情</summary>
      <div className="cp-detail-body">
        {session.description && <p className="cp-prose">{session.description}</p>}
        {!!session.depths?.length && <div className="cp-depths" aria-label="教学深度">{session.depths.map(depth => <span key={depth}>{depthLabels[depth]}</span>)}</div>}
        {session.key_points.length > 0 && <div><b className="cp-detail-label">学习要点</b><ul className="cp-detail-list">{session.key_points.map((point, i) => <li key={i}>{point}</li>)}</ul></div>}
        {!!session.outline.length && <div><b className="cp-detail-label">课时提纲</b>{Array.isArray(session.outline)
          ? <ul className="cp-detail-list">{session.outline.map((item, i) => <li key={i}>{item}</li>)}</ul>
          : <p className="cp-prose">{session.outline}</p>}</div>}
      </div>
    </details>
  </li>
}

export function CourseStructure({ course, unit }: { course: Course; unit: Unit }) {
  const pending = unit.generation_status && unit.generation_status !== 'ready'
  const hasContent = unit.lectures.length > 0 || unit.project_stages.length > 0 || unit.exams.length > 0
  const projects = course.projects.filter(project =>
    unit.project_keys?.some(key => key === project.project_key || key === project.project_id)
    || unit.project_stages.some(stage => stage.project_id === project.project_id))
  const base = `/courses/${encodeURIComponent(course.course_id)}`

  return <section className="cp-path" aria-label={`${unit.title}学习路径`}>
    {!unit.lectures.length && pending && <div className="cp-empty">
      {unit.generation_status && <span className="cp-status">{unitGenerationLabels[unit.generation_status]}</span>}
      <h3 className="cp-empty-title">学习路径尚未就绪</h3>
      <p className="cp-prose">{unit.generation_status === 'generating' ? '本单元的讲次与课时正在展开，生成后会显示在这里。' : '本单元暂未生成讲次与课时，可在单元生成进度中查看当前状态。'}</p>
    </div>}
    {!hasContent && !pending && <div className="cp-empty">
      {unit.generation_status && <span className="cp-status">{unitGenerationLabels[unit.generation_status]}</span>}
      <h3 className="cp-empty-title">本单元暂无学习内容</h3>
      <p className="cp-prose">{unit.generation_status === 'ready' ? '单元已就绪，但没有可显示的讲次、项目阶段或考核。' : '当前没有可显示的讲次、项目阶段或考核。'}</p>
    </div>}
    {hasContent && <ol className="cp-timeline">
      {unit.lectures.map((lecture, index) => <li className="cp-step" key={lecture.lecture_id}>
        <span className="cp-node"><PathIcon kind="lecture" /></span>
        <section className="cp-card">
          <div className="cp-card-heading">
            <span className="cp-kind">讲次 {String(index + 1).padStart(2, '0')}</span>
            <h3 className="cp-card-title">{lecture.title}</h3>
            {lecture.description && <p className="cp-card-description cp-prose">{lecture.description}</p>}
          </div>
          {lecture.sessions.length > 0
            ? <ol className="cp-sessions">{lecture.sessions.map((session, si) => <SessionRow key={session.session_id} session={session} index={si} course={course} />)}</ol>
            : <p className="cp-availability">本讲次暂无已生成课时。</p>}
        </section>
      </li>)}
      {unit.project_stages.map(stage => {
        const project = course.projects.find(project => project.project_id === stage.project_id)
        return <li className="cp-step" key={stage.stage_id}>
          <span className="cp-node cp-node-project"><PathIcon kind="project" /></span>
          <section className="cp-card cp-activity">
            <span className="cp-kind">项目阶段</span>
            <h3 className="cp-card-title">{stage.title}</h3>
            {project && <p className="cp-project-name">{project.name}</p>}
            <p className="cp-prose">{stage.description}</p>
            <details className="cp-details">
              <summary>阶段交付要求</summary>
              <div className="cp-detail-body"><p className="cp-prose">{stage.deliverable}</p></div>
            </details>
            <p className="cp-availability">成果提交暂未开放</p>
          </section>
        </li>
      })}
      {unit.exams.map(exam => <li className="cp-step" key={exam.exam_id}>
        <span className="cp-node cp-node-exam"><PathIcon kind="exam" /></span>
        <section className="cp-card cp-activity">
          <span className="cp-kind">单元考核</span>
          <h3 className="cp-card-title">{exam.title}</h3>
          {exam.completed && <span className="cp-status cp-status-complete">已完成</span>}
          <p className="cp-prose">{exam.goal}</p>
          <div className="cp-actions"><Link className="cp-button" to={`${base}${quizTargetPath('exam', exam.exam_id)}`} aria-label={`${exam.completed ? '查看结果或再练一次' : '进入单元考核'}：${exam.title}`}>{exam.completed ? '查看结果 / 再练一次' : '进入单元考核'} <IconArrowRight size={13} /></Link></div>
        </section>
      </li>)}
    </ol>}
    {projects.length > 0 && <details className="cp-details cp-projects">
      <summary>关联项目 · 总体目标与交付要求</summary>
      <div className="cp-detail-body">{projects.map(project => <section className="cp-project" key={project.project_id}>
        <h3 className="cp-card-title">{project.name}</h3>
        <b className="cp-detail-label">总体目标</b>
        <p className="cp-prose">{project.description}</p>
        <b className="cp-detail-label">最终交付要求</b>
        <p className="cp-prose">{project.final_deliverable}</p>
      </section>)}</div>
    </details>}
  </section>
}
