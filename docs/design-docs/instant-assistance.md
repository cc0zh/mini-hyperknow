# 即时协助 V1 契约

状态：2026-10-26教学职责重构后已执行有界真实模型复验：即时协助8轮ready、2轮失败，四类产物保存；动画截断、教学语义及移动溢出使整体验收未通过，详见[真实复验](../exec-plans/completed/20261026-real-teaching-refactor-validation.md)。2026-10-24的浏览器、取消／冷重启证据及已知内容／隔离限制见[历史完成计划](../exec-plans/completed/20261024-instant-assistance.md)，不覆盖新提示质量。本契约在本范围内取代旧产品文档“不做独立即时聊天”的裁剪；不代表全部教学正确或任意脚本强隔离，其他裁剪不变。

## 职责与范围

独立会话支持概念讲解、问题求解、澄清及显式继续。业务提示维护基本教学策略，工具创建结构化产物，服务端决定状态、事务与权限。无课程归属，无搜索／RAG／文件／命令工具。2026-10-26删除两个基础教学Skill，但保留通用Skill能力：当前可信白名单为空，普通回答及产物无需加载Skill；有专门方法时按显式可信目录白名单装配，非空目录才注册get_skills。目录与正文版本仍在run输入冻结，实际加载进入使用记录及轨迹，重试使用原快照。SQLite是权威记录，不启用内核JSONL作为第二业务数据库。

重构及本地验证边界见[执行计划](../exec-plans/completed/20261026-teaching-boundaries-refactor.md)，后续真实复验单独记录。新契约不兼容旧格式、不提供迁移器，也不清空已有数据库；前后端须一起升级，验证使用独立数据。历史真实模型验收不能作为新提示的质量验收。

## 数据及接口（实施基线）

- Conversation：conversation_id、title、version、created_at、updated_at、turns、active_run。active_run为现有Run或null。
- Turn：turn_id、run_id、user_text、action、status、response、artifacts、skill_uses、steps、error。状态沿用queued/generating/ready/failed/cancelled/interrupted。response为空或{text,questions,plan,current_step,waiting_for,suggestions}；questions为{question_id,question,options:string[],multiple:boolean}数组，plan为字符串数组，waiting_for为answer/continue/none。
- action：只有message/continue两个意图，产物种类不是学习者要选的选项，不再接收skill_hint。text为用户实际输入；message必须非空，continue可为空但必须有已保存待续讲计划，next-step状态独立于可选历史预算冻结，输出必须保留原plan且current_step+1，不从历史推断缺失的权威继续状态。可选artifact_id仅用于关联同会话白板提问，输入上下文仅包含已确认步骤。
- suggestions：按需0–4项，每项必须有{label,text,action}。推进原计划下一步用continue，且回复必须waiting_for=continue；其他建议用message。前端直传显式动作，不识别文案猜测；questions等待回答时suggestions为空。计划、理解检查和建议都不要求每轮出现。
- 产物意图由服务端从用户文本派生两个独立字段并写入run输入：requested_artifacts（点名，最多一项）与forbidden_artifacts（明确拒绝）。命中的点名仍保留「说了要某类产物就必须真有」的强校验；拒绝在工具层与提交层都生效。判定是关键词启发式，引用已有产物的措辞（当前/这块/上面的…）不计为点名。否定沿闭合词表的顿号/和/或等并列列表传递，分句重置；仍不处理任意复杂语义，修复不改写历史run已冻结输入。
- Artifact：artifact_id、conversation_id、turn_id、kind、title、version、data，写入反馈后另有feedback与feedback_at。kind为flashcards/quiz/whiteboard/animation/diagram。
- steps是该run已记录的受控步骤轨迹，run进入ready／failed／cancelled／interrupted任一终态时随turn保存，可回看实际加载与创建；没有步骤时界面只显示正在生成回复，不伪造技能加载。skill_uses允许为空，但保留实际使用的name/version/sha256。
- flashcards.data={cards:[{question,answer}]}，上限6张；quiz.data={questions:[{question_id,question,options:[{id,text}],correct_ids,explanation}]}，上限6题，correct_ids长度决定单／多选；不计入课程成绩，不保存作答。
- diagram.data={source,caption}：source是不含配置指令的Mermaid源码（上限4000字符），caption是独立图注。前端复用白板既有的Mermaid渲染器生成SVG，不保存渲染结果，也不引入服务端渲染。
- whiteboard.data={steps:[BoardStep],cursor:-1}，BoardStep沿用step_id/narration/page/column/operations；操作结构沿用现有八种BoardOperation。独立保存cursor及产物version，不添加course_id。恢复本地播放器始终暂停。
- animation.data={html}，仅保存源码，iframe内部状态不保存。
- POST /api/assistance/conversations {client_command_id} → Conversation；GET同路径→{conversations:摘要数组}；GET /api/assistance/conversations/{id}→Conversation。
- POST /api/assistance/conversations/{id}/turns {client_command_id,expected_version,text,action,artifact_id?} → 202 Conversation。写入用户轮次与run后立即返回，不等待模型；一个会话仅一个在途运行。
- GET /api/assistance/artifacts/{id}→Artifact；PUT同路径/progress {client_command_id,expected_version,cursor}→Artifact。cursor仅保持或+1，白板问答pending时拒绝推进。
- PUT /api/assistance/artifacts/{id}/feedback {client_command_id,expected_version,vote:up|down}→Artifact。progress与feedback的待确认命令均可从sessionStorage恢复，沿用原命令身份；仅progress可附带保存后提问链。服务器已保存反馈不会因刷新被删除。
- 反馈更新与会话内嵌产物同事务保存，刷新会话读取与产物独立GET保持一致；使用产物自身version，不为反馈提升会话版本或调用模型。
- 取消／重试复用/api/runs/{id}/cancel及retry；重试保留同turn与原输入，旧run不得覆盖后继。对话后已有新轮次时不允许重试较早轮次。
- 事件复用/api/events，新增conversation:{id}与artifact:{id}的resource_changed；断线靠快照，不将正文只放WS中。

## 模型与产物

使用现有Agent、同步provider与共享worker；每个run独立上下文。五种产物工具为create_flashcards、create_quiz、create_whiteboard、create_animation、create_diagram，非空可信目录另注册可选get_skills，参数由Pydantic校验。实际创建只是本轮暂存，最终回复及全部产物通过校验并在同事务提交；失败不留下伪完成。显式产物请求必须确实生成相应产物。模型不持有任意路径、网络或执行能力。工具循环、上下文及模型调用次数有上限；普通教学限制输出，明确请求动画时不传输出上限参数；输入不静默截断当前问题，历史选择范围及预算留证。

教学策略与交互说明维护在prompts/assistance.py；具体产物制作要求跟随工具描述，结构在assistance_domain.py；状态/权限/数量与提交门禁留执行及存储模块。必要条件缺失时问一个关键问题，普通风格偏好不阻塞；只要提示不泄露完整解答，检查时定位最早错误及原因。Skill是专门方法的可选补充，不是基本教学的强制路由。

普通教学输出上限默认8192；明确请求动画且未禁止动画的轮次，OpenAIService的max_output_tokens为None，供应商请求不含max_tokens或max_completion_tokens。不能据此保证无限输出或供应商默认一定高于8192/16384。未点名而由模型自行选择动画的普通教学轮次仍沿用原上限。

AssistantGenerator构造参数output_reserve仍默认8192，仅作Agent上下文预留和逐次门禁；普通轮次也用它设置输出上限。审计分别记录output_reserve与max_output_tokens（动画为null），避免把预留误称为硬上限。原时限、调用次数、HTML长度校验和隔离规则不变，不新增环境变量/API。此前16384失败的[预算实验](../exec-plans/completed/20261026-animation-output-budget.md)保持原始证据；后续[取消上限真实复验](../exec-plans/completed/20261026-animation-no-cap-validation.md)已得到完整动画参数，但产物回填后上下文估算超限导致收尾失败，0已提交产物，产品浏览器未执行。

TeachingContext在成功create_animation后，对下一次请求深拷贝中的HTML使用明确省略标记/UTF-8字节数/SHA-256；原始调用响应、活动历史、审计及待提交/最终产物保留全文，工具调用ID/名称/标题/成功回执不变。失败/未完成/其他工具不投影；短于标记的HTML不改。该产品专用投影发生在内核prepare和逐调用门禁之前，不修改通用Agent或删除用户输入。旧失败响应离线复放和一次新真实生成/桌面及手机展开预览已有证据；默认手机预览仍被输入框遮挡，见[收尾上下文修复](../exec-plans/completed/20261026-animation-followup-context.md)。

## 展示及隔离

仅桌面浏览器属于当前适配和验收范围。历史手机预览遮挡与窄屏检查结果保留为当时事实，2026-10-27起不再作为待修项或交付门禁；不因此修改已生成产物、原browser.json或桌面交互要求。
正文使用受控文本／公式／代码渲染，不注入模型HTML；HTML只在动画iframe中展示。动画sandbox仅为allow-scripts，不授予同源、表单、弹窗、下载或顶层导航；CSP禁止第三方子资源、连接、框架与eval，只允许必要内嵌脚本／样式及data图片。无主应用凭据或工具桥接。生成提示要求自包含，静态清理额外去除显式导航元素／属性。

正文另有四种封闭块类型（definition／example／warning／note），只映射到固定组件；模型不能自定义块种类或注入样式，行内公式与加粗限定在该范围内。产物反馈只记录学习者对产物的判断，不改变已保存的教学内容，也不触发模型调用。
**隔离边界**：浏览器sandbox不能可靠禁止活动脚本导航iframe自身，Chromium不支持用navigate-to获得此保证，静态清理不能证明任意JavaScript安全。因此这是本地教学HTML的宿主隔离预览，不是任意恶意JS的网络／CPU／内存沙箱；不接受用户上传代码，不宣称所有网络出口绝对封锁。页面明确不可信预览和不输入敏感信息；重置重建iframe，不恢复内部状态。若未来要求任意不可信代码及严格出口封锁，须另行设计真正的执行与网络隔离，不扩充正则黑名单来冒充保证。

闪卡、测验为本地轻量组件，切换题目清除本地作答；生成内容可恢复不表示作答可恢复。白板以现有受控渲染与单播放器复用为主，不要求Excalidraw编辑器或原站语音同步协议。
