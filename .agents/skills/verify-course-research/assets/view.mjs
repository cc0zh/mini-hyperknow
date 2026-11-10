export const title = "课程停止与继续生成";
export const state = (v) => {
  const entries = Object.entries(v.units);
  const damaged = entries.some(([id, unit]) => {
    const saved = v.snapshots[id];
    return saved.generation_status !== "uncommitted" && (unit.generation_status !== "ready" ||
      unit.unit_id !== saved.unit_id || unit.payload !== saved.payload);
  });
  if (damaged) return ["接续生成", "重试重置了已保存单元"];
  const ready = entries.filter(([, unit]) => unit.generation_status === "ready").length;
  if (v.structureStatus === "ready") return "课程全部保存完成";
  const stopped = v.runStatus[v.owner] === "stopped";
  const phase = v.owner === "parent" ? (stopped ? "原任务已停止" : "原任务生成") :
    (stopped ? "接续任务已停止" : "接续生成");
  return [phase, `已保存${ready}个单元`];
};
export const step = (action) => {
  if (action.startsWith("BeginUnit")) return "开始未保存单元";
  if (action.startsWith("FinishUnit")) return "保存完整单元";
  if (action.startsWith("Stop")) return "停止当前任务";
  if (action.startsWith("Retry")) return "显式继续剩余内容";
  return "保持保存状态";
};
