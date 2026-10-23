import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { blueprintNodes, blueprintStats, resolveBlueprintSelection } from '../lib/blueprint-view'
import type { BlueprintKind, BlueprintNode } from '../lib/blueprint-view'
import { depthLabels, unitGenerationLabels } from '../lib/course-state'
import type { Course } from '../lib/types'
import '../styles/blueprint-explorer.css'

const kindLabels: Record<BlueprintKind, string> = {
  course: '课程', unit: '单元', lecture: '讲次', session: '小节', project: '全局项目', stage: '项目阶段', exam: '考核',
}

function TextList({ title, items }: { title: string; items: string[] | undefined }) {
  return items?.length ? <section className="bx-field"><h4>{title}</h4><ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul></section> : null
}

function Field({ title, text }: { title: string; text: string | undefined }) {
  return text ? <section className="bx-field"><h4>{title}</h4><p>{text}</p></section> : null
}

function NodeDetails({ node, course, nodes, select }: { node: BlueprintNode; course: Course; nodes: BlueprintNode[]; select: (key: string) => void }) {
  const coursePath = `/courses/${encodeURIComponent(course.course_id)}`
  switch (node.kind) {
    case 'course':
      return <>
        <Field title="课程简介" text={node.data.description} /><Field title="课程目标" text={node.data.goal} /><Field title="适合人群" text={node.data.target_learner} />
        <section className="bx-field"><h4>全局项目 · 仅展示要求</h4>
          {nodes.filter(item => item.kind === 'project').map(project => <button className="bx-project-link" type="button" aria-pressed={node.key === project.key} key={project.key} onClick={() => select(project.key)}>{project.title} →</button>)}
          {!course.projects.length && <p>蓝图未安排全局项目。</p>}
        </section>
      </>
    case 'unit':
      return <>
        <Field title="范围与边界" text={node.data.description} /><TextList title="学习目标" items={node.data.learning_objectives} />
        {node.data.estimated_sessions != null && <p className="bx-note">规划约 {node.data.estimated_sessions} 课时，非已生成数量。</p>}
        <TextList title="关联全局项目" items={node.data.project_keys?.map(key => course.projects.find(project => project.project_key === key || project.project_id === key)?.name ?? key)} />
        <Field title="考核目标" text={node.data.exam_goal} />
      </>
    case 'lecture':
      return <><Field title="讲次范围" text={node.data.description} /><p className="bx-note">已保存 {node.data.sessions.length} 个小节，选择小节可查看要点和提纲。</p></>
    case 'session':
      return <>
        <Field title="小节目标与范围" text={node.data.description} />
        <TextList title="教学深度" items={node.data.depths?.map(depth => depthLabels[depth])} />
        <TextList title="学习要点" items={node.data.key_points} />
        {Array.isArray(node.data.outline) ? <TextList title="完整提纲" items={node.data.outline} /> : <Field title="完整提纲" text={node.data.outline} />}
        <p className="bx-note">预计 {node.data.estimated_minutes} 分钟{node.data.completed ? ' · 已完成' : ''}</p>
        <Link className="bx-route" to={`${coursePath}/sessions/${encodeURIComponent(node.data.session_id)}`}>进入课堂 →</Link>
        <p className="bx-note">进入课堂只读取已保存内容，准备讲义需另行确认。</p>
      </>
    case 'project':
      return <><Field title="项目要求" text={node.data.description} /><Field title="最终交付要求" text={node.data.final_deliverable} /><p className="bx-note">仅展示项目要求，成果提交尚未开放。</p></>
    case 'stage':
      return <><Field title="所属全局项目" text={course.projects.find(project => project.project_id === node.data.project_id)?.name} /><Field title="阶段要求" text={node.data.description} /><Field title="阶段交付要求" text={node.data.deliverable} /><p className="bx-note">仅展示项目要求，成果提交尚未开放。</p></>
    case 'exam':
      return <><Field title="考核目标与范围" text={node.data.goal} /><Link className="bx-route" to={`${coursePath}/exams/${encodeURIComponent(node.data.exam_id)}`}>{node.data.completed ? '查看结果 / 再练一次' : '进入单元考核'} →</Link><p className="bx-note">仅在明确准备题组时调用模型。</p></>
  }
}

export function BlueprintExplorer({ course, currentUnitId }: { course: Course; currentUnitId?: string | null }) {
  const nodes = useMemo(() => blueprintNodes(course), [course])
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const selected = resolveBlueprintSelection(nodes, selectedKey)
  // Commit only an invalid-selection fallback; normal course/version/current-unit updates are read-only.
  useEffect(() => {
    if (selected.key !== selectedKey) setSelectedKey(selected.key)
  }, [selected.key, selectedKey])
  const stats = blueprintStats(nodes)
  const units = nodes.filter(node => node.kind === 'unit')
  const activeUnit = units.find(node => node.unitId === selected.unitId)
  const branch = activeUnit ? nodes.filter(node => node.parentKey === activeUnit.key) : []
  const root = nodes[0]
  const nodeButton = (node: BlueprintNode) => <button type="button" className={`bx-node bx-${node.kind}`} aria-pressed={selected.key === node.key} onClick={() => setSelectedKey(node.key)} title={node.title}>
    <span className="bx-kind">{kindLabels[node.kind]}</span><span className="bx-node-title">{node.title}</span>
  </button>

  return <div className="bx-explorer">
    <div className="bx-overview" aria-label="课程与全部单元总览">
      <button type="button" className="bx-root" aria-pressed={selected.key === root.key} title={course.title} onClick={() => setSelectedKey(root.key)}>
        <span className="bx-kind">课程蓝图 · 点击查看课程与全局项目</span><strong className="bx-node-title">{course.title}</strong>
        <span className="bx-count">{stats.readyUnits}/{stats.units} 单元已就绪 · {stats.sessions} 已保存课时 · {stats.exams} 考核</span>
      </button>
      <ol className="bx-units">
        {units.map((node, index) => <li className="bx-unit-branch" key={node.key}>
          <button type="button" className={`bx-unit-card${activeUnit?.key === node.key ? ' bx-active-unit' : ''}${currentUnitId === node.unitId ? ' bx-generating' : ''}`} aria-pressed={selected.key === node.key} onClick={() => setSelectedKey(node.key)} title={node.title}>
            <span className="bx-unit-number">{String(index + 1).padStart(2, '0')}</span><span className="bx-unit-copy"><strong className="bx-node-title">{node.title}</strong><span className="bx-unit-objective">{node.data.learning_objectives?.[0] ?? node.data.description}</span><span className="bx-unit-meta">{node.data.generation_status ? unitGenerationLabels[node.data.generation_status] : '已保存结构'} · {node.data.generation_status === 'ready' ? `${node.data.lectures.reduce((sum, lecture) => sum + lecture.sessions.length, 0)} 课时` : `规划约 ${node.data.estimated_sessions ?? '—'} 课时`}{currentUnitId === node.unitId ? ' · 当前展开' : ''}</span></span>
          </button>
        </li>)}
      </ol>
    </div>
    <div className={`bx-local${activeUnit ? '' : ' bx-local-wide'}`}>
      {activeUnit && <section className="bx-branch" aria-label="所选单元已保存结构">
        <h3 className="bx-panel-heading">单元结构 <span>仅展示已保存节点</span></h3>
        <div className="bx-branch-scroll"><p className="bx-branch-title">{activeUnit.title}</p>
          {branch.length ? <ul className="bx-children">{branch.map(node => <li key={node.key}>{nodeButton(node)}
            {node.kind === 'lecture' && <ul className="bx-children">{nodes.filter(child => child.parentKey === node.key).map(child => <li key={child.key}>{nodeButton(child)}</li>)}</ul>}
          </li>)}</ul> : <p className="bx-note">本单元尚未保存讲次、小节、项目阶段或考核。可在右侧查看规划目标与范围。</p>}
        </div>
      </section>}
      <section className="bx-detail" aria-label="所选节点完整详情">
        <h3 className="bx-panel-heading">节点详情 <span>{kindLabels[selected.kind]}</span></h3>
        <div className="bx-detail-scroll"><h4 className="bx-detail-title">{selected.title}</h4><NodeDetails node={selected} course={course} nodes={nodes} select={setSelectedKey} /></div>
      </section>
    </div>
  </div>
}
