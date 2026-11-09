export const title = '逐题作答与显式提交和结果保存';
export const state = v => v.phase === 'submitted' ? v.answers === 2 ? '结果与完成记录已保存' : '未答完就保存了结果' : v.phase === 'in_progress' ? v.answers === 2 ? '末题反馈，等待你提交' : v.answers > v.cursor ? '本题反馈，等待下一题' : v.cursor === 0 ? '回答第一题' : '回答第二题' : ['queued','generating'].includes(v.phase) ? '正在准备题组' : ['failed','cancelled','interrupted'].includes(v.phase) ? '出题已停止，等待重试' : ({unprepared:'进入练习或考核，只读',ready:'题组已保存，等待开始'}[v.phase]);
export const step = action => ['Cancel','Fail','Restart'].includes(action) ? '任务停止或用户取消' : ({Prepare:'明确准备题组',Start:'开始出题',SaveQuiz:'保存不可变题组',BeginAttempt:'明确开始作答',Answer:'保存答案或跳过，停留反馈',NextQuestion:'明确进入下一题',Submit:'明确看结果，事务计分并保存',Retry:'明确重试出题',Done:'停留结果页'}[action] ?? action);
export const group = v => v.phase === 'submitted' ? 'done' : v.phase === 'in_progress' ? 'input' : ['failed','cancelled','interrupted'].includes(v.phase) ? 'stop' : 'work';
export const colors = {done:'teal',input:'yellow',stop:'orange',work:'blue'};
