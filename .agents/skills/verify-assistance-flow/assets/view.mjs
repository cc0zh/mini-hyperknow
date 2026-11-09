export const title = '独立即时协助与可选产物';
export const state = v => v.saved > 1 ? '一轮错误地保存多个产物' : v.phase === 'ready' ? v.saved ? '回复与一个产物同时保存' : '回复已保存，无需产物' : ({idle:'独立会话，可直接提问',queued:'教学轮次排队',generating:'正在教学，产物尚未提交',cancelled:'已取消，未保存本轮回复',failed:'本轮失败，未提交产物',interrupted:'重启后本轮已中断'}[v.phase]);
export const step = action => ({Send:'发送问题或明确继续',Start:'开始教学',ReceiveDraft:'得到尚未保存的候选结果',Commit:'校验并原子保存回复和可选产物',Cancel:'显式取消',Fail:'生成或校验失败',Restart:'服务重启',Retry:'显式重试当前失败轮次',Done:'保留已保存记录'}[action] ?? action);
export const group = v => v.phase === 'ready' ? 'done' : ['cancelled','failed','interrupted'].includes(v.phase) || v.saved > 1 ? 'stop' : 'work';
export const colors = {done:'teal',stop:'orange',work:'blue'};
