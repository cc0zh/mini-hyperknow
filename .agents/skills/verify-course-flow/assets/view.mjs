export const title = '从学习目标到可学习的课程';
const labels = {queued:'目标已提交',clarifying:'分析学习需求',awaiting_answers:'等待必要澄清',research:'搜索并阅读资料',blueprint:'生成全局蓝图',awaiting_blueprint:'等待你确认蓝图',units:'逐单元展开并保存',ready:'课程结构就绪',cancelled:'已取消',failed:'生成失败',interrupted:'重启后已中断'};
export const state = v => v.phase === 'ready' && v.finished < 2 ? '只展开部分单元却宣布就绪' : ['cancelled','failed','interrupted'].includes(v.phase) ? '任务已停止，需显式重试' : labels[v.phase];
export const step = action => ['Cancel','Fail','Restart'].includes(action) ? '任务停止或用户取消' : ({Start:'提交学习目标',NeedAnswers:'需要补充信息',NoQuestions:'无需澄清，直接调研',Answer:'提交澄清答案',ResearchDone:'调研报告已保存',SaveBlueprint:'保存蓝图草案',Adjust:'反馈调整，补充调研',Approve:'明确批准蓝图',BeginUnit:'开始下一单元',FinishUnit:'保存单元，全部完成后就绪',Done:'保持当前结果'}[action] ?? action);
export const group = v => v.phase === 'ready' ? 'done' : ['awaiting_answers','awaiting_blueprint'].includes(v.phase) ? 'input' : ['failed','cancelled','interrupted'].includes(v.phase) ? 'stop' : 'work';
export const colors = {done:'teal',input:'yellow',stop:'orange',work:'blue'};
