# API、事件与客户端同步契约

独立教学新增`/api/assistance/conversations`、会话`/{id}/turns`、`/api/assistance/artifacts/{id}`、`/progress`及`/feedback`；完整字段、202返回和版本约束见[即时协助契约](instant-assistance.md)。取消／重试仍复用`/api/runs/{id}`，事件增加`conversation:{id}`及`artifact:{id}`，不引入第二套WebSocket。快照读取与恢复不自动触发模型收费。

状态：2026-10-22 造课与课堂保留既有真实验收；练习／考核出题、作答、显式提交与结果查询本阶段范围已完成真实验收。thought-answers 与成果提交仍为目标；证据及未覆盖时序见[完成计划](../exec-plans/completed/20261022-real-practice-exams.md)。
关联：[架构](../ARCHITECTURE.md)、[数据](data-model.md)、[交互](learning-experience.md)。

## 1. 基本约定

- REST 使用 `/api` 前缀，JSON 字段统一 snake_case；不要求兼容原站 `/api/v1` URL 与字段。
- 不做公开登录；本地固定身份，默认回环访问。前端开发通过代理同源访问。
- 查询返回已保存快照及 version；命令返回提交后结果，不阻塞 HTTP 到模型完成。造课／澄清／重试返回 202 和 run；课堂 prepare 返回 200 快照，questions 返回 202 快照，运行引用位于 generation_run 或 interactions[].run_id。
- 写命令携带 client_command_id；同 ID／输入重试复用已保存资源引用并读取其当前快照，不重复创建或提交，也不保证返回第一次提交时的旧版本；同 ID 异输入返回 409。
- 更新 run 携带其 expected_version；课堂 progress／questions／complete 携带 progress.version 和 script_id，prepare 仅需命令 ID。版本冲突返回 409 和 error.latest_version，客户端重新读快照，不静默覆盖。
- 未知端点返回 404，错误使用相应 4xx／5xx，不返回 `success: true, stubbed: true`。

通用错误示意如下，仅为协议说明，不是测试桩或实际运行证据：

```json
{
  "error": {
    "code": "model_request_failed",
    "message": "模型请求失败，本次未生成课程",
    "retryable": true
  }
}
```

错误消息不含密钥；区分配置缺失、请求失败、内容校验失败、保存失败和状态冲突。

## 2. REST 功能面

当前 schema 由 Pydantic/OpenAPI 落实，前端有消费类型；不在文档另维护完整类型库。

### 已实现端点

| 方法与路径 | 作用及保存边界 |
| --- | --- |
| `GET /api/health` | 服务、存储路径指纹及model／search配置状态；不披露密钥，已配置不等于真实模型或搜索连通 |
| `POST /api/course-runs` | 保存文字目标，建立blueprint-v1生成run，返回202；缺模型或Tavily配置提前503且不建任务／回执 |
| `GET /api/runs` | 最新 30 条运行，课程库恢复等待、失败、取消或中断的任务 |
| `GET /api/runs/{run_id}` | 运行阶段、澄清、结果引用或错误 |
| `POST /api/runs/{run_id}/answers` | 保存答案；`skip: true` 明确跳过，进入课程生成 |
| `POST /api/runs/{run_id}/blueprint` | 全局蓝图待确认时保存批准或调整意见；client_command_id、expected_version、approve、feedback；批准后自动逐单元展开，不逐单元审批 |
| `POST /api/runs/{run_id}/cancel` | 显式取消，阻止晚到结果生效 |
| `POST /api/runs/{run_id}/retry` | 根据原输入建立新 run，不重写旧运行身份 |
| `GET /api/courses` | 课程列表及一致的进度摘要 |
| `GET /api/courses/{course_id}` | 完整目录、完成情况、课时比例和 next_item |
| `POST /api/courses/{course_id}/delete` | client_command_id、expected_version（课程 version）；200 返回 `{course_id, deleted:true}`。事务内检查版本并删除课程及其课堂、练习、作答、运行与调研证据；关联任务 queued／clarifying／generating／awaiting_answers／awaiting_blueprint 时返回 409 course_active，需先停止相关任务。未知课程 404；同命令／输入重试在删除后仍返回成功，异输入 409 |
| `GET /api/sessions/{session_id}` | LessonSnapshot：课时元数据、完整脚本、progress、interactions、generation_run、completed 及顶层 version；不触发模型 |
| `POST /api/sessions/{session_id}/prepare` | 200；无讲义及历史生成记录时建立 lesson run，已有脚本／记录复用；失败等状态由显式 run retry 处理 |
| `GET /api/sessions/{session_id}/lesson` | 与课时 GET 相同的已保存快照，不另造暂停版本 |
| `PUT /api/sessions/{session_id}/progress` | 200；检查 progress.version、script_id、cursor 与 play_intent，只允许保持或前进一步，不允许倒退／跳步；问答 pending 时拒绝 |
| `POST /api/sessions/{session_id}/questions` | 202；cursor 必须等于确认位置，问题 2–2000 字；保存锚点、was_playing、pending Interaction、question run 并暂停，回答稍后提交 |
| `POST /api/sessions/{session_id}/complete` | 200；已有关联讲义时手动完成，activity_progress、课程版本及课堂暂停同事务提交；不以播放到末步自动完成 |

### 练习与考核端点

以下端点已实现并完成本阶段范围的真实验收。GET 不调用模型、不新建尝试、不自动提交。

| 方法与路径 | 作用及保存边界 |
| --- | --- |
| `GET /api/sessions/{session_id}/practice` | QuizSnapshot，读取课后练习目标及已有题组／运行／最近尝试 |
| `GET /api/exams/{exam_id}` | QuizSnapshot，读取所属单元考核目标 |
| `POST /api/sessions/{session_id}/practice/prepare` | 显式依据已有真实讲义出题；无讲义明确拒绝，不自动先生成讲义 |
| `POST /api/exams/{exam_id}/prepare` | 显式基于单元真实大纲及预算内已缓存讲义出题 |
| `POST /api/quizzes/{quiz_id}/attempts` | 明确开始／再练；已有未提交尝试复用，已提交后才建立新尝试 |
| `GET /api/quizzes/{quiz_id}/attempts` | `{attempts:[...]}`，保留并查阅历次尝试 |
| `GET /api/attempts/{attempt_id}` | AttemptSnapshot：quiz、attempt、当前派生 course |
| `POST /api/attempts/{attempt_id}/answers` | 保存当前题选择／跳过／实际用时，服务端判定；当前cursor不变，保留反馈 |
| `POST /api/attempts/{attempt_id}/next` | 当前题已保存后明确推进，持久化新cursor及question_started_at |
| `POST /api/attempts/{attempt_id}/submit` | 全题已答／跳过后明确提交；结果、完成事实与课程版本同事务，结果页不自动导航 |

prepare／attempts使用client_command_id；answer／next／submit另带expected_version，answer含question_id、option_ids、skipped、elapsed_ms。用时为0至86,400,000的整数毫秒，不能传浮点、布尔、字符串或前端总分；刷新沿用已保存起点，超过24小时由界面明确提示按24小时截断，不假称可信考试计时。QuizSnapshot按目标version合并，AttemptSnapshot按attempt.version排序；course有独立version，不能用旧课程数据覆盖新课程状态。

### 独立网页调研

独立网页调研提供`POST /api/research-runs`（202），输入client_command_id、goal、可选context。返回kind=research，查询、取消、重试及run订阅复用现有端点；research保存已读来源、过程和报告，缺模型／Tavily配置提前503。不经过课程澄清，不创建课程。新课程已单独接入相同研究能力，research／blueprint／units阶段及awaiting_blueprint状态见[蓝图工作流](course-blueprint-workflow.md)，不要求旧run兼容。

### 后续目标端点

下列路由尚未注册，当前请求返回 404；长期范围保留，不当作已交付能力。

| 方法与路径 | 目标作用及保存边界 |
| --- | --- |
| `POST /api/sessions/{session_id}/thought-answers` | 保存思考题答案，返回判定或反馈 run |
| `GET /api/projects/{stage_id}` | 阶段要求、所属项目与已保存成果 |
| `POST /api/projects/{stage_id}/submissions` | 保存非空成果并完成阶段，同事务提升课程版本 |

答题为本地单用户，允许客户端取得题目答案和解释，不做防作弊；计分由后端执行真实规则，避免两套口径。活动 ID 必须属于所引用课程。

最后一题“看结果”：确认答案已保存 → 明确提交尝试 → 展示结果。“回到课程”只导航不再次提交。失败保留状态，可用同一命令身份重试。测验命令清理采用所有权比较后删除：方法、路径与client_command_id仍匹配才释放；卸载页面的迟到请求不得清除后继页面的新待确认命令。

## 3. WebSocket 只做通知

当前连接 `/api/events`，支持 `run:{id}`、`course:{id}`、`session:{id}`、`attempt:{id}` 与 `quiz_target:practice:{session_id}`／`quiz_target:exam:{exam_id}`。quiz_target 的资源ID包含practice:或exam:前缀；不通过另一套 WS 命令修改业务。

```json
{
  "type": "resource_changed",
  "resource_type": "run",
  "resource_id": "run_example",
  "version": 3,
  "state": "awaiting_answers"
}
```

事务提交后发送通知，不携带唯一正文，不是事件溯源日志，不承诺历史无限回放。run 通知使用运行版本，course 通知使用课程版本，session 通知使用课堂快照顶层 version，不是 progress.version。客户端收到更新后读取快照，合并时拒绝旧版本；问答 ready 即使未改变位置也不能被旧快照覆盖。

连接成功回复 `connected`；每次订阅成功回复 `subscribed` 和对应主题。初次连接或重连先等待订阅确认，再拉取当前快照，避免先查询后订阅的漏更新窗口。课堂同时订阅 session 和 course，读取中有更新则标记 dirty 并再次查询；若命令回包先被接受，拒绝用更早发出的 GET 覆盖它。通知不可用时显式回退 HTTP，同步轮询为 5 秒，另在重新联网／可见时读取。测验读取有有效结果（或已明确失败）时即结清该批等待者，dirty只安排后续读，不能因慢于轮询而要求队列完全排空、永久阻塞命令busy。心跳只代表连接，不代表模型仍在执行。

## 4. 播放与同步

- 单一 PlaybackClock 负责推进；取消旧计时并保留写入互斥，Board 从已确认 cursor 的步骤前缀重建，不重复追加视觉元素。后端不开第二套讲课计时器。
- 下一步先串行保存，再接受提交后快照并展示；同一步不并行写，不在每次渲染发送命令。初始 cursor=-1，保持或 +1 合法，跳步和倒退拒绝。
- 结果不明时保留 sessionStorage 中原命令 ID、完整请求和后续动作，显式重试同一命令；确认 409 后释放冲突命令并重新读取。断网／同步错误暂停，不积累未保存步骤。
- 课堂聚合顶层 version（session 资源版本）排序完整快照；progress.version 由脚本／进度写事务更新（提问或完成的暂停写入也更新），供进度、提问和完成命令校验，回答状态变化不必更新它。两者不能替换使用。
- GET 保留 SQLite 中权威 play_intent，同一 version 不因恢复读取伪改为 paused；前端本地 playing 初始化为 false，任何 GET／轮询都不会调用 play。显式用户播放且命令确认后才启用时钟。
- 提问先保存暂停，再用返回的 progress.version 提交问题。回答持久化后仍保持暂停与可读，点击继续才恢复 was_playing；确认身份包含 interaction_id 和 run_id，重试回答不能复用上次继续确认。
- 回看页栏只改变本地选择，不改变确认 cursor、写入位置或问答锚点；恢复从脚本与保存位置重建。

## 5. 复用与竞争

当前 prepare 对已有脚本或任一该课时讲义 run 返回当前快照，不另启模型调用；failed／cancelled／interrupted 由显式 retry 建立新 run，保留旧 run 与模型／输入依据。题组prepare也复用既有题组或最近运行，失败由显式run retry处理；再练复用原题组版本，不重新出题。

取消与模型完成竞争以事务内状态为准，已取消结果不提交；ready 后取消返回明确冲突，不删除课程。单进程事务和版本检查足够，不引入分布式锁。

删除课程与清理关联数据、保存删除回执在同一事务中提交；版本冲突为409 version_conflict并含latest_version。提交后course通知state=deleted、version=删除前版本+1，后续GET返回404。旧创建、准备、重试等命令回执保留，其资源已删除时重放返回404，不能重新生成；只有成功删除命令的同输入重放返回既有删除确认。

内核 emit 不是本协议。当前本地检查覆盖实际函数、SQLite 与本地 HTTP／WS；真实 deepseek-flash 已生成 asyncio／摄影两课讲义和两条问答，并完成播放、回看、显式继续、手动完成及已保存状态冷重启验收，证据见[课堂计划](../exec-plans/completed/20261022-real-whiteboard-classroom.md)。没有凭据不能证明生成成功，未来目标端点仍不可调用；生成 OpenAPI 不代表接口验收完成。
