# ATIF轨迹格式固定版本参考

核对日期：2026-10-26；状态更新：2026-10-29原评测框架与ATIF出口已退役。下文是当时实现和来源核验记录，不代表现行能力；现行[学习任务评测](../design-docs/backend-evaluation-pipeline.md)不导出ATIF，也不转换历史文件。当时锁定ATIF-v1.7，实现本地文字子集导出／校验并核对首份真实轨迹；未安装Harbor、运行完整上游校验器、接入AgentLoop或上传。原证据见[首切片计划](../exec-plans/completed/20261026-lightweight-backend-eval.md)。

## 固定来源

Harbor提交：`872da9479f4a2078142d22c49c9ffae0f09e2e63`。通过公开Git远端解析提交身份，并读取以下固定提交内容，不使用main作为实施依据：

| 固定链接 | 本轮核对内容 |
| --- | --- |
| [ATIF RFC](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/rfcs/0001-trajectory-format.md) | v1.7变更、根／Agent／Step／工具／观察／指标结构，版本及上下文语义 |
| [Trajectory模型](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/src/harbor/models/trajectories/trajectory.py) | 可接受版本、默认值、连续step_id、嵌套轨迹身份及同step工具引用校验 |
| [Step模型](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/src/harbor/models/trajectories/step.py) | 三种source、角色专属字段、时间格式、llm_call_count与无模型调度约束 |
| [ObservationResult模型](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/src/harbor/models/trajectories/observation_result.py) | 工具反馈及来源调用身份、extra扩展 |
| [Metrics模型](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/src/harbor/models/trajectories/metrics.py) | 可选usage、费用、采样指标与扩展字段 |
| [TrajectoryValidator](https://github.com/harbor-framework/harbor/blob/872da9479f4a2078142d22c49c9ffae0f09e2e63/src/harbor/utils/trajectory_validator.py) | 基于Pydantic的结构校验、错误收集和本地媒体存在性检查 |

选择v1.7是项目决定，不声称它是最新版本。固定提交的RFC及实现已包含v1.8，主要新增音频内容；当前产品不做音频，首轮纯文字轨迹不需要该能力。v1.7的工具／观察extra、trajectory_id及llm_call_count已满足所需表达。

## 不能忽略的参考实现边界

- 固定提交的Trajectory模型接受ATIF-v1.0至v1.8，缺省schema_version为ATIF-v1.8。项目必须显式输出并严格检查ATIF-v1.7，不能靠默认值或一次通用校验通过证明版本正确。
- 同一模型实现支持不同版本的字段，不应假设schema_version标签会自动禁止新版字段。项目出口还需按v1.7及首轮文字范围限制字段／内容，不输出audio。
- agent step可带tool_calls与observation；反馈的source_call_id必须指向同一step的tool_call_id。不存在source为tool的标准step。一次可辨识模型推理优先对应一个agent step。
- llm_call_count为0的agent step表示无模型的确定性调度，不能包含模型metrics或reasoning_content。业务提交不能伪装成一次模型推理。
- schema允许的可选字段不代表采集系统能提供。缺失usage／推理／反馈不能补零或编造；校验器不替业务核查数据完整性和事实正确性。
- 校验器接受多个版本，且以结构检查为主；本地媒体检查也不等于来源可访问、内容正确或安全。首轮不启用多模态，不引入媒体下载行为。

采用ATIF不要求安装整个Harbor或复制其代码。当时本地出口 `src/hyperknow/eval_atif.py`（现已移除，可查Git历史）使用已有Pydantic，独立定义严格文字子集，转换与校验版本均为1；不复制上游实现，不新增依赖。格式版本、规范提交、转换规则版本及本地校验器版本是四个不同标识，升级时都需留痕，不能仅修改schema_version字符串。

## AgentLoop与Claude Code接入的区别

本轮核对的阿里云官方页面属于滚动产品文档，不是固定版本的实现依据：

- [AI Coding Agent接入](https://help.aliyun.com/zh/agentloop/ai-application-access-ai-coding-agent/)：LoongSuite Pilot通过不同Agent的Hook／插件／本地数据源采集、归一化并上报；Claude Code采用Hook。采集器与ATIF格式是不同层面。
- [Agent轨迹](https://help.aliyun.com/zh/agentloop/agent-trajectories)：AgentLoop将接入的Trace加工为ATIF轨迹；页面未明确承诺支持的具体ATIF版本，也不能据此推断任意ATIF文件可直接导入。

因此，本项目先做现有后端记录到固定ATIF的本地转换，不安装Claude Code采集器来替代产品Agent的采集，不接云端。若以后需要AgentLoop消费，须另验接入通道、支持版本、字段映射和脱敏；生成合法ATIF不是该外部集成已经完成的证据。
