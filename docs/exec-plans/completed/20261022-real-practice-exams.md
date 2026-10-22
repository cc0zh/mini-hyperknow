# 真实练习与单元考核闭环

状态：2026-10-22 本阶段业务范围已完成真实模型及内置浏览器验收，归档本计划；最终 CI、前端测试、生产构建、Markdown、差异与锁文件检查均已执行通过；模型及浏览器汇总证据已落盘核对。思考题、项目成果及完整 V01–V12 仍未完成，教学内容仍有人工核查债务。

## 目标与边界

用户授权实施已讨论的下一阶段：真实出题、作答保存、服务端计分、结果页停留、单元考核及继续入口。保留已实现的造课、课堂、双手写字体与全部既有未提交改动。

- 不做思考题、项目成果提交、主观题自动评阅、掌握度、及格门槛、强制解锁或全课预生成。
- 不使用 Mock／Fake／Stub、SDK 注入、接口拦截、回放或模板降级。确定性规则直接输入、临时真实 SQLite、实际 HTTP／WS 可以检查；真实模型与浏览器另验。
- 沿用 FastAPI／SQLite／React、单 worker、既有模型配置及 uv／npm 锁文件。不改 `.env`，不读取其他项目凭据，不停止 5173 Clone，不提交 Git／push／部署。
- 用户库升级先核对活跃任务与本项目进程并备份；开发检查使用独立数据目录。并行学习数据不清空、不回滚。

## 实施与检查

- [x] 核对现有设计、原始计分与共享契约，并落本计划。
- [x] 后端：出题结构／上下文与真实生成，迁移／缓存／取消重试屏障，作答与结果事务、计分与完成事实；直接规则、真实 SQLite／HTTP／WS 检查。
- [x] 前端：课后练习、考核、逐题反馈与下一题、显式结果提交、结果停留与再练；刷新／未知命令恢复、课程入口；前端逻辑与构建检查。
- [x] 集成审查：验证重复命令、多标签、版本、时间、出题来源和继续入口；修复本阶段引起的问题。
- [x] 真实模型与内置浏览器验收：练习及考核、三题型、答对／错／跳过、刷新和无活跃任务时冷重启；记录实测调用／usage与未覆盖项。
- [x] 同步长期设计／质量／运行说明，history与必要学习记录；更新入链并归档。
- [x] 最终门禁：CI、前端测试、生产构建、Markdown、Git 差异与锁文件检查通过；模型与浏览器汇总证据已落盘核对。

## 共享契约

本节是本次前后端实施契约，具体 schema 以代码实现为准；若调整须同步协作者。

### 题组与出题

- `Run.kind` 新增 `quiz`，另有 `quiz_id`、`target_type`（`practice|exam`）、`target_id`；复用 `/api/runs/{id}/cancel|retry` 与单 worker，最多一次结构修复，SDK不自动重试。
- `Quiz`：`quiz_id, course_id, unit_id, target_type, target_id, title, content_version, schema_version, source_refs, questions, created_at`。
- question：`question_id, kind(single|multiple|boolean), prompt, options[{id,text}], correct_option_ids[], explanation, source_refs[]`。题组 3–8 题，三种客观题均覆盖；选项ID唯一、答案属于选项、多选至少两个正确、boolean恰两项且一个正确；来源引用必须属于本次输入提供的范围。
- 课后练习仅基于已有真实讲义，无讲义时明确需要先准备讲义，不自动收费生成讲义；不要求先标完成或全部看完。单元考核用所属单元各课时真实大纲／要点及有界已缓存讲义，显示实际来源，不先生成整单元讲义。
- 同一活动只有一个已保存不可变题组；prepare复用题组或该活动已有生成记录，失败仅明确retry，不因进入／刷新／重连再次出题。再练一次复用同一题组。
- `GET /api/sessions/{id}/practice`、`GET /api/exams/{id}` → QuizSnapshot，无收费。
- `POST /api/sessions/{id}/practice/prepare`、`POST /api/exams/{id}/prepare`，body `{client_command_id}` → QuizSnapshot。
- QuizSnapshot：`course_id, unit_id, target_type, target_id, title, description, quiz:null|Quiz, generation_run:null|Run, latest_attempt:null|QuizAttempt, completed, version`。顶层version单调，供同步旧快照过滤；target唯一性校验，错误不冒充空题组。

### 作答与结果

- `POST /api/quizzes/{quiz_id}/attempts`，body `{client_command_id}` → AttemptSnapshot；若已有未提交尝试则复用，已提交后显式调用才新建。GET不建尝试。
- `GET /api/quizzes/{quiz_id}/attempts` → `{attempts:[QuizAttempt]}`；`GET /api/attempts/{attempt_id}` → AttemptSnapshot。
- QuizAttempt：`attempt_id, quiz_id, course_id, target_type, target_id, status(in_progress|submitted), version, cursor, question_started_at, answers[], result:null|QuizResult, created_at, updated_at, submitted_at`。cursor为当前题的零起点下标；当前题作答后保留原cursor与反馈，明确next才推进并持久化下一题起点；刷新不跳过反馈、不重置起点。
- answer：`question_id, option_ids[], skipped, elapsed_ms, correct, fast, points, answered_at`；已判定答案不可改写，不信任前端总分／判定。用时为客户端实际起点至确认作答的记录（非可信考试），服务端仅接受0–86,400,000的整数毫秒，拒绝浮点、布尔、字符串、负数与越界；超过24小时由界面明确提示按24小时截断；同命令重试保持原用时，不能借刷新或冲突重置。
- `POST /api/attempts/{id}/answers`，body `{client_command_id, expected_version, question_id, option_ids[], skipped, elapsed_ms}` → AttemptSnapshot。单选／判断点击选项提交，multi先选再明确确认；skip为空选项。仅当前题可答，必须先保存再显示反馈／解释。
- `POST /api/attempts/{id}/next`，body `{client_command_id, expected_version}` → AttemptSnapshot；当前已答且非末题才推进。最后一题明确“看结果”而非自动提交。
- `POST /api/attempts/{id}/submit`，同上命令／版本 → AttemptSnapshot；全题已答／跳过才提交，结果、完成事实、父课程version同事务。已提交结果只读，再次提交不重复计数；同命令重放先于版本／配置判断。
- AttemptSnapshot：`quiz, attempt, course`，其中course为当前派生课程，结果页及返回入口读此快照；顶层同步采用attempt.version。
- QuizResult：`total_score, max_score, correct_count, question_count, skipped_count, fast_count, best_streak, stars, total_elapsed_ms, scoring_version`。
- 计分严格沿用只读 Clone `quizScoring-CUGhpPfb.pretty.js` 的个人规则：600基础，≤10000ms快答+200，答对前连击×100上限400，错／跳过断连；双路径星级取大值。PracticePage／ExamPage源码均确认包含恰好10000ms的边界；无伪对手、无通过线。
- practice提交完成所属session（已完成不重复记）；exam提交完成所属exam。课时比例仍只算session，不偷换全部活动完成率；项目未开放保持真实提示。`next_item`原单元内session→project→exam顺序不改。

### 同步与异常

- WS增加 `quiz_target:practice:{session_id}`／`quiz_target:exam:{exam_id}` 和 `attempt:{attempt_id}` 主题；target通知为resource_type=quiz_target、resource_id=`practice:{id}`或`exam:{id}`。订阅确认后GET、版本合并、HTTP轮询补偿。
- 目标快照version须覆盖出题／尝试变化；attempt快照按attempt.version合并，命令回包后旧GET不能覆盖。未知结果在sessionStorage保留原方法／路径／请求体／命令ID，明确拒绝后才释放。
- 刷新／重连只读，不自动prepare、attempt或submit。进入结果不自动导航，不把再练的后续成绩覆盖历史结果。
- 迁移拒绝未来版本、提前备份；cancel／retry／interrupt均延续事务屏障，旧run不覆盖新题组，跨标签不双收费／双建未完成尝试。

## 证据与关键决定

执行时记录真实结果，不预填通过。首两个业务阶段证据分别见[课程库](../completed/20261022-real-course-library.md)与[课堂](../completed/20261022-real-whiteboard-classroom.md)。字体不变，本次不做视觉重设计。

原始目标与当前数据有并行学习可能：备份前核对在途任务，验收按明确实体记录；不能用回滚用户库制造一致结果。

### 本阶段验收矩阵

以下区分直接规则／临时磁盘 SQLite、实际 HTTP／WS、真实模型和内置浏览器。前两类可构造确定性输入，但不冒充模型生成成功或所有浏览器竞争时序均通过。

| 编号 | 场景 | 当前结果／证据 |
| --- | --- | --- |
| Q01 | 缺配置明确拒绝，GET／刷新不创建题组或尝试 | 已验：临时真实 HTTP 缺配置返回明确错误、无讲义拒绝练习 prepare、GET 不建 attempt／不生成；实际浏览器刷新及重入复用保存事实。见 test_quiz_http.py 的 reads_missing_configuration 与模型／浏览器记录 |
| Q02 | 练习依据真实讲义，单元考核依据实际单元范围 | 已验来源范围与上下文预算：真实三题组来源分别7／8／9项，input_basis留存；考核用单元大纲及预算内缓存讲义，不自动补讲义。人工核查发现摄影 q_plant_ab 概念问题，标待纠正，不宣称教学全部正确 |
| Q03 | 两主题真实题组均覆盖single／multiple／boolean | 已验：asyncio练习6题、摄影练习7题、asyncio考核6题，均真实 deepseek-flash、首次响应通过结构校验，非人工注题 |
| Q04 | 单选／判断点击即保存，多选明确确认，答错与跳过有解释 | 已验：asyncio三题型，含错单选、部分错多选及跳过判断；多选确认前无答案写入，确认后反馈／解释可读。真实逐题记录汇总为3／6正确、2200／6200、1星 |
| Q05 | 判题反馈刷新仍在原题，next后才开启下一题起点 | 已验：asyncio首题600分、46.789秒，刷新仍原题反馈；摄影保存两答案后next到cursor=2，冷重启起点不变。临时SQLite／HTTP另验next保存起点 |
| Q06 | 刷新／重连不重置用时，未知结果同命令重试不双答 | 已验规则、存储与HTTP的原命令／原用时重放；真实浏览器刷新、实际500／断线恢复不丢两答案及起点。超24小时截断提示与整数边界由前端逻辑／实际HTTP分层验证，未声称实等24小时；全部跨标签未知结果时序未覆盖 |
| Q07 | 最后作答不自动提交；看结果提交一次并停留 | 已验真实浏览器：末题答案后仍in_progress、result=null；明确提交才出结果并停留，重入仍同结果。重复submit与事务回滚由临时SQLite及实际HTTP补证 |
| Q08 | 计分含10000ms边界、连击上限、跳过重置及双路径星级 | 已验直接score_answers、临时SQLite的9999／10000／10001ms及实际HTTP用时类型／范围拒绝；真实三份结果2200／6200（1星）、5100／7400（3星）、0／6200（0星）。未声称浏览器精确复现10000ms |
| Q09 | 练习提交完成课时，考核提交完成考核而不是通过 | 已验：asyncio课时此前手动完成，练习提交不重复增长（课程v2、7.6923%）；摄影提交课时25%→50%、课程v2→v3，next未开放项目明确提示；考核全错仍提交，exam.completed=true、课程v2→v3、课时7.6923%不变，继续下一真实课时，明确“已提交”非通过 |
| Q10 | 再练复用题组且创建新attempt，旧结果仍可查看 | 已验真实浏览器：新attempt_6c9bdd6da713443e9e4bbf244f3a9827复用原题组，历史URL固定attempt_35c8ef13c83746b4a9e32faa613b0544，重入仍2200分；不因再练调用模型 |
| Q11 | 多标签prepare／attempt／answer／submit冲突与命令幂等 | 已验临时SQLite并发prepare／单未提交attempt与答案竞争、实际HTTP并发attempt／answer／submit；所有权predicate直接回归通过。浏览器6秒真实网络延迟不再busy卡住；精确跨页面迟到A／后继B时序未在浏览器复现，不标全跨标签通过 |
| Q12 | 旧用户库备份迁移v3，原八表既有记录不丢 | 已验：核实本项目服务与无活跃任务后SQLite backup；v2→v3原八表哈希一致、新三表各0行。见下方备份与pre/post-migration证据索引；未清空或回滚并行学习数据 |
| Q13 | 无在途任务时冷重启，题组／在途作答／已提交结果恢复 | 已验用户库无生成在途的冷重启：全部11表哈希一致、调用保持17；摄影未提交作答cursor=2、起点及两答案不变，asyncio已提交结果仍可重入。临时实际HTTP另验保存反馈／结果与排队quiz重启标interrupted；不代表真实模型调用中硬重启已验 |
| Q14 | 出题取消／失败／重试／重启中断屏障 | 已验真实函数、临时SQLite与执行器门禁的cancel／retry／interrupt及晚到结果拒绝，实际HTTP覆盖缺配置retry与启动中断标记；本次三次真实出题均一次成功，未触发quiz真实失败结构修复、取消晚到收费或在途硬重启 |
| Q15 | React转义题干／选项／解释，不执行模型内容 | 静态审查未确认来源安全问题，真实题目按文本展示；来源引用经schema校验。不是全部危险输入／协议的浏览器覆盖证明 |
| Q16 | 前后端、CI、Markdown及Git差异检查 | 已有：99项Python（65旧＋34新，其中28规则／真实磁盘SQLite＋6实际HTTP／WS）、此前21项Node、最新49项前端（含所有权回归）及TS／Vite构建通过，分包警告保留。最终复核通过：npm.cmd run ci（21项Node＋99项Python）、npm.cmd --prefix web test（49项）、npm.cmd --prefix web run build、Markdown lint（67文件／0问题）、git diff --check及uv lock --check，退出码均0；明确落盘日志与退出记录见下节 |

### 迁移与冷重启

- 迁移前核实本项目服务及无活跃任务，使用SQLite backup保存至 `data/backups/before-quizzes-20261022-194842.sqlite3`。v2→v3原八表哈希一致，新增quizzes／quiz_states／quiz_attempts三表均0行；没有以回滚制造验收结果。
- 用户库pre/post-migration及before-restart／after-restart证据位于 `data/validation/20261022-quiz-*.json`，属忽略的本地证据，不提交原数据库或日志。
- 摄影attempt保存两答案、明确next到第3题后，在没有在途生成时冷重启。全部11表哈希一致，model_calls保持17；cursor=2、question_started_at=`2026-10-22T11:57:44.404119+00:00`与两答案不变。浏览器实际遇到服务500及断线后恢复；这证明已保存状态恢复，不证明在途模型硬重启或全部网络异常时序。

### 真实模型与成本

复用原有讲义与课程，仅三次显式出题，model_calls总数14→17。三次requested／实际模型均为deepseek-flash、attempt=1、validated=true，无结构修复、降级或模板；本次没有为凑覆盖额外收费生成。

| 活动 | run／quiz | 题数／来源项 | 耗时 |
| --- | --- | --- | --- |
| asyncio练习 | run_fc0cdda9576b4a918f42aca2a09c8036／quiz_7fd9fb234c964b718314b7667bccf5d6 | 6／7 | 15,296ms |
| 摄影练习 | run_c4840ab9ae464fe0af489a7694426a5d／quiz_8e8ae38fde874d7aa9aea27cfe9ed901 | 7／8 | 6,770ms |
| asyncio单元考核 | run_a12b317827d441498a382886179e4fec／quiz_dc0c011ed5f54aab8b56714c5a104afb | 6／9 | 17,555ms |

实测usage合计prompt=12,514、completion=9,487、total=22,001 Token。未获取实际账单金额，不推算／猜测费用；此前造课／课堂调用与并行学习调用不归入本次三次用量。

### 内置浏览器事实

- asyncio练习：attempt_35c8ef13c83746b4a9e32faa613b0544，三题型全部经历，3／6正确，错single＋部分错multiple＋跳过boolean，2200／6200、1星。首题46.789秒得600分，刷新仍同题反馈；末题未自动提交。再练另建attempt_6c9bdd6da713443e9e4bbf244f3a9827，复用题组，旧URL重入保留原2200分。
- 摄影练习：attempt_ee03741b3d654a3498365e5d13130f79，冷重启恢复后明确提交，6／7正确、1跳过，5100／7400、3星；课时进度25%→50%、课程v2→v3，继续入口遇到未开放项目时明确提示，不造假链接。
- asyncio考核：attempt_ab45d14f7207452498f0fdce73271488，6题全错，0／6200、0星仍可提交；exam.completed=true、课程v2→v3，但课时进度仍7.6923%。结果表述是已提交／完成，不是通过；继续下一真实课时。原submit命令经实际HTTP再发送两次，前后快照完全一致、attempt版本13与course版本3不变，证据为 `data/validation/20261022-quiz-submit-replay.json`。
- 三路审查后修复两处前端竞态：卸载页面的旧命令A迟到时可能删除后继页面命令B；读取慢于5秒轮询时dirty持续为真，命令等待全队列排空而永久busy。所有权predicate直接回归已通过；真实浏览器使用Network.emulateNetworkConditions的6000ms网络延迟（不是拦截响应），实测POST／两个GET约6009／6010／6012ms，约6034ms出现反馈且pending=false。精确跨页面A／B迟到顺序未实际复现，不据此夸大。
- 教学内容限制：摄影q_plant_ab忠于已保存讲义，但在相机／窗户固定时转动植物，并不普遍等同于改变相机相对光线方向；人工核查标为待纠正。未手改讲义／题组或重造正确样本，后续见[教学内容债务](../tech-debt-tracker.md)。结构与来源有效不等于全部教学正确。

### 证据落盘与最终门禁

已保存并核对 `data/validation/20261022-quiz-builtin-browser.json` 与 `data/validation/20261022-quiz-model-audit.json`。浏览器汇总保存实际操作观察、三份结果、冷重启和6秒网络检查；模型审计确认3次真实调用、来源白名单、计分与用量。最终只读核对三份结果仍为submitted、无pending或可见alert，796px视口scrollWidth为781px；截图仅在工具会话中实际查看，不虚构落盘PNG。

最终同步执行并保存显式退出码：npm.cmd run ci（21项Node、99项Python）、npm.cmd --prefix web test（49项）、npm.cmd --prefix web run build全部退出0，见 `data/validation/20261022-quiz-final-checks.json` 及对应ci／frontend／build-final.log。曾有后台任务报告exit0却未生成日志，未采用该回执作为通过证据；已改用同步subprocess捕获输出并确认真实日志。Markdown命令为node调用本机markdownlint-cli2，对README.md、docs/**/*.md与web/public/fonts/NOTICE.md共67文件检查0问题；git diff --check与uv lock --check均退出0。分包体积警告保留，没有提高阈值掩盖。

文档收尾定向复核：18份本次编辑Markdown无NUL、代码围栏成对、无旧active计划入链；25个相对链接文件目标存在（检查退出码0）。这不是完整Markdown／CI／Git diff门禁，也未核读两份待补存JSON。

## 最终交接

- 已完成业务文件：后端quiz_domain.py、quiz_storage.py及generation／storage／runtime／main接入；前端Quiz页面、quiz-state与use-quiz-command／sync／target／attempt、真实课程／课堂入口；tests/test_quiz.py、test_quiz_http.py和前端直接逻辑回归。确切差异以本轮Git diff为准，保留原课堂与双字体未提交内容。
- 已同步长期设计：架构、产品／学习体验、模型工作流、数据／接口、真实验证、质量／运行与Windows说明；本计划归档至 `docs/exec-plans/completed/20261022-real-practice-exams.md`，history仅留诉求／结果／计划索引。轻量学习记录聚焦命令所有权比较后删除，不复制验收流水账。
- 未覆盖：真实quiz取消晚到收费、模型调用在途硬重启、quiz失败结构修复、全部跨标签时序及全部危险输入；不为补覆盖无谓增加收费。缺配置／并发／幂等／10000ms边界按规则、临时SQLite与实际HTTP证据分层报告。
- 后续产品范围：思考题真实保存与反馈、项目成果保存及恢复、适用项目贯通后的完整V12；V01–V12不能整体盖章。摄影教学内容问题先留债务，后续纠正须保留题组／历史尝试身份，不无声改写已保存结果。
- 交付约束：没有commit／push／deploy或修改.env；保留本地数据与此前未提交改动。最终检查及两份汇总证据落盘已完成；不把静态／本地检查扩写为全部产品验收。
