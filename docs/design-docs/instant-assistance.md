# 即时协助 V1 契约

状态：2026-10-24本切片实现与分层验收完成，真实模型、浏览器、取消／冷重启证据及已知内容／隔离限制见[完成计划](../exec-plans/completed/20261024-instant-assistance.md)。本契约在本范围内取代旧产品文档“不做独立即时聊天”的裁剪；不代表全部教学正确或任意脚本强隔离，其他裁剪不变。

## 职责与范围

独立会话支持概念讲解、问题求解、澄清及显式继续。Skill指导教学策略，工具创建结构化产物，服务端决定状态、事务与权限。无课程归属，无搜索／RAG／文件／命令工具。两类可信内置Skill按需加载；目录与正文版本在run输入固定，实际激活记录可追溯，重试使用原快照。SQLite是权威记录，不启用内核JSONL作为第二业务数据库。

## 数据及接口（实施基线）

- Conversation：conversation_id、title、version、created_at、updated_at、turns、active_run。active_run为现有Run或null。
- Turn：turn_id、run_id、user_text、action、skill_hint、status、response、artifacts、skill_uses、error。状态沿用queued/generating/ready/failed/cancelled/interrupted。response为空或{text,questions,plan,current_step,waiting_for}；questions为{question_id,question,options:string[],multiple:boolean}数组，plan为字符串数组，waiting_for为answer/continue/none。
- action：只有message/continue两个意图，产物种类不再是学习者要选的选项；skill_hint：auto/concept-explanation/problem-solving。text为用户实际输入；message必须非空，continue可为空但必须有已保存待续讲计划，next-step状态独立于可选历史预算冻结，输出必须保留原plan且current_step+1。可选artifact_id仅用于关联同会话白板提问，输入上下文仅包含已确认步骤。
- 产物意图由服务端从用户文本派生两个独立字段并写入run输入：requested_artifacts（点名，最多一项）与forbidden_artifacts（明确拒绝）。命中的点名仍保留「说了要某类产物就必须真有」的强校验；拒绝在工具层与提交层都生效。判定是关键词启发式，引用已有产物的措辞（当前/这块/上面的…）不计为点名，这是已知近似而非语义理解。
- Artifact：artifact_id、conversation_id、turn_id、kind、title、version、data，写入反馈后另有feedback与feedback_at。kind为flashcards/quiz/whiteboard/animation/diagram。
- Turn：turn_id、run_id、user_text、action、skill_hint、status、response、artifacts、skill_uses、steps、error。steps是该run已记录的受控步骤轨迹，run进入ready／failed／cancelled／interrupted任一终态时随turn保存，因此完成后仍可回看「加载了哪个技能、创建了什么产物」，不需要第二次请求。
- flashcards.data={cards:[{question,answer}]}，上限6张；quiz.data={questions:[{question_id,question,options:[{id,text}],correct_ids,explanation}]}，上限6题，correct_ids长度决定单／多选；不计入课程成绩，不保存作答。
- diagram.data={source,caption}：source是不含配置指令的Mermaid源码（上限4000字符），caption是独立图注。前端复用白板既有的Mermaid渲染器生成SVG，不保存渲染结果，也不引入服务端渲染。
- whiteboard.data={steps:[BoardStep],cursor:-1}，BoardStep沿用step_id/narration/page/column/operations；操作结构沿用现有八种BoardOperation。独立保存cursor及产物version，不添加course_id。恢复本地播放器始终暂停。
- animation.data={html}，仅保存源码，iframe内部状态不保存。
- POST /api/assistance/conversations {client_command_id} → Conversation；GET同路径→{conversations:摘要数组}；GET /api/assistance/conversations/{id}→Conversation。
- POST /api/assistance/conversations/{id}/turns {client_command_id,expected_version,text,action,skill_hint,artifact_id?} → 202 Conversation。写入用户轮次与run后立即返回，不等待模型；一个会话仅一个在途运行。
- GET /api/assistance/artifacts/{id}→Artifact；PUT同路径/progress {client_command_id,expected_version,cursor}→Artifact。cursor仅保持或+1，白板问答pending时拒绝推进。
- 取消／重试复用/api/runs/{id}/cancel及retry；重试保留同turn与原输入，旧run不得覆盖后继。对话后已有新轮次时不允许重试较早轮次。
- 事件复用/api/events，新增conversation:{id}与artifact:{id}的resource_changed；断线靠快照，不将正文只放WS中。

## 模型与产物

使用现有Agent、同步provider与共享worker；每个run独立上下文。工具为get_skills、create_flashcards、create_quiz、create_whiteboard、create_animation，参数由Pydantic校验。实际创建只是本轮暂存，最终回复及全部产物通过校验并在同事务提交；失败不留下伪完成。显式产物请求必须确实生成相应产物。模型不持有任意路径、网络或执行能力。工具循环、输出与模型调用次数有上限；输入不静默截断当前问题，历史选择范围及预算留证。

## 展示及隔离

正文使用受控文本／公式／代码渲染，不注入模型HTML；HTML只在动画iframe中展示。动画sandbox仅为allow-scripts，不授予同源、表单、弹窗、下载或顶层导航；CSP禁止第三方子资源、连接、框架与eval，只允许必要内嵌脚本／样式及data图片。无主应用凭据或工具桥接。生成提示要求自包含，静态清理额外去除显式导航元素／属性。


正文另有四种封闭块类型（definition／example／warning／note），只映射到固定组件；模型不能自定义块种类或注入样式，行内公式与加粗限定在该范围内。产物反馈只记录学习者对产物的判断，不改变已保存的教学内容，也不触发模型调用。
**隔离边界**：浏览器sandbox不能可靠禁止活动脚本导航iframe自身，Chromium不支持用navigate-to获得此保证，静态清理不能证明任意JavaScript安全。因此这是本地教学HTML的宿主隔离预览，不是任意恶意JS的网络／CPU／内存沙箱；不接受用户上传代码，不宣称所有网络出口绝对封锁。页面明确不可信预览和不输入敏感信息；重置重建iframe，不恢复内部状态。若未来要求任意不可信代码及严格出口封锁，须另行设计真正的执行与网络隔离，不扩充正则黑名单来冒充保证。

闪卡、测验为本地轻量组件，切换题目清除本地作答；生成内容可恢复不表示作答可恢复。白板以现有受控渲染与单播放器复用为主，不要求Excalidraw编辑器或原站语音同步协议。
