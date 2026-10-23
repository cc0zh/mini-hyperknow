import type { Course, Run } from './types.ts'

export function savedPreferences(run: Pick<Run, 'questions' | 'answers' | 'skipped'>) {
  if (run.skipped) return []
  return run.questions.flatMap(question => {
    const answer = run.answers.find(item => item.question_id === question.id)
    if (!answer) return []
    const labels = question.type === 'single' && answer.custom_text.trim() ? [] :
      question.options.filter(option => answer.option_ids.includes(option.id)).map(option => option.label)
    const values = [...labels, ...(answer.custom_text.trim() ? [answer.custom_text.trim()] : [])]
    return values.length ? [{ question: question.question, values }] : []
  })
}

export function savedStructureCounts(course: Course | null) {
  const units = course?.units ?? []
  return {
    units: units.filter(unit => unit.generation_status === 'ready').length,
    lectures: units.reduce((sum, unit) => sum + unit.lectures.length, 0),
    sessions: units.reduce((sum, unit) => sum + unit.lectures.reduce((count, lecture) => count + lecture.sessions.length, 0), 0),
  }
}

const order = ['clarifying', 'research', 'blueprint', 'units'] as const
export function workbenchSteps(run: Run) {
  const index = order.indexOf(run.stage ?? 'clarifying')
  return order.map((stage, position) => ({
    stage,
    label: { clarifying: '确认学习需求', research: '查阅参考资料', blueprint: '设计课程方向', units: '完善全部单元' }[stage],
    state: run.status === 'ready' || position < index ? 'done' : position > index ? 'pending' :
      ['failed', 'cancelled', 'interrupted'].includes(run.status) ? 'stopped' :
        ['awaiting_answers', 'awaiting_blueprint'].includes(run.status) ? 'waiting' : 'active',
  }))
}

export function workbenchStatus(run: Run, course: Course | null): { title: string; description: string } {
  if (run.status === 'ready') return { title: '课程准备好了', description: '学习路径已保存。从第一课开始，讲义会在你需要时准备。' }
  if (run.status === 'awaiting_answers') return { title: '先了解你的学习偏好', description: '这些选择会影响课程内容，也可以跳过，按原始目标继续。' }
  if (run.status === 'awaiting_blueprint') return { title: '请确认课程方向', description: '先看看全部单元是否符合预期。确认一次后，我们会继续完善整门课程。' }
  if (run.status === 'failed') return { title: '这一步没有完成', description: '已保存的资料和内容仍在。解决下方问题后，可以继续未完成部分。' }
  if (run.status === 'cancelled') return { title: '已停止生成', description: '已有内容已保留。需要时可以继续完善剩余部分。' }
  if (run.status === 'interrupted') return { title: '上次生成已中断', description: '已有内容已保留，由你决定何时继续，不会自动重新生成。' }
  if (run.status === 'queued') return { title: '等待开始', description: '学习需求已保存，准备好后会继续。你可以稍后回来查看。' }
  if (run.stage === 'research') return { title: '正在查阅参考资料', description: '结合你的目标查找和阅读网页，已取得的资料会保存在下方。' }
  if (run.stage === 'blueprint') return { title: run.blueprint_feedback ? '正在调整课程方向' : '正在设计课程方向', description: '先安排单元顺序与目标，完成后请你确认，再补充具体课时。' }
  if (run.stage === 'units') {
    const units = course?.units ?? []
    const index = units.findIndex(unit => unit.unit_id === run.current_unit_id)
    return index < 0 ? { title: '正在完善课程内容', description: '按顺序补充讲次与小节，已保存内容可以查看。' } :
      { title: `正在完善第 ${index + 1} / ${units.length} 单元`, description: units[index].title }
  }
  return { title: '正在理解你的目标', description: '准备几个真正影响课程内容的问题。' }
}
