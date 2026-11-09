export const title = '有预算的网页调研';
export const state = v => v.steps > 10 ? '工具调用超过十次' : ['cancelled','failed','interrupted'].includes(v.phase) ? '调研已停止' : v.phase !== 'generating' ? ({queued:'调研排队',ready:'报告与证据已保存'}[v.phase]) : v.pageRead ? v.searched ? '已搜索并读取原文，可生成报告' : '已有原文，仍需有效搜索' : v.searched ? '找到候选来源，等待读取' : '等待有效搜索结果';
export const step = action => ['Cancel','Fail','Restart'].includes(action) ? '任务停止或用户取消' : ({Start:'开始调研',Search:'搜索找到候选来源',SearchFails:'搜索失败，仍消耗预算',ReadPage:'成功读取并保存原文',Finish:'合法报告通过校验后保存',Done:'保留结果'}[action] ?? action);
export const group = v => v.phase === 'ready' ? 'done' : v.steps > 10 || ['failed','cancelled','interrupted'].includes(v.phase) ? 'stop' : 'work';
export const colors = {done:'teal',stop:'orange',work:'blue'};
