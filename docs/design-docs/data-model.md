# 领域对象、持久化与恢复

状态：2026-10-22 课程、运行、回执和调用记录已实现；下述课堂、作答、成果记录仍为后续目标。
关联：[产品设计](product-design.md)、[交互状态](learning-experience.md)、[接口](api-and-events.md)。

## 1. 唯一事实来源

业务事实保存到单个本地 SQLite 文件，默认 `data/hyperknow.sqlite3`，已支持 `HK_DATA_DIR` 改变本地数据根。

当前小型 course/run 以主键加完整 JSON 保存，版本与状态在真实事务中检查；命令回执和调用关联有独立索引键。后续有明确查询需求再细化普通列，不先引入 ORM、独立文档存储、向量库或 JSONL 事件溯源。SQLite 是权威业务数据，不是可删除查询缓存。

## 2. 领域对象

| 对象 | 必需内容与不变量 |
| --- | --- |
| Course | 稳定 ID、标题、简介、原始目标、澄清快照、语言、难度、标签、课程结构及版本 |
| Unit | 稳定 ID、标题、说明、顺序；包含 Lecture、Exam、ProjectStage 引用 |
| Lecture | 稳定 ID、标题、说明、顺序；包含一个或多个 Session |
| Session | 稳定 ID、标题、说明、大纲、要点、顺序；时长若有仅是估计，不伪称实测 |
| Exam | 稳定 ID、所属单元、目标与范围；不内置无证据的通过线 |
| Project / ProjectStage | 课程目标／最终成果，及各阶段要求、所属单元、顺序和交付增量 |
| BoardScript / BoardStep | 不可变脚本版本、稳定 stepId、讲解、视觉操作、可选思考题；步骤引用完整 |
| LessonProgress | 脚本版本、最近确认展示步骤、播放状态／意图、保存版本；讲到不等于课时已完成 |
| LessonInteraction | 所属课时、类型、问题、学生回答／插话、模型反馈、状态、锚定步骤和时间 |
| Quiz | 稳定题组版本、目标类型及 ID、有序问题、选项、答案集合、解释和来源内容引用 |
| QuizAttempt | 题组版本、有序作答／跳过、用时、当前位置、提交状态、个人汇总结果及计分版本 |
| ProjectSubmission | 项目阶段、文字／链接、保存时间、提交身份；不含虚构评审结果 |
| ActivityProgress | 活动类型／ID、完成状态、完成依据和时间；nextItem 的输入事实 |
| GenerationRun | 生成类型、输入快照、阶段状态、目标引用、结果引用、错误、父重试及有效配置 |

课程结构 JSON 保存单元／讲座／课时／考核／项目定义。不要在另一张表再保存一份可独立修改的课程目录。其内部 ID 的归属和唯一性由结构校验及应用事务共同保证。

## 3. 当前物理记录与后续建议

首个切片已建 `courses(id,data)`、`runs(id,data)`、`command_receipts(id,fingerprint,run_id)`、`model_calls(id,run_id,data)`，`PRAGMA user_version=1`，Course JSON 含 schema_version。目标 generation_runs 在当前实现名为 runs；其他表尚未创建，不得将下表视为现有数据库全表清单。

| 表 | 权威内容 | 关键唯一性／关系 |
| --- | --- | --- |
| `courses` | 元数据、需求与澄清、结构 JSON、schema_version、version | course_id；活动内部 ID 在结构内唯一 |
| `generation_runs` | 造课／讲义／出题／问答运行及结果引用 | run_id；course 生成成功最多绑定一个 course_id |
| `lesson_scripts` | 经过校验的完整步骤 JSON、生成及 schema 版本 | script_id；session_id + content_version |
| `lesson_progress` | 确认步骤、脚本引用、暂停／恢复意图 | course_id + session_id；不重复存完成标记 |
| `lesson_interactions` | 插话、思考作答、回答和状态 | interaction_id；锚定 session_id / step_id |
| `quizzes` | 完整题组 JSON 和对应讲义／大纲版本 | quiz_id；版本不可就地重写 |
| `quiz_attempts` | 小型作答 JSON、当前题、用时与汇总 | attempt_id；固定 quiz_id 和 scoring_version |
| `project_submissions` | 成果正文和所属阶段 | submission_id；允许主动再次提交，展示最近记录 |
| `activity_progress` | 课时／考核／项目完成事实 | course_id + activity_type + activity_id |
| `model_calls` | 场景、实际输入依据／响应、配置、用量和失败 | call_id；关联 run_id，不保存凭据 |
| `command_receipts` | 重复点击／网络重试的命令 ID、输入指纹与结果引用 | client_command_id；同 ID 异内容报冲突 |

先用简单显式 SQL 和事务，不要求每张表配独立服务或通用仓储基类。题量小，逐题保存整个小型答案 JSON 可接受，不为未知规模提前拆分大量表。

## 4. 状态与版本

- Course 目录结构版本与记录修改版本分开；首版不提供课程结构编辑，因此不会在用户学习时无声替换目录。
- Script 和 Quiz 内容版本不可变。生成后重入读取同版本，不因刷新重新调用模型；未来主动重新生成必须新建版本，旧结果仍可解释。
- Attempt 保存 `in_progress` 或 `submitted`。全题已答／跳过后，用户点击“看结果”显式提交；汇总结果和相关完成标记同事务写入，结果页读取该事实。最后一次保存答案本身不自动提交。
- LessonProgress 保存最后成功确认展示的步骤。未提交的动画、输入草稿和正在回看的页栏不承诺崩溃恢复。
- 所有可变聚合有整数 version；更新检查 expected_version。多标签页产生冲突时读取新快照，不静默覆盖另一页已保存结果。
- GenerationRun 使用[交互状态](learning-experience.md)的 queued、clarifying、awaiting_answers、generating、ready、failed、cancelled、interrupted；不同生成类型只经过适用的状态。

## 5. 保存屏障与事务

| 用户可见确认 | 必须已经提交的内容 |
| --- | --- |
| 创建请求已接收 | 原始目标、run、命令回执 |
| 澄清已提交 | 问题与文字答案快照、run 新阶段 |
| 课程就绪 | 完整且校验成功的 Course、run 结果引用及 ready |
| 教学步骤已保存 | 脚本引用、确认 cursor 和新版本 |
| 问题已发送 | 用户问题及锚定位置、对应 run；模型回答稍后单独提交 |
| 回答已完成 | 回答正文和状态、相关 run 结束信息 |
| 答题已判定 | 实际选择／跳过、用时、判定和当前位置；不能只存在前端 |
| 练习／考核已完成 | 最终答案、汇总结果、ActivityProgress，以及 Course 版本更新 |
| 项目阶段已完成 | 非空成果正文、ActivityProgress，以及 Course 版本更新 |

进度和 nextItem 是从 `activity_progress` 与目录按同一函数派生的读结果，不建立第二份独立可修改事实。活动变更后父课程版本提升，所有入口重新获取同一结果。

模型调用和 WebSocket 发送不持有数据库长事务。状态提交成功后才推送通知；通知失败不撤销已经保存的业务数据，重连按快照恢复。

## 6. 计分与时间

已核对原站共享算法的证据是 `hyperknow-clone2/recon/pretty/quizScoring-CUGhpPfb.pretty.js`。本项目沿用以下个人计分，不保留伪对手：

- 答对基础 600；10 秒内快答额外 200；连击奖励为本题前连续答对数 × 100，上限 400。
- 答错或跳过重置连击。未作答不提前计为错。
- 正确率达到 80%／55%／25% 分别为 3／2／1 星，否则 0 星。
- 另按满分差值与得分比例计算星级，最终取两条路径较大值；完美满分为每题基础＋快答＋对应连击奖励之和。
- 第二路径：满分差值 ≤ 0 为 3 星；差值 = 1 或得分比例 ≥ 80% 为 2 星；比例 ≥ 50% 为 1 星，否则 0 星。空题组不产生正常成绩。

服务端使用实际作答重新计算，不信任前端上传的总分。客户端保留实际作答用时／起点用于快答语义，刷新不重置已保存记录；这是个人使用记录，不建设防作弊或可信考试系统。

本轮不把现有内核 tests 的 Mock 结论作为算法证据；今后直接调用真实计分函数，用实际数值输入核查即可。

## 7. 恢复与数据维护

刷新恢复读取数据库快照；进程重启将 queued、clarifying、generating 的未终结运行标为 interrupted，不自动再发模型请求。awaiting_answers 可重新展示并由用户继续；ready 读取已保存结果。

问答／出题在途被打断也要留下明确的失败或 interrupted 状态，不留下永久 loading。已保存讲义和题目不需要模型再次生成才能恢复。

首版不迁移 Clone 的真实用户库，不导入其账号、token 或样本个人数据。数据库 schema 迁移用有序 SQL 和 schema_version；修改前备份，不能为修复测试直接清空用户数据。

手动备份在服务停止后复制 SQLite 文件；不声称只复制运行中的主文件即可覆盖所有模式下的完整数据。首版不建设自动备份平台或完整导入导出界面。
