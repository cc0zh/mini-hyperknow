# Agent 内核 V1 升级

## 目标、范围与风险

- 目标：在既有 Python 同步内核上补齐工具调度与审批、可追溯输出裁剪、受控基础工具、持久会话与显式长期记忆、按 Token 预算压缩、分层模型与用量追踪。
- 验收：直接逻辑、真实临时文件／进程／存储、真实模型工具循环及压缩验证；课程服务现有检查继续通过。不引入 Mock、Fake provider 或接口回放。
- 保持兼容：`LLMService.complete`、原有消息类型和课程四类生成工作流不改；不新增产品页面、任意命令 API、多 Agent、向量库或原生 Token 流。
- 权限：新文件工具限定显式工作区，写入与命令执行默认需审批；路径校验不是操作系统沙箱，命令经授权后拥有宿主进程权限。产品不注册这些工具。
- 持久化：内核会话为独立、可选的本地 JSONL；不替代产品 SQLite，不读取／修改已有课程数据或凭据。模型摘要不能替代原始日志，压缩失败不丢历史。
- 已有授权：本地可逆实现与验证；沿用仓库现有真实模型配置做最小内核验收，不发布、不部署、不提交 Git。已有产品范围与质量文档的未提交修改予以保留。
- 关联：[架构](../../ARCHITECTURE.md)、[模型工作流](../../design-docs/agent-workflows.md)、[真实验证](../../design-docs/real-validation.md)。方法来源为用户提供的 agent-harness-dev V1 规范，适配本仓库 Python 与显式业务工作流边界。

## 进度与决定

- [x] 核对内核、V1 清单与仓库约束；确认 Python、同步 provider 和无 Mock 验收。
- [x] 工具调度／审批／输出存档及工作区基础工具 → 21 项真实 Windows 工具检查通过，无 skip。
- [x] 会话／记忆／Token 预算与安全压缩 → 24 项上下文检查通过，真实摘要及重开通过。
- [x] 模型分层及执行循环接入 → 原 API 保持，实际工具循环两次主调用通过。
- [x] 完整回归、真实模型切片验收及文档同步 → 记录实际结果与未覆盖边界，完成归档。
- 2026-10-22：V1 继续使用同步 `complete`；不声称取消能终止在途网络请求。并行仅调度只读工具，写入与命令串行。长期记忆由调用者显式更新，不自动提取个人信息。
- 2026-10-23：真实模型验收使用同一已配置 deepseek-flash 显式分配 high／low，验证用途路由，不声称廉价 tier 或节省成本。每个完成工具结果即时写入会话，跨轮工具 ID 重复拒绝；重开补 unknown 结果不重放。
- 2026-10-23：独立审查发现并收口：turn_start 回调取消后的调用门禁、摘要请求构建后的取消检查、观察事件深拷贝、结果提交失败必须阻止后续写、NaN／非 JSON 参数及未知 finish_reason 拒绝、CR／分片 CRLF 分页。审查最终未发现剩余明确 P1／P2；静态审查不冒充独立运行验证。

## 验收与交接

- 已执行：`uv sync --frozen`／`uv lock --check` 通过，无新增依赖；首轮 `npm.cmd run ci` 通过（21 项 Node、131 项 Python，含 36 项内核）；49 项前端及 TypeScript／Vite 构建通过，保留既有大 chunk 警告。
- 最终代码回归：`npm.cmd run ci` 退出 0，21 项 Node、162 项 Python 通过；日志 `data/validation/agent-v1/final-ci.log`。其中内核 67 项（原 core 4、context 24、engine 6、LLM 边界 12、tools 21），实际临时磁盘／审批线程／rg／Windows 进程与真实本地服务，无模型替身。关闭真实 SessionStore／实际目录写失败测试证明第二个写不会发生；Windows suspended→Job→resume 测试覆盖超时、取消和父进程退出后的子树清理。
- 真实验收：`uv run --frozen python scripts/verify_agent_v1.py` 退出 0；证据 `data/validation/agent-v1/20261022T161528-e66a9a/evidence.json`（忽略目录）。真实模型从实际 UTF-8 文件取得随机 code，tool loop 共 2 轮；另调用 1 次实际摘要与 1 次摘要后主模型，合计 4 次。Provider 实测 prompt 7,116、completion 839、total 7,955 tokens，其中 summary 2,509；不是估算计费或货币金额。
- 压缩前／后保守上下文估算 12,419 → 5,522（后值含新回复）；原始 JSONL bytes 保持前缀，active 4 条／audit 9 条。关闭并重新打开 SessionStore 后两类历史一致，恢复没有模型调用。验收中的长历史为显式调用者输入，不是假模型响应。
- 后台 powershell 包装返回空日志、无法读取 task 状态，未作为命令验收依据；上述结果来自前台实际执行与本地证据文件。
- 文档与仓库门禁：文档骨架／相对链接、Markdown lint、`git diff --check`、`uv lock --check` 通过。归档后仅改文档，定向重查文档与差异，不重复收费验收。
- 未覆盖边界：真实收费网络在途硬中断、不同厂商／不同价格模型 tier、POSIX 宿主运行未验；不将 Windows 与纯函数证据扩大成这些已通过，也不重新盖章产品 V01–V12。
- 归档检查：所有本计划入链更新为 completed；长期边界已写入架构／内核 V1／安全说明；质量仅新增本任务事实，保留用户原有产品范围改动；学习记录解释 unknown outcome 与持久化屏障，不声称 exactly-once。
- 不实施发布或部署；未修改产品 SQLite 结构、已有课程数据和本地凭据。2026-10-23 用户追加授权完成后提交 commit，仅提交本次 V1 升级；仓库原有未提交产品范围／history 保留，不混入本次提交。
