# 领域对象、持久化与恢复

独立即时协助的数据、事务与恢复另见[即时协助契约](instant-assistance.md)：新增assistance_conversations与assistance_artifacts两表，保持SQLite user_version=3，不将course_id改为可空或创建假课程。会话、轮次、Skill快照、生成产物及白板cursor持久化，临时作答不进入课程成绩。

状态：2026-10-22 基线。v3 题组、尝试、目标版本及确定性计分已实现；实现与验证程度见[质量状态](../QUALITY_SCORE.md)。思考题与成果提交仍为后续目标。
关联：[产品设计](product-design.md)、[交互状态](learning-experience.md)、[接口](api-and-events.md)。

## 1. 唯一事实来源

新增独立网页调研沿用现有v3表：kind=research的run在input保存goal/context，在research保存steps/sources/report；来源URL、摘录及抓取元数据随运行持久化，实际模型轮次仍写model_calls。不自动创建或修改课程，不为本轮改变PRAGMA版本；完整来源／重试契约见[网页调研 Agent](web-research-agent.md)。

业务事实保存到单个本地 SQLite 文件，默认 `data/hyperknow.sqlite3`，已支持 `HK_DATA_DIR` 改变本地数据根。

当前小型 course/run、讲义、课堂状态、问答及完成事实以主键加完整 JSON 保存；讲义／问答另有 session_id 列，版本与状态在真实事务中检查。命令回执保存输入指纹、资源类型和引用。后续有明确查询需求再细化普通列，不先引入 ORM、独立文档存储、向量库或 JSONL 事件溯源。SQLite 是权威业务数据，不是可删除查询缓存。

## 2. 领域对象

当前分阶段课程新增结构状态、蓝图版本、当前创建run引用以及单元生成状态；部分目录允许空lectures／exams／project_stages且progress=null。蓝图确认／修改与局部保存边界见[蓝图工作流](course-blueprint-workflow.md)；不迁移旧课程，也不在run另存第二份可改目录。研究仍随run保存，既有表与PRAGMA v3不变。

当前已落地 Course、BoardScript／BoardStep、LessonProgress、课堂聚合、Interaction、ActivityProgress、GenerationRun；本阶段新增Quiz、QuizAttempt、QuizResult。ProjectSubmission与思考题反馈仍为目标，不因列出对象即表示已有表或端点。

| 对象 | 必需内容与不变量 |
| --- | --- |
| Course | 稳定 ID、标题、简介、原始目标、澄清快照、语言、难度、标签、课程结构及版本 |
| Unit | 稳定 ID、标题、说明、顺序；包含 Lecture、Exam、ProjectStage 引用 |
| Lecture | 稳定 ID、标题、说明、顺序；包含一个或多个 Session |
| Session | 稳定 ID、标题、说明、大纲、要点、顺序；时长若有仅是估计，不伪称实测 |
| Exam | 稳定 ID、所属单元、目标与范围；不内置无证据的通过线 |
| Project / ProjectStage | 课程目标／最终成果，及各阶段要求、所属单元、顺序和交付增量 |
| BoardScript / BoardStep | 单一schema_version=2：objectives、roadmap及来源索引；稳定step_id、stage、keypoint_id、focus_ids、check、讲解、page／column与有object_id的视觉操作；不兼容旧脚本 |
| LessonProgress | script_id、最近确认可展示的 cursor、play_intent、独立 version 及 updated_at；讲到不等于课时完成 |
| LessonSnapshot | 课堂聚合顶层version、课时及课程上下文、script、progress、interactions、generation_run、completed、format_error；不支持的旧脚本不混入新类型 |
| LessonInteraction | 问题或check回答及模型反馈、interaction_id／run_id／script_id、教学cursor／step_id、查看anchor_step_id／anchor_object_id、was_playing、状态、错误和时间；无掌握评分 |
| Quiz | 稳定题组版本、目标类型及 ID、有序问题、选项、答案集合、解释和来源内容引用 |
| QuizAttempt | 题组版本、有序作答／跳过、用时、当前位置、提交状态、个人汇总结果及计分版本 |
| ProjectSubmission | 项目阶段、文字／链接、保存时间、提交身份；不含虚构评审结果 |
| ActivityProgress | course_id、type=session或exam、completed_at，活动ID为主键；手动完成／练习submit完成课时，考核submit完成exam，项目完成仍未实现 |
| GenerationRun | kind为course／lesson／question／quiz，保存输入快照、阶段状态、目标／结果引用、错误、父重试及有效模型；quiz另含quiz_id、target_type与target_id |

课程结构 JSON 保存单元／讲座／课时／考核／项目定义。不要在另一张表再保存一份可独立修改的课程目录。其内部 ID 的归属和唯一性由结构校验及应用事务共同保证。

## 3. 当前物理记录与后续建议

首切片 v1 的四表保留；本阶段 `PRAGMA user_version=3`，JSON 内容的 schema_version 与数据库迁移版本不是同一个值。v1 → v2 **新增四张表，不是五张**，另新增索引与命令回执字段；课堂进度没有独立 lesson_progress 表，而在 lesson_states.data 内。

### 保留的八张既有表

| 表 | 权威内容 | 关键唯一性／关系 |
| --- | --- | --- |
| `courses` | 元数据、需求与澄清、结构 JSON、schema_version、version | course_id；活动内部 ID 在结构内唯一 |
| `runs` | 造课／讲义／问答／出题运行及结果引用；目标generation_runs的当前实际名称 | id=run_id；按kind保存course_id、session_id或quiz目标等引用 |
| `command_receipts` | id、fingerprint、run_id、resource_type | client_command_id 主键；run_id 列在 resource_type=session 时实际存 session_id，同 ID 异输入冲突 |
| `model_calls` | id、run_id、data；实际输入依据／响应、配置、用量和错误 | call_id；关联 run_id，不保存凭据 |
| `lesson_scripts` | id、session_id、完整脚本 data，含 content_version 与 schema_version | script_id 主键，session_id UNIQUE；当前每课最多一个不可变脚本，content_version=1 |
| `lesson_states` | id=session_id，data={version, progress} | 课堂聚合版本与 progress.version 分开保存；没有独立 lesson_progress 表 |
| `lesson_interactions` | id、session_id、问题／回答及状态 data | interaction_id 主键；interactions_session 索引；锚点 script_id／step_id／cursor 在 JSON 内 |
| `activity_progress` | id=活动ID，data含course_id、type、completed_at | 课时手动完成、练习提交及考核提交写入；存在记录即完成，不表示通过／掌握 |

迁移已有 v1 库前，使用 sqlite3.Connection.backup 建立 `<数据库名>.v1-backup_*.bak` 一致备份（含已提交 WAL 数据），再在事务中建上述四张课堂表、interactions_session 索引并给 command_receipts 加 resource_type，默认 run；旧 run 补 kind=course 及空课堂引用。这是既有v1→v2迁移步骤；当前新库会继续顺序建到v3，高于v3才拒绝打开，不降级或清空。升级前仍须停止旧服务。

### v3新增记录

本阶段新增三张表，合计十一张；沿用v2的八张表，不另存一份课程目录。已有v2库在升级前自动SQLite backup，事务新增结构；新库从0顺序建到v3，高于v3拒绝打开。既有run无需为可选quiz字段重写JSON。

| 表 | 权威内容与约束 |
| --- | --- |
| `quizzes` | id、target_type、target_id、完整题组data；UNIQUE(target_type,target_id)，每活动一份不可变题组 |
| `quiz_states` | id=`practice:{session_id}`或`exam:{exam_id}`、data.version；覆盖出题／作答目标变化 |
| `quiz_attempts` | id、quiz_id、status、完整attempt data；部分唯一索引限制每题组一个in_progress尝试 |

Quiz保存3–8道single／multiple／boolean题，必须同时覆盖三型。每题选项／答案集合有效、解释非空、来源引用限本次输入allowed_source_refs；练习依据实际script与step，考核允许unit／session大纲及预算内已缓存script。

Attempt绑定固定quiz_id与scoring_version，保存cursor、question_started_at、逐题答案／跳过／elapsed_ms／correct／fast／points和最终result。answer保存后不推进，next才更新cursor与下一题起点；已判定答案不可改写。用时是客户端记录，不建设防作弊；刷新及命令重试不得重置已保存起点或原请求时长。elapsed_ms只接受0–86,400,000的整数，拒绝布尔／浮点／字符串；超过24小时由界面明示按24小时截断。

### 后续目标记录

以下不是现有数据库表。未来若支持主动重生成，应扩展脚本历史保存和唯一性设计；当前 UNIQUE(session_id) 并不支持每课多版本并存。

| 目标记录 | 权威内容 | 关键唯一性／关系 |
| --- | --- | --- |
| `project_submissions` | 成果正文和所属阶段 | submission_id；允许主动再次提交，展示最近记录 |
| 思考题反馈与项目完成 | 实际思考答案／反馈，以及项目完成依据 | 具体表结构随功能实施，不冒用当前问答记录已支持全部类型 |

先用简单显式 SQL 和事务，不要求每张表配独立服务或通用仓储基类。题量小，逐题保存整个小型答案 JSON 可接受，不为未知规模提前拆分大量表。

## 4. 状态与版本

- Course 的 schema_version 表示 JSON 结构，version 表示记录修改；当前无课程结构编辑，课时手动完成及首次练习／考核完成只提升记录版本，不无声替换目录。
- Script生成后重入读取同一版本，不因刷新调用模型。显式regenerate建立新run，旧脚本原字节保存在run.previous_script_data，成功前当前脚本不动，成功后切换新script_id并恢复cursor=-1；不迁移旧协议、不清库。Quiz仍不可变且再练复用同一版本。
- Attempt 保存 `in_progress` 或 `submitted`。全题已答／跳过后，用户点击“看结果”显式提交；汇总结果和相关完成标记同事务写入，最后一次保存答案本身不自动提交。
- LessonProgress 初始 script_id=null、cursor=-1、play_intent=paused、version=1；生成讲义后关联脚本，cursor 仍为 -1。cursor 只允许保持或 +1，后端确认后前端才展示步骤；页栏回看不会倒退确认位置。
- 课堂快照顶层 version 是 session 资源的聚合版本，run 变化、问答 ready 等也会提升；progress.version 由脚本／位置／播放意图写事务更新（提问或完成写入暂停也会更新），不是每次回答状态改变都更新。课堂命令的 expected_version 取 progress.version，WS 与完整快照排序取顶层 version，不能混用。
- GET 保留权威 play_intent，不在相同版本下改写成 paused；新建／恢复前端本地时钟始终暂停，与持久化播放意图分离。暂存命令身份及继续确认在 sessionStorage，不替代 SQLite 业务事实；输入草稿和回看页栏不承诺崩溃恢复。
- run 更新检查自己的 expected_version；已有聚合冲突时读取新快照，不静默覆盖另一页结果。同命令重试读取已保存资源的当前快照，避免重复生成或提交。
- GenerationRun 使用[交互状态](learning-experience.md)的 queued、clarifying、awaiting_answers、generating、ready、failed、cancelled、interrupted；不同生成类型只经过适用的状态。

## 5. 保存屏障与事务

| 用户可见确认 | 必须已经提交的内容 |
| --- | --- |
| 创建请求已接收 | 原始目标、run、命令回执 |
| 澄清已提交 | 问题与文字答案快照、run 新阶段 |
| 课程就绪 | 完整且校验成功的 Course、run 结果引用及 ready |
| 讲义就绪 | 不可变 BoardScript、lesson run 引用及 ready、script_id 关联与初始暂停位置 |
| 教学步骤可展示／已保存 | 脚本引用、确认 cursor 和新版本；前端不先乐观展示再补确认 |
| 问题已发送 | 用户问题及锚定位置、对应 run；模型回答稍后单独提交 |
| 回答已完成 | 回答正文和状态、相关 run 结束信息 |
| 课时手动完成 | activity_progress 记录、Course 版本及课堂暂停状态；同一已完成课时不重复计数 |
| 答题已判定 | 实际选择／跳过、用时、判定与attempt版本；cursor与question_started_at保持不变，反馈可刷新恢复 |
| 下一题可作答 | 前题已保存，next持久化新cursor、question_started_at与版本 |
| 练习／考核已提交 | 全题答案／跳过、汇总结果、ActivityProgress与Course版本同事务；已完成课时不重复增长，考核全错也记已提交而非通过 |
| 项目阶段已完成（未来） | 非空成果正文、ActivityProgress，以及 Course 版本更新 |

当前课程列表、详情与课堂继续入口从 `activity_progress` 与目录由 derive_course 同一函数派生完成状态、课时比例和 next_item，不另存可独立修改的进度。按单元先找未完成课时，再项目阶段、考核；考核已有作答／提交端点，项目仍只有目录定义。首次课时手动完成、练习完成课时或考核完成提升父课程版本；已完成课时再交练习不重复提升，考核完成不改变课时比例。所有入口读取同一派生结果；未开放项目若为next_item明确提示，不伪造可提交页面。

模型调用和 WebSocket 发送不持有数据库长事务。状态提交成功后才推送通知；通知失败不撤销已经保存的业务数据，重连按快照恢复。

## 6. 计分与时间

本阶段Quiz／Attempt使用本节确定性算法，真实业务验收见[完成计划](../exec-plans/completed/20261022-real-practice-exams.md)；算法检查不替代真实模型出题或浏览器作答。

已核对原站共享算法的证据是 `hyperknow-clone2/recon/pretty/quizScoring-CUGhpPfb.pretty.js`。本项目沿用以下个人计分，不保留伪对手：

- 答对基础 600；用时 ≤10,000ms 的快答额外 200；连击奖励为本题前连续答对数 × 100，上限 400。
- 答错或跳过重置连击。未作答不提前计为错。
- 正确率达到 80%／55%／25% 分别为 3／2／1 星，否则 0 星。
- 另按满分差值与得分比例计算星级，最终取两条路径较大值；完美满分为每题基础＋快答＋对应连击奖励之和。
- 第二路径：满分差值 ≤ 0 为 3 星；差值 = 1 或得分比例 ≥ 80% 为 2 星；比例 ≥ 50% 为 1 星，否则 0 星。空题组不产生正常成绩。

服务端使用实际作答重新计算，不信任前端上传的总分。客户端保留实际作答用时／起点用于快答语义，刷新不重置已保存记录；这是个人使用记录，不建设防作弊或可信考试系统。

算法直接调用真实score_answers检查实际数值与边界，不使用Mock结论；题目结构与存储测试不能代替真实出题成功。

## 7. 恢复与数据维护

课程支持显式硬删除：以课程version检查并在单个事务内清理courses、所属lesson_scripts／lesson_states／lesson_interactions、activity_progress、quizzes／quiz_states／quiz_attempts、关联runs及model_calls。关联运行包含创建run的父重试链及后继，课程研究来源／过程／报告随run一起清除；独立调研和其他课程保留。仍在排队、生成或等待答案／蓝图确认的关联任务必须先取消。已取消线程的晚到结果因run不存在不能提交，model_calls也仅在run仍存在时保存，避免删除后重建孤立证据。

command_receipts保留输入指纹与资源引用，阻止旧命令重放重新创建数据；资源已删除的旧命令返回404。删除命令使用resource_type=course_deletion，run_id列存course_id，允许同ID／输入在删除后及重启后返回`{course_id, deleted:true}`，同ID异输入仍409；新命令删除不存在的课程返回404，不写成功回执。不增加表或改变PRAGMA版本。

刷新恢复读取数据库快照；进程重启将 queued、clarifying、generating 的未终结运行标为 interrupted，不自动再发模型请求。awaiting_answers 可重新展示并由用户继续；ready 读取已保存结果。

当前讲义／问答在途被打断会留下 interrupted，问答 Interaction 随 run 状态更新，不留永久 loading；用户重试创建新 run，仍复用原场景输入与模型。问答重试复用 interaction_id 但更新 run_id，旧 run 晚到回答不得覆盖新运行。已有讲义／题组／作答与结果均直接恢复。quiz同样采用取消／重试／中断事务门禁，GET不自动出题或新建尝试；历史URL固定attempt，不因再练改看最新结果。已保存状态冷重启有真实证据，真实quiz调用在途硬重启仍未覆盖。

首版不迁移 Clone 的真实用户库，不导入其账号、token 或样本个人数据。当前数据库迁移用有序 SQL 和 PRAGMA user_version，与 JSON schema_version 区分；已有v1／v2升级前自动一致备份，不能为修复测试直接清空用户数据。

手动备份在服务停止后复制 SQLite 文件；不声称只复制运行中的主文件即可覆盖所有模式下的完整数据。首版不建设自动备份平台或完整导入导出界面。
