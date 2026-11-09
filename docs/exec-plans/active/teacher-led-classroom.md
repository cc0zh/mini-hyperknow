# 教师 Agent 驱动的单课白板课堂

## 目标、范围与风险

- 目标与验收标准：课前保存有来源、可追溯的 `TeachingBasis`；课堂每个教学回合由 Teacher Agent 根据目标、依据、已发生教学、当前白板和学生最新回答选择讲解、示范、追问、检查或调整；白板操作通过真实工具调用校验、执行和保存；模型/工具内部轮次与对学生可见的教学回合分开；程序限制记录为明确的运行停止原因。
- 包含与不包含：包含课堂提示词、课前依据 schema、教师回合状态、白板工具、相关 API/前端状态和真实验证；不包含教师结束课堂的权限取舍、不决定旧课堂数据如何迁移/清理、不扩展整门课程自适应重排或新的单课自主预算产品策略。
- 风险及缓解：旧 `lesson_scripts` 与已保存课堂数据不删除、不自动转换；新教师协议使用独立状态字段和命令。现有 SQLite 命令收据、版本、单 worker、取消/重启/晚到提交屏障继续复用。模型质量和学习效果不以 schema 或 ready 状态替代，必须保留真实输入、工具动作、回合和持久化证据。
- 已有授权与需要确认的边界：本地代码、测试、隔离数据库和真实浏览器验证已授权；真实模型调用可能产生费用但仅使用隔离目录。教师结束权限、单课预算数值和旧数据处置在交付中单列为待用户决定，不自行扩大范围。
- 关联设计文档、产品 spec 或质量项：`docs/design-docs/learning-experience.md`、`docs/design-docs/agent-workflows.md`、`docs/design-docs/data-model.md`、`docs/design-docs/api-and-events.md`、`docs/design-docs/real-validation.md`、`.agents/skills/verify-classroom-flow/SKILL.md`。

## Ground：已证实事实与待验证假设

### 已证实

- `prepare_lesson()` 当前把 `lesson_context()` 送入一次 `BoardScriptDraft` 请求；`BoardScriptDraft` 强制 opening first、summary last、每个 keypoint 依序 explain/example、至少一个 check 和全部要点覆盖。
- `save_progress()` 只允许数组 cursor 保持或前进一项；前端 `use-lesson-player.ts` 用单一播放时钟自动确认下一项。`questions` 使用 `LessonAnswer`，只能生成不修改主讲义的文本反馈。
- 产品请求实际走同步 `OpenAIService.complete(AgentContext)`，课堂请求不带工具；通用 `agent_core.engine.run_agent_loop()` 已实现模型消息、tool calls、`ToolScheduler`、tool results 回填和有界轮次。
- 白板安全渲染和布局由 `Board.tsx`、`board-scene.ts` 负责；对象引用、公式、Mermaid、代码转义等程序边界已有实现。
- SQLite 的 runs、model_calls、lesson_states、lesson_scripts、lesson_interactions 与 command receipts 已承担持久化、幂等、版本、取消/重启和晚到结果门禁。
- 旧课堂计划明确记录一次生成完整讲义、不兼容旧协议、保护用户数据；这些是数据/兼容边界，不代表新课堂仍必须采用固定教学顺序。

### 待验证假设

- 现有内容显得像“流程播放”可能同时来自固定顺序、课前脚本冻结、前端自动播放和真实样本教学内容不足，不能先归因于提示词。
- 真实模型是否会在相同状态下对正确、关键误解、明确困惑和无需调整的回答做稳定且可解释的不同决策，需要固定输入并记录多次真实结果；单次随机文本差异不算适应。
- 现有白板安全操作类型足以承载增量教师回合，仍需验证批量操作、重复引用、工具失败和回合中断下的保存屏障。

## Sketch：候选与综合决定

候选 A 是“单一教师回合服务”：课前生成依据，`start_teacher_turn()` 组装上下文并运行一个带 `whiteboard_present` 工具的 Teacher Agent；工具在内存账本上校验，最终回合成功后原子提交白板和回合。候选 B 是“事件日志驱动课堂”：每个模型/工具事件先写入独立事件记录，再从事件折叠出当前白板和回合。A 的调用方只知道准备依据、提交学生回答、读取快照三个动作，隐藏了内部模型/工具轮次；B 的恢复与审计更强，但会把事件协议、折叠规则和并发语义暴露给产品层，接口更浅且调用链更深。

综合决定采用 A：新增教师域类型和一个深的 Teacher Agent 入口，复用现有 `runs`/`model_calls`/`lesson_states`/command receipts，不新建通用事件溯源。白板工具只修改本回合的受校验临时账本，最终答复成功后与 `TeacherTurn` 一起事务提交；失败或取消不把未完成回合的临时操作展示为已确认板书。旧 `lesson_scripts` 保留为历史数据，新的教师协议通过显式 `teacher` 状态字段运行。

调用方草图：

```text
prepare_teacher_lesson(session_id, command_id)
  -> LessonSnapshot(protocol="teacher_led", basis, board, turns, pending_run)

start_teacher_turn(session_id, command_id, expected_version, student_answer?)
  -> one TeacherTurn committed after 0..N internal LLM/tool rounds
  -> snapshot.board and snapshot.teacher_turn updated atomically
```

草图类型：

```text
TeachingBasis:
  objectives: string[]
  knowledge: EvidenceItem[]
  examples: EvidenceItem[]
  derivations: EvidenceItem[]
  misconceptions: EvidenceItem[]
  teaching_options: TeachingOption[]
  references: SourceRef[]                 # server-resolved claim/evidence refs

TeacherBoard:
  version: int
  operations: BoardOperation[]             # one validated object namespace

TeacherTurn:
  turn_id, run_id, index
  student_answer: string | null
  action: explain | demonstrate | ask | check | adapt | summarize | continue
  response: string
  student_prompt: string
  awaits_student: bool
  board_object_ids: string[]
  basis_refs: string[]
  created_at: string

TeacherState:
  status: ready | generating | awaiting_student | stopped | failed
  version, turn_index, board, turns, stop_reason
```

程序校验保留：目标/来源引用、白板 operation schema、对象 ID 唯一性、引用只能指向当前或本回合已出现对象、HTTP 权限、命令幂等、乐观版本、单回合工具轮次上限、取消/重启/迟到提交门禁。删除：opening/explain/example/check/summary 必经顺序、数组 cursor 推进、前端阅读时钟决定教学进度、check 必须存在、所有 keypoint 必须按序讲完以及问题只能生成“主讲义外”答疑。

## Implement：进度与决定

- [x] 新增教师依据/回合/白板账本 schema 与上下文装配，并要求目标和依据条目引用允许来源
- [x] 接入真实 Teacher Agent、`whiteboard_present` 工具和工具轮次审计；工具 schema 使用 provider 兼容的扁平 JSON Schema
- [x] 新增教师课堂状态/API，保留旧讲义数据且不自动转换
- [x] 将课堂前端改为回合式交互，保留现有白板渲染和视觉风格
- [x] 删除新生产路径中的固定脚本推进约束，补充直接规则/HTTP/前端验证；旧路径仍保留兼容
- [x] 更新设计文档、真实验收边界、README、质量状态和 history

## 验收与交接

- 已执行的命令及结果：`uv run --frozen python -m unittest discover -s tests` 已通过此前全套 452 项；教师协议测试、Python 编译、`npm --prefix web run typecheck`、`npm --prefix web test` 已通过。真实模型验收最终保留于 `data/validation/teacher-led-classroom-real-7/`：真实 `deepseek-flash` 生成 5 条来源依据、4 个学生回答回合、8 次白板工具调用并保存 11 个累计对象；同命令幂等、取消停止原因、retry 命令、冷重启读取和源库 hash 均有记录。`npm --prefix web run test:browser -- teacher-classroom.spec.ts` 在该隔离库通过。
- 未执行的检查、阻塞和遗留事项：教师真实 retry 本次为显式取消，`retry_completed=false`；retry 的新版本最终提交由 SQLite 协议测试覆盖，仍需后续真实 provider 完成回合验证。真实回合不能证明学生掌握或学习效果。旧课堂数据处置、教师结束权限和单课自主预算等待用户决定。
- 必要的复验方式：使用隔离 SQLite 和真实前后端，在同一课前依据/同一课堂状态分别提交正确解释、关键误解、明确困惑和无需调整的回答；保存模型输入、工具调用、白板动作、教师回合、run/model_calls 与刷新/中断/重试后的快照，检查适应不是随机差异。
- 归档前检查：更新受影响设计文档和历史索引；只在质量状态事实变化时更新 `QUALITY_SCORE.md`；不重新创建已删除的 `docs/exec-runs/20261109-teacher-led-classroom/`。
