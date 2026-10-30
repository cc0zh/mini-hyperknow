# 业务、AI契约与评测可优化性审计

状态：2026-10-26 静态审计，**2026-10-30 移出设计目录**。本文是重构前的源码快照与当时建议，**不是当前业务地图、契约或实施依据**；现行定位查[业务与改动影响入口](../ARCHITECTURE.md#10-现行业务与改动影响入口)，现行设计查[设计文档索引](../design-docs/index.md)。审计不新增产品范围，也不替代真实模型或浏览器验收。

后续状态：两个教学Skill、固定加载和已记录跨端问题的处理见[重构计划](../exec-plans/completed/20261026-teaching-boundaries-refactor.md)。


关联：[产品范围](../design-docs/product-design.md)、[产品内核](../design-docs/product-kernel.md)、[架构](../ARCHITECTURE.md)、[模型工作流](../design-docs/agent-workflows.md)、[即时协助](../design-docs/instant-assistance.md)、[现有eval](../design-docs/backend-evaluation-pipeline.md)、[审计计划](../exec-plans/completed/20261026-business-ai-eval-audit.md)。

后续清理：旧评测执行器已移除，下文已删除模块的名称仅为历史源码定位，不再作为可点击现行入口；现行命令与历史只读边界见[评测入口](../../evals/README.md)。

## 1. 阅读结论与证据口径

- “业务已实现”“该业务经过某次真实验收”“已接入持续eval”是三件不同的事；八类业务地图不是八套已落地自动eval。
- 系统提示词、工具描述、参数Schema、用户输入组装、工具结果和Skill正文共同构成模型实际输入；不能只搜索名为prompt的文件。
- 必要耦合：展示结构必须被渲染器理解，课堂回答必须使用已确认位置，生成必须符合保存契约。这些依赖不能靠拆文件消除。
- 优化耦合：教学策略在多个位置重复、一个入口携带无关能力说明、业务限制与评测目标不一致，会让改动难隔离、结论难归因。
- 静态事实可以确认契约限制，不能证明某段提示导致某次模型错误，也不能证明减少提示词就会提高质量。

结论：运行底座没有显示出必须整体重写的证据；主要障碍是教学策略维护位置重复、业务契约与候选判据未对齐、前端动作改变真实输入，以及当前eval对首个场景的强绑定。应先让一个能力的修改与证据可隔离，再按需扩大覆盖。

## 2. 当前业务地图

当前有两条学习入口，以及不依赖模型的支撑业务。以下“八类”是业务能力分类，不能按行数推断有八个独立Agent。

```text
造课：目标 → 生成澄清问题 → 用户回答/跳过 → 网页调研
     → 全局蓝图 → 用户确认/反馈调整 → 自动逐单元展开 → 课程库/路径
学习：课时大纲 → 准备讲义 → 确认展示/回看 → 课堂提问
     → 课后练习/单元考核 → 答题/反馈/提交 → 完成记录/下一项
协助：独立会话 → message/continue → 加载Skill → 可选创建一个产物
     → 回复与产物原子保存 → 后续追问/继续/产物反馈
另有：独立网页调研端点；与造课共用Researcher，但不是已接入独立前端调研页。
```

| 业务能力 | 实际入口与执行 | 输出/持久化与消费者 |
| --- | --- | --- |
| 需求澄清 | main.create_run → CourseService.create；答案经main.answers → CourseService.answers/resolve_answers | Clarification问题保存到run；CourseRun收集答案；随后转入research |
| 学习资料调研 | main.research_run独立入口；造课提交答案后也进入Researcher.generate | ResearchReport、搜索/阅读步骤和已读来源保存到run.research；报告供蓝图/展开及CourseRun展示 |
| 课程规划与展开 | Generator.generate的blueprint/units；main.blueprint处理确认或反馈 | BlueprintDraft → Course骨架；UnitExpansionDraft逐单元提交；CourseRun、BlueprintExplorer、CourseOverview消费 |
| 课堂讲义生成 | main.prepare → LessonStorage.prepare_lesson → Generator.generate的lesson分支 | BoardScriptDraft → 不可变BoardScript与LessonSnapshot；Classroom/Board播放器消费 |
| 课堂问答 | main.question → LessonStorage.ask_question → question分支 | LessonAnswer → Interaction；只保存问答，不改主讲义 |
| 练习与考核生成 | main.practice_prepare/exam_prepare → QuizStorage.prepare_quiz → quiz分支 | QuizDraft → 不可变Quiz、QuizAttempt/QuizResult；Quiz页面作答与结果展示 |
| 即时协助教学 | assistance_api.turn → CourseService.assistance_turn → AssistantGenerator.generate | TeachingResponse、Skill激活与受控步骤保存至独立Conversation/Turn；Assistance页面消费 |
| 教学产物生成 | 同一即时协助Agent按需调用create工具；不是课程生成阶段 | flashcards/quiz/whiteboard/animation/diagram保存至assistance_artifacts；AssistanceArtifacts分支渲染 |

源码入口：[main.py](../../src/hyperknow/main.py)、[runtime.py](../../src/hyperknow/runtime.py)、[blueprint_storage.py](../../src/hyperknow/blueprint_storage.py)、[lesson_storage.py](../../src/hyperknow/lesson_storage.py)、[quiz_storage.py](../../src/hyperknow/quiz_storage.py)、[assistance_api.py](../../src/hyperknow/assistance_api.py)。

支撑业务包括课程库/路径读取、播放位置、确定性计分、活动完成/next_item、命令幂等、取消/重试/冷重启、WS通知和产物反馈；不能漏掉，也不必为了纳入eval给它们增加提示词。项目目前可生成要求/阶段描述，但成果提交/恢复、课堂思考题反馈、掌握度和自适应重排未实现，不能作为已具备能力评测。

## 3. 提示词、工具与Skill清单

### 3.1 业务提示词及动态输入

当前主要生成提示有8个语义入口：generation.py的6个分支，加research_prompt和teaching_prompt；产物生成复用即时协助提示，不另有五份产物提示词。所有主提示直接位于Python。

| 能力/主提示 | 具体定位 | 实际输入构建 | 输出Schema与主要职责 |
| --- | --- | --- | --- |
| 课程需求澄清 | generation.py:142，Generator.generate/clarifying | 仅goal；不是后续学习者档案的自动推理 | Clarification：2–4个有影响的问题（Prompt要求）、选项及后果说明 |
| 网页调研 | research.py:37，research_prompt，research-v1 | run.input的goal/context；造课context由CourseService.answers保存澄清快照 | ResearchReport：主题边界、先修、学习顺序、实际应用、证据引用与限制 |
| 全局蓝图/调整 | generation.py:149，blueprint | blueprint_domain.planning_context：目标/澄清、调研报告/来源摘录、调整时previous_blueprint/feedback | BlueprintDraft：课程元数据、单元目标和规模，不生成课时/讲义 |
| 单元展开 | generation.py:164，units | planning_context：批准蓝图版本、不可修改的当前unit、全局顺序/已展开摘要和预算 | UnitExpansionDraft：lectures/sessions/exams/project_stages，只展开当前单元 |
| 课时讲义 | generation.py:116，kind=lesson | lesson_domain.lesson_context：目标/澄清、完整session、课程/单元/讲座及前后课标题 | BoardScriptDraft：具体讲解、教学深度、有序视觉操作及narration |
| 课堂答疑 | generation.py:133，kind=question | lesson_domain.question_context：当前问题、script版本、确认前缀、最多6条/6000字符近期问答，整体60000字符 | LessonAnswer：针对问题回答，不续写主脚本，不把未来步骤当已学 |
| 课程练习/考核 | generation.py:101，kind=quiz | quiz_domain.quiz_context：practice用完整真实讲义；exam用单元大纲及预算内缓存讲义，allowed_source_refs | QuizDraft：3–8道客观题，三题型、选项/答案/解析和真实引用 |
| 即时协助/产物 | assistance_generation.py:88，teaching_prompt，assistance-v1 | AssistanceStorage.assistance_turn：原始文本/action/hint、派生产物意图、历史选择；continue/白板问题追加权威状态 | TeachingResponse及产物工具Schema；系统提示目前同时管教学、协议、UI格式和产物选择 |

源码：[generation.py](../../src/hyperknow/generation.py)、[research.py](../../src/hyperknow/research.py)、[assistance_generation.py](../../src/hyperknow/assistance_generation.py)、[blueprint_domain.py](../../src/hyperknow/blueprint_domain.py)、[lesson_domain.py](../../src/hyperknow/lesson_domain.py)、[quiz_domain.py](../../src/hyperknow/quiz_domain.py)。行号是审计快照定位，长期以函数/分支名称为准。

普通生成的system由instruction加Pydantic JSON Schema组成，用户消息为JSON输入；prompt_version用kind-phase-v1标记。版本标签不是内容哈希，改提示词却不改标签仍可能同名，跨实验应保留实际内容与版本。当前课程生成、调研和即时协助沿用Settings.model/已保存run.model，不是八类各自独立默认模型；Grader另有显式配置。

### 3.2 两个实际产品Skill

| Skill | 版本与位置 | 教学职责 | 实际消费者 |
| --- | --- | --- | --- |
| concept-explanation | v2，原路径`skills/concept-explanation/SKILL.md`（已删除） | 按需澄清、概念直觉与推导、分步计划、理解检查、产物选择及下一步建议 | 即时协助；课堂答疑和课程生成不加载它 |
| problem-solving | v2，原路径`skills/problem-solving/SKILL.md`（已删除） | 区分提示/完整求解/检查，定位最早错误，说明条件，分步引导及产物选择 | 即时协助；课程练习出题不加载它 |

[build_skill_snapshots](../../src/hyperknow/assistance_generation.py)固定可信目录及两个名称；[SkillRegistry](../../src/agent_core/skills.py)校验名称、版本、正文大小与SHA256。每个run固定快照，初始只披露目录，模型经get_skills取得正文；重试复用原输入，不读取新版正文冒充同次尝试。开发助手使用的Agent/UI等Skill不是产品运行时的教学Skill。

### 3.3 模型可调用工具

| 运行路径 | 工具 | 参数/输出依据 | 边界 |
| --- | --- | --- | --- |
| 网页调研 | web_search、read_webpage | [Researcher._tools](../../src/hyperknow/research.py)中的JSON参数Schema；结果由fit_search/fit_page裁剪，已读页产生source_id | 实际搜索/阅读；不是仅靠模型自述已查证 |
| 即时协助 | get_skills | 技能名称枚举；返回可信正文及元数据 | 不授予文件、网络或命令权限 |
| 即时协助产物 | create_flashcards、create_quiz、create_whiteboard、create_animation、create_diagram | [AssistantGenerator.tools](../../src/hyperknow/assistance_generation.py)由ARTIFACT_SCHEMAS生成title/data参数Schema，inline_schema展开本地引用 | 每轮最多一个产物；工具只暂存，最终事务提交才算保存 |

课程澄清、蓝图/展开、讲义、课堂问答和课程题组不是各自的工具Agent。业务HTTP命令也不等于模型工具。两个工具场景合计8个工具名称，分属不同运行权限，不一次全部授予同一Agent。

### 3.4 修复提示词与评分器

| 类型 | 位置 | 修改/评测时必须注意 |
| --- | --- | --- |
| 通用生成结构修复 | [generation.py](../../src/hyperknow/generation.py)的bounded_repair_message和Generator.generate | 最多一次；追加有界错误及原文摘录，并重新校验；初始输出和修复输出是不同调用 |
| 调研报告修复 | [research.py](../../src/hyperknow/research.py)的Researcher.generate | 仅修复格式与引用，不再提供搜索工具，不允许新增无依据结论 |
| 即时协助修复 | [assistance_generation.py](../../src/hyperknow/assistance_generation.py)的AssistantGenerator.generate | 仅修复六字段结构与教学状态，不再重复创建产物；使用独立修复system指令 |
| eval裁判 | `eval_grading.py`的build_grading_context，concept-grader-v1 | 无工具；判据/参考事实与原始请求/最终回复隔离；不是教学Skill，不进入被测教学轨迹 |

内核的摘要提示不等于产品已启用长期记忆或自动压缩：当前两个产品Agent直接传provider，未传模型registry的低层摘要模型，也未装配持久JSONL/长期记忆。依据[Agent构造](../../src/agent_core/agent.py)及两个产品generate调用；不要把内核可选能力作为本次业务已覆盖项。

## 4. Schema与状态的实际作用

### 4.1 即时协助不是一段自由文本

[SubmitTurn](../../src/hyperknow/assistance_api.py)接收client_command_id、expected_version、text、action、skill_hint和可选artifact_id。action为message/continue；skill_hint为auto/concept-explanation/problem-solving；artifact_id只用于同会话白板提问。

[TeachingResponse](../../src/hyperknow/assistance_domain.py)包含text、questions、plan、current_step、waiting_for、suggestions六字段。模型输出要求全部出现；Pydantic的默认值主要兼容存储，不代表模型可以省略。questions与waiting_for=answer绑定，存在问题时不能同时给suggestions；continue须有下一步。

[ContinuationState](../../src/hyperknow/assistance_domain.py)单独固定原plan、下一个current_step和is_last_step；[assistance_turn](../../src/hyperknow/assistance_storage.py)从最近ready回复构建，而非只靠可裁剪历史。生成校验要求保留计划并推进指定一步；不能把“换一种更好课程计划”作为continue的默认优化。

### 4.2 五种产物不是五个独立Agent

| kind | 参数数据Schema | 保存与后续消费 |
| --- | --- | --- |
| flashcards | FlashcardsData → Flashcard.question/answer | 保存生成内容；翻卡状态属浏览器现场 |
| quiz | QuizData → ChatQuizQuestion/QuizOption | 与课程QuizDraft不是同一契约；即时作答不计课程成绩 |
| whiteboard | WhiteboardData → BoardStepDraft，并复用BoardScriptDraft顺序校验 | 保存cursor，步骤ID由服务端生成；问答仅取已确认前缀 |
| animation | AnimationData.html | 后端此Schema只限制非空和长度，不证明脚本行为安全或动画正确 |
| diagram | DiagramData.source/caption | 后端非空和长度检查不等于Mermaid语法、渲染或语义正确 |

定义及映射见[assistance_domain.py](../../src/hyperknow/assistance_domain.py)。[finish_assistance](../../src/hyperknow/assistance_storage.py)再次校验并原子保存回复、产物和ready状态；工具返回“暂存成功”不等于交付完成。

### 4.3 课程Schema与前后端映射

| 层次 | 当前主要Schema/对象 | 关键限制与注意 |
| --- | --- | --- |
| HTTP命令 | main.py的CreateRun/CreateResearch、SubmitAnswers、SubmitBlueprint、SaveProgress、AskQuestion、AnswerQuiz；assistance_api.py的SubmitTurn/ArtifactProgress/ArtifactFeedback | 幂等身份和expected_version是执行契约；不是模型负责生成的输出 |
| 澄清 | domain.py的Clarification → Question → Option | Prompt要求2–4问，Schema接受1–5问；支持显式跳过/至少回答一题，但不能生成零问题 |
| 调研 | research_domain.py的ResearchReport → ResearchFinding；validate_report | finding引用只限成功读取页，且要求真实搜索；只验证引用合法，不验证页面支持结论 |
| 蓝图/展开 | BlueprintDraft → UnitBlueprint；UnitExpansionDraft → LectureDraft/SessionDraft/ExamDraft/StageDraft | 项目引用、课时预算、批准考核目标等由valid_plan/validate_expansion校验；单元展开不允许改批准标题/目标 |
| 讲义/课堂 | BoardScriptDraft → BoardStepDraft → BoardOperation；LessonAnswer；LessonSnapshot/Interaction/LessonProgress | 八种operation：text/list/code/formula/box/arrow/highlight/mermaid；page/column是位置，不是新类型；完成不等于理解 |
| 课程练习/考核 | quiz_domain.py的QuizDraft/QuizQuestion/QuizOption、QuizAnswer/QuizAttempt/QuizResult/QuizSnapshot | 三题型/正确选项/来源集合检查；评分由score_answers确定性计算，不是再次调用模型判断 |
| 即时协助 | TeachingResponse/TeachingQuestion/TeachingSuggestion/ContinuationState及五种产物数据 | 不含course_id；即时QuizData不等于课程QuizDraft；白板复用课程BoardStepDraft结构 |
| eval | EvalCase/RubricItem；ATIF文字子集模型；Grader结果严格JSON检查 | result.json是普通记录对象，不是全业务统一领域Schema；规则、内容判定、校准状态分别保留 |

源码：[domain.py](../../src/hyperknow/domain.py)、[main.py](../../src/hyperknow/main.py)、[research_domain.py](../../src/hyperknow/research_domain.py)、[blueprint_domain.py](../../src/hyperknow/blueprint_domain.py)、[lesson_domain.py](../../src/hyperknow/lesson_domain.py)、[quiz_domain.py](../../src/hyperknow/quiz_domain.py)、`eval_cases.py`。

Schema合法只能证明约定的结构和部分不变量，不保证来源支持、数学事实、教学质量或浏览器可用性。domain.CourseDraft/materialize_course和storage.finish_course仍保留旧整课代码，但当前worker按research→blueprint→units推进，不应把旧代码当新增的第九条生成业务。

## 5. 前后端共同影响面

### 5.1 页面与命令链

路由见[web/src/main.tsx](../../web/src/main.tsx)。主要消费者如下：

| 页面/交互 | 实际组件与命令 | 对模型或业务的影响 |
| --- | --- | --- |
| 目标输入/澄清/确认 | [Home](../../web/src/pages/Home.tsx)、[CourseRun](../../web/src/pages/CourseRun.tsx)、BlueprintExplorer、RunResearch；创建run、answers、blueprint命令 | 目标、选项文本、自定义答案、跳过与反馈形成后端固定输入；全局确认是流程屏障，不是模型自确认 |
| 课程库/路径 | [Courses](../../web/src/pages/Courses.tsx)、[CourseOverview](../../web/src/pages/CourseOverview.tsx)、[CourseStructure](../../web/src/components/CourseStructure.tsx) | 读取/删除课程及进入课时/练习/考核；nextLearningPath映射后端next_item，不自行推断掌握度 |
| 课堂播放/提问 | [Classroom](../../web/src/pages/Classroom.tsx)、[use-lesson-player](../../web/src/lib/use-lesson-player.ts)、[Board](../../web/src/components/Board.tsx) | prepare生成；progress保存确认位置；先暂停再用服务端返回cursor提问；手动complete，不因播完自动完成 |
| 课程练习/考核 | [Quiz](../../web/src/pages/Quiz.tsx) | prepare → 创建attempt → 保存answer → next → submit；作答、计分与完成以服务端事实为准 |
| 即时协助 | [Assistance](../../web/src/pages/Assistance.tsx)、[AssistanceTurns](../../web/src/components/AssistanceTurns.tsx)、[use-assistance](../../web/src/lib/use-assistance.ts) | 普通发送固定hint=auto；专用继续按钮发action=continue；回答澄清和建议按钮发message |
| 产物/白板追问 | [AssistanceArtifacts](../../web/src/components/AssistanceArtifacts.tsx)、[AssistanceBoard](../../web/src/pages/AssistanceBoard.tsx) | 本地闪卡/即时答题，白板位置保存及关联问题，产物反馈仅保存up/down，不触发模型优化 |

### 5.2 会改变模型输入的前端行为

1. 课堂cursor是累计“确认展示”的位置，后端只提供displayed_steps前缀。Board的review仅改变回看页栏，不回退cursor。eval若只记录截图，不足以推断模型实际看到了什么；“围绕当前回看步骤”与“围绕已确认前缀”也不是同一产品语义。
2. 即时协助的message与continue不等价。continue冻结原计划并严格推进一步；普通文本“继续”仍可被模型理解为继续，但不进入同一代码校验路径。
3. 快捷入口只是预填草稿；澄清选项经clarificationText拼成自然语言；建议按钮发送suggestion.text。这些文案直接成为下一轮输入，并可能触发requested/forbidden_artifacts启发式。
4. 白板追问包含“保存位置 → 读取最新会话 → 提交带artifact_id问题”的客户端链条；待确认命令放sessionStorage以保持原幂等身份。只测最后一个POST会漏掉前置位置和跨页恢复。

依据：[assistance.ts](../../web/src/lib/assistance.ts)、[use-assistance.ts](../../web/src/lib/use-assistance.ts)、[use-lesson-player.ts](../../web/src/lib/use-lesson-player.ts)、[lesson_domain.question_context](../../src/hyperknow/lesson_domain.py)、[assistance_storage.assistance_turn](../../src/hyperknow/assistance_storage.py)。

### 5.3 已确认的跨端缺口与风险

| 发现 | 已核查事实 | 结论边界 |
| --- | --- | --- |
| 建议“继续”与专用继续走不同action | Assistance.tsx的onSuggest调用send(suggestion.text)，默认message；专用按钮send('继续下一步','continue')；Prompt允许建议下一步 | 存在语义入口分叉；可能绕过严格continuation_state路径。未实际运行，不认定每次都会错步 |
| 反馈pending恢复白名单遗漏 | Assistance.vote构造PUT /artifacts/{id}/feedback；pendingCommandForScope对PUT只接受progress | 当前页面内仍持有pending；刷新后该反馈命令被过滤，可能丢失结果不明时的重试入口。不等于已保存反馈丢失或已发生重复提交 |
| 类型声明不是运行时契约校验 | api.request成功后return body as T；types.ts/assistance.ts镜像后端对象 | 手工跨端Schema维护存在漂移风险；不能仅凭TypeScript编译通过证明响应符合Pydantic。不是发现当前所有响应错误，也不因此立刻引入代码生成平台 |
| ready不等于图形/动画可用 | 后端diagram/animation只作有限结构校验；Board/Mermaid/KaTeX、animationSrcDoc在浏览器解析/清理/执行 | 后端eval不能覆盖排版、渲染失败、操作可用性；静态清理还可能改变实际展示内容 |
| 版本协议有多层 | session.version合并快照、progress.version写入；Conversation和Artifact各自版本，mergeConversation单独合并产物 | 是必要并发协议，不是简单重复字段；评测要覆盖旧响应/重连/跨页，而非盲目统一所有version |

### 5.4 后端eval不能替代的浏览器检查

- 保存确认前是否提前展示、播放/暂停/提问竞态、刷新恢复、错误提示与旧响应合并。
- 中文输入法Enter、键盘/焦点、历史URL、窄屏与长内容溢出、字体实际加载、公式与Mermaid布局。
- 动画控件、DOM清理后的真实展示、iframe宿主访问及CSP；不是只检查生成HTML非空。
- 动画sandbox仅allow-scripts，定位是opaque-origin宿主隔离预览；不保证任意脚本自导航、资源消耗或完整网络出口控制。见[assistance-animation.ts](../../web/src/lib/assistance-animation.ts)和[即时协助安全边界](../design-docs/instant-assistance.md)。

已有[assistance.spec.ts](../../web/e2e/assistance.spec.ts)、[assistance-generation.spec.ts](../../web/e2e/assistance-generation.spec.ts)等入口；本次未运行，存在文件或条件skip不是已验收。内容、结构、渲染、交互与安全应分别保留结论。

## 6. 耦合与eval阻碍

### 6.1 当前eval的硬边界

| 已确认限制 | 代码依据 | 对扩展的具体影响 |
| --- | --- | --- |
| Case只接受concept-explanation | `EvalCase`的skill_hint是单值Literal，extra=forbid | auto和problem-solving直接校验失败；不能仅换题目JSON就测另一Skill或选择能力 |
| Runner只建立空的新会话并发送一轮message | `recover_conversation/recover_turn` | 没有当前课堂、课程前置对象、后续用户反馈和continue脚本 |
| 证据要求assistance且history为空 | `collect_evidence` | 多轮、其他run kind不是“评分低”，而是当前测量契约不接受 |
| 验收数据库不能含courses | `check_backend` | 为首轮防误连的限制合理；当前不能复用于需要真实课程对象的评测 |
| 规则ID固定为五项 | `RULE_IDS/classify_result`及`evaluate_rules` | no_artifacts/no_questions适用于首题，不是所有业务共同成功条件 |
| 轨迹转换只接受assistance调用形状 | 历史 `src/hyperknow/eval_atif.py::_export`，2026-10-29随旧框架退役，代码见Git历史 | 课程生成的字符串响应/消息与工具Agent快照不同；不能直接复用转换器声称全业务ATIF |
| Grader只收到原始输入和最终TeachingResponse | `build_grading_context` | 无完整来源正文、产物data、已展示步骤或多轮状态；不具备评价这些内容的证据 |
| 后端代码版本未固定 | `finalize_evidence`的backend_code_version=None | 实际Prompt/工具/Skill哈希可追踪，但不等于业务代码或前端版本；系统改动的前后对照归因不完整 |

这些限制大多来自“一个单轮Case起步”的显式范围，并非首轮实现失效。明显障碍在于直接把它当全业务通用Runner，而不是首切片本身。

### 6.2 教学策略与业务契约耦合

- 系统提示词teaching_prompt与两个Skill重复规定澄清、分步、产物选择、suggestions及部分权限边界，导致同一策略有多处维护位置。重复是事实，导致模型错误是待实验假设。
- 简单概念问题也接收五种产物的说明与工具Schema、格式块及六字段输出约束。输入混合教学、UI和协议职责；是否影响质量须保持其他条件不变做对照，不预先声称删减有效。
- requested_artifacts/forbidden_artifacts由原始文本按关键词、否定前缀与指代规则派生，然后在工具与提交层硬约束。启发式误判可能阻断合理行为，不一定能由Skill补救；评测应保留原始意图和派生字段分别判定。
- 历史最多12个ready轮次、24000序列化字符，产物历史只含ID/kind/title；除显式白板前缀，不等于模型能看到历史产物完整内容。未提供的信息不能通过“请结合历史产物”补回。
- 模型必选适用Skill且显式hint必须加载，在此业务契约内合理；若实验比较“无Skill基线”，必须明确这是另一个实验条件，不能把原有skill_loaded硬门禁直接用于宣称教学效果。

来源：[assistance_generation.py](../../src/hyperknow/assistance_generation.py)、[assistance_storage.py](../../src/hyperknow/assistance_storage.py)、[assistance_domain.py](../../src/hyperknow/assistance_domain.py)及上列两个Skill。

### 6.3 课程的耦合发现

| 事实/限制 | 证据 | 对优化及eval的影响 |
| --- | --- | --- |
| 澄清必须产生问题，但可跳过 | generation.py的clarifying、domain.Clarification/resolve_answers | 若目标是“信息充分则不问”，先改变产品契约或缩小判据；不能只改Prompt。2–4与1–5口径差异也是维护点，不等于所有有效输出都错 |
| 原始网页证据不直接进入讲义/题组输入 | planning_context含report/sources；materialize_blueprint保留creation_run_id但不复制报告；lesson_context只取课程/大纲 | 原调研仍在创建run可回查，并非丢失；教学模型不能假称收到原网页；题组source_refs不等于网页引用 |
| 上游内容错误可能被下游忠实继承 | quiz_context直接提供真实讲义/大纲；validate_sources检查集合 | “忠于讲义”和“事实正确”必须分项。引用合法不抵消上游错误，不应只改出题Prompt |
| 内容单位与教学进度是显式层级 | UnitExpansionDraft/validate_expansion、lesson_storage、quiz_storage | 课程结构ready不等于全部讲义/题组已生成；局部改动须固定前置版本，不为比较最后一题重跑全课 |
| 完成标记不是掌握度 | complete_lesson与submit_quiz写活动完成；derive_course派生progress/next_item | 课时手动完成、练习提交、考核提交是行为事实；不能把100%进度当教学质量或考核通过 |
| 共享worker/模型与调用协议 | runtime.CourseService.work；Settings.model；三条生成记录路径 | 串行会影响等待体验；模型/网络/排队耗时应区分。日志形状不同不是业务错误，但限制现有轨迹出口的直接复用 |

必要的前后端DTO与渲染协议共享不自动算架构缺陷；浏览器特有影响见第5节。

## 7. 优化与评测的最小分层

建议按“要证明什么”划边界，而非按八个业务名建立八套平台。以下是后续建议，尚未实施。

| 证据层 | 输入与检查 | 不应声称证明 |
| --- | --- | --- |
| 内容/策略 | 固定真实业务输入，评价回复、规划、题目及必要来源；同时保留实际模型输入 | 全链路交付、用户真正看到或理解了内容 |
| 业务契约 | 真实HTTP、持久状态、工具结果、引用和事务规则 | 数学事实、来源支持或教学效果一定正确 |
| 跨阶段 | 在独立后端通过业务API准备真实前置状态，执行后续命令，检查上下游关系 | 一次通过就代表真人学习增益 |
| 浏览器 | 实际页面、播放确认、公式/图形、动画交互和刷新恢复 | 仅靠截图或DOM存在就证明全部语义、安全和教学效果 |

内容评价可复用真实已保存输出进行重评，但这只能比较裁判或判据，不能冒充修改教学策略后的新执行。局部生成实验要与真实业务调用保持一致并标记层级，不用手工SQL或伪provider构造成功业务证据。

## 8. 建议顺序与保留项

### 8.1 阻碍分级

| 优先级 | 问题 | 建议的最小动作 |
| --- | --- | --- |
| P0，目标对齐 | 八类地图被误当成现有八类eval；按需零追问与课程澄清契约冲突 | 每个Case先声明所属业务和允许行为，不先改模型；确认产品取舍后再修改不允许目标的契约 |
| P1，评测扩展前 | Runner/Case/规则/ATIF/Grader均绑定首题；无产物和来源证据，缺完整代码版本 | 选择下一类业务，补最小前置状态与证据入口；不要仅放宽Literal、替换题目就声称覆盖 |
| P1，跨端行为 | 建议继续的action分叉；feedback pending恢复白名单缺口 | 用无模型契约/恢复测试固定行为，再单独修小问题；不能靠教学Skill修复客户端命令 |
| P2，优化隔离 | 系统Prompt/Skill重复策略、产物说明全量装配、手工跨端Schema | 为一项能力划主要维护位置、记录实际输入；先证明重复/无关输入影响，再决定按需装配或类型校验改造 |
| P2，质量归因 | 上游错误继承、原网页不在教学输入、完成不等于掌握 | 区分来源合法/忠实/事实正确/教学适配/完成；固定真实上游版本做局部比较和小型跨节点回归 |

P0表示本次评测设计中的优先澄清，不表示生产事故；所有建议均未实施，不自动授权行为变更。max_tokens协议复验不是这次架构审计的主阻碍。

### 8.2 建议推进顺序

1. 先对齐业务契约与eval目标，确定哪些需求是允许行为、哪些要改变产品；Schema不允许的输出不能靠Prompt优化。
2. 为一项能力确定主要策略维护位置；从概念解释入手减少策略重复，保留代码权限和事务门禁，不把所有逻辑迁入Skill。
3. 新增下一类eval时只补该业务所需输入/证据/规则；逐步提取已证实公共机制，不先建注册器、DAG或八套Agent。
4. 固定真实运行的模型、Prompt/工具/Skill、Schema/上下文构建、代码版本和必要浏览器状态；改一个因素后再谈归因。
5. 补一个业务节点关系的场景，再按实际需要增加浏览器验收；不把轮数增加当成长程质量。

保留：显式课程工作流、SQLite单一事实源、独立run输入快照、按需工具循环、结构校验与一次有界修复、原子提交、真实失败记录及收费授权/幂等恢复。没有证据要求全盘推翻FastAPI/SQLite、引入多Agent、向量库或分布式队列。

## 9. 验证与边界

- 已执行无网络纯Schema检查：Clarification拒绝空questions；EvalCase拒绝auto/problem-solving；TeachingResponse模型输出要求六字段；两个产品Skill均为v2；ARTIFACT_SCHEMAS当前五种；Grader证据键仅original_input/final_response且tools为空。
- 纯Schema输入只是契约验证，不是业务成功样本，不写入Case库或教学数据库。
- 无网络调用pendingCommandForScope：progress命令被接受、feedback命令被拒绝，确认刷新恢复过滤缺口；没有发出反馈HTTP请求。
- 文档骨架/本地链接检查、Markdown检查、33个源码锚点及草稿占位检查通过；最终命令与边界记录在审计计划。
- 未运行真实模型、搜索、浏览器或性能实验；不新增教学质量/隔离保证，不覆盖旧eval原始评分，不把人工校准写成完成。
