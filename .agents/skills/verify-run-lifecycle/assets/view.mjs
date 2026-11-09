export const title = '任务命令与取消和显式重试';
const labels = {new:'尚未提交',queued:'任务排队',generating:'正在生成',ready:'结果已保存',cancelled:'已取消',failed:'生成失败',interrupted:'重启后已中断'};
export const state = v => v.conflictingReply ? '错误地接受了同标识的不同命令' : labels[v.phase];
export const step = action => ({Create:'提交命令',Start:'开始实际调用',Finish:'事务保存结果',ReplayDifferent:'重发同标识的不同内容',Cancel:'显式取消',Fail:'生成失败',Restart:'服务重启',Retry:'显式重试，新建任务'}[action] ?? action);
export const group = v => ['failed','cancelled','interrupted'].includes(v.phase) || v.conflictingReply ? 'attention' : 'normal';
export const colors = {normal:'blue',attention:'orange'};
