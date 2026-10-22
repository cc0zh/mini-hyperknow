# 真实手写白板课堂闭环

## 目标与范围

- 用户授权继续下一阶段，白板普通文字需满足手写体要求。
- 交付：按课时生成并保存真实讲义，手写白板的单一播放器，锚定当前步骤的课堂问答，位置／问答恢复，手动完成与一致的课程继续入口。
- 不做：语音、上传、独立聊天、练习／考核执行、项目提交、掌握度算法、强制解锁、全课预生成或模板降级。
- 参考现有 Clone 课堂布局；参考仓库只读。沿用 Python／FastAPI／SQLite 和 React，Python 只用 uv。
- 收费调用使用本仓库既有配置，先用已有两门真实课程各验证一课；刷新、读取、重启和字体加载不应再次收费。

## 执行与验证

- [x] 核对现有代码与设计，冻结前后端契约。
- [x] 后端：有序迁移及备份、讲义与互动 schema、真实模型输入／一次结构修复、事务保存、命令幂等及单 worker 调度。
- [x] 前端：课程进入链接、手写白板与安全图公式渲染、播放／暂停／下一步／回看、问答与显式继续、保存状态与恢复。
- [x] 无 Mock 的直接函数、临时磁盘 SQLite、真实 HTTP／WS 与前端逻辑检查；构建及仓库检查。
- [x] 内置浏览器使用真实模型验证两种主题、进度与问答、刷新和服务重启不重复生成；记录实际用量及未覆盖条件，不猜金额。
- [x] 同步设计、运行说明、质量状态、history 与可迁移知识；更新入链并归档本阶段计划。

## 集成契约

以下为本阶段实施契约，实际类型由 Pydantic／TypeScript 落实，不生成测试替身或人工样本课程冒充收费成功。

- 原 run 扩展 `kind: course | lesson | question`（历史缺省为 course）与可选 session_id、script_id、interaction_id。复用既有 GET/cancel/retry；历史课程数据不删除。
- GET `/api/sessions/{session_id}` 与 `/api/sessions/{session_id}/lesson` 返回 LessonSnapshot：course_id、course_title、unit_title、lecture_title、session、script（可空）、progress、interactions、generation_run（最近讲义 run，可空）、completed；额外顶层version作为整个会话快照的单调版本，不能只按progress.version合并互动更新。
- BoardScript：script_id、session_id、course_id、content_version、schema_version、title、steps、created_at。BoardStep：step_id、title、narration、page（从1起）、column（1或2）、operations。每步1–6项，有序步骤不超过18。
- BoardOperation：kind 为 text/list/code/formula/box/arrow/highlight/mermaid；content 为普通文本／代码／TeX／Mermaid源码，items 为列表项（其他类型为空），language 为代码语言（其他类型为空）。框和箭头表达使用有内容的可读图形，不执行代码或原始 HTML。
- progress：script_id（可空）、cursor（-1代表尚未展示）、play_intent（paused/playing）、version、updated_at。GET/写响应/幂等重放在同版本下返回同一权威意图；恢复暂停由前端播放器初始状态控制，不能在GET篡改同版本快照。逐步串行确认后推进；回看位置与确认游标分离。
- POST `/api/sessions/{session_id}/prepare`：client_command_id，返回 LessonSnapshot；已有脚本直接读，已有活跃讲义 run 复用。失败／取消／中断只通过明确 retry 新建 run。
- PUT `/api/sessions/{session_id}/progress`：client_command_id、expected_version、script_id、cursor、play_intent；返回 LessonSnapshot。游标范围与脚本归属校验，多标签冲突不覆盖。
- POST `/api/sessions/{session_id}/questions`：client_command_id、expected_version（progress版本）、script_id、cursor、question（trim后2–2000字）、was_playing；同事务保存问题与 run，返回 LessonSnapshot。限定同课时一个活跃回答，模型只见已展示前缀及有界近期问答。
- Interaction：interaction_id、run_id、script_id、step_id、cursor、question、answer（可空）、was_playing、status、error、created_at。回答持久化后才能展示完成；失败仍保留问题。重试建立新 run，并更新对应互动的 run_id。
- POST `/api/sessions/{session_id}/complete`：client_command_id、expected_version（progress版本）、script_id；返回 LessonSnapshot。完成事实与父 Course.version 在同一事务更新，不重复完成；读课程时统一派生 progress、各 session.completed 与 next_item。
- WS 增加 `session:{id}`／`course:{id}` 通知，保持先订阅确认再读快照；通知不存唯一正文，GET可补偿。单 worker 同时处理课程、讲义和问答，沿用取消与重启屏障。
- 全部写入命令可跨刷新重试同身份；确定性拒绝后允许改输入，未知网络结果保留原命令。字体与图形失败不能假装已加载或静默丢内容。

## 风险与决定

- 字体配置已由后续替换任务取代，当前资源与验收见[字体参考](../../references/whiteboard-font.md)；本计划保留原课堂的非字体事实，不证明替换后的字体已验。
- 迁移：现有真实课程库有价值，升级前停止本项目服务并备份，不清空用户库，不停止其他项目；新代码与测试在临时真实数据库先验。
- 同步模型网络请求不承诺远端撤销；取消／停服不追加修复，晚到结果不得落库，重启不自动重新收费。
- 不让字体加载或 Mermaid 异步渲染驱动教学推进；文字和代码默认转义，公式不启用信任命令，Mermaid严格模式并清理SVG。

## 实际证据与交接

实施中维护此处；尚未实现或未验证的项目不勾选。首切片证据见[已完成计划](../completed/20261022-real-course-library.md)，白板与字体长期要求见[学习体验](../../design-docs/learning-experience.md)及[字体参考](../../references/whiteboard-font.md)。

- 已停本项目旧服务并用SQLite backup API备份v1库，原始两门课程、5个运行、9个命令及7次调用逐表一致；实际v2启动迁移后两门课程完整JSON哈希未变、调用仍7次。
- 最终本地检查：`npm.cmd run ci` 的21项Node、65项Python通过，包含真实SQLite迁移、事务回滚、并发与实际HTTP／WS；`npm.cmd --prefix web test` 的35项直接逻辑／真实KaTeX检查通过；`npm.cmd run build` 的typecheck与Vite构建通过。npm官方registry审计0漏洞，后续未改依赖。
- 审查修复：同version的GET/PUT不再返回不同play_intent；重试较早互动优先锁播放器，继续确认按interaction_id+run_id；模型SDK构造后增加调用准入门禁；断网后晚到保存不自动恢复播放。
- 新增并发测试实际复现同course父run两命令retry创建两子run的问题（失败为2而非1），随后在事务内拒绝已有后继的重复重试；同测试及最终65项Python检查通过。

## 实现文件与交付

- 后端：`src/hyperknow/lesson_domain.py`、`lesson_storage.py`，以及既有 generation／storage／runtime／main；课程、讲义与问题共用单 worker，不新增模型替身或微服务。
- 前端：`web/src/pages/Classroom.tsx`、`components/Board.tsx`、`lib/use-lesson*.ts`、`lesson-state.ts`、`board-rendering.ts` 与 `styles/classroom.css`；目录／课程库接入真实课时和完成状态。百分比仅展示保留一位小数，不修改服务端计算精度。
- 资源：字体配置已由后续替换任务取代，当前资源与验收见[字体参考](../../references/whiteboard-font.md)。
- 检查：`tests/test_lesson.py`、`test_lesson_http.py`、课程并发重试回归，以及前端课堂、图形、公式、格式逻辑检查。最终CI、生产构建、35项前端检查、63份Markdown lint及`git diff --check`通过；未放宽检查规则。直接规则输入不冒充真实模型；本次收费成功另由下列实际调用证明。
- 未修改`.env`、未读取其他项目凭据、未停止5173的Clone服务、未提交Git或发布部署。保留本地真实课程。

## 真实模型与浏览器验收

使用既有asyncio和手机摄影课程各一节，不重造目录、不注入讲义。浏览器为内置Chromium；桌面截图已实际查看，DOM核查视口为974×1002，无本次观察到的横向页面溢出。

| 范围 | 实际结果与边界 |
| --- | --- |
| asyncio讲义 | `run_8d76c9af4b624761a0f680db2e30d918`，真实生成9步，含Python3.13代码、列表、强调和Mermaid机制图；约39.5秒 |
| 摄影讲义 | `run_17c39bf976fb449b9f19c7e7e2e216dc`，首响应内容校验失败，仅一次修复后保存8步、4页×2栏；主题是默认手机操作、主体／背景与A/B对比，无硬塞代码或公式 |
| 两种真实插话 | asyncio `run_8dce64acbd5d479ab0df65a35cc74667`，锚定已确认第5步且`was_playing=true`；摄影 `run_ccc139d07e1b4fbc8f55024b9eff0145`，锚定第4步且`was_playing=false`。两答均具体针对问题，原讲义不变；回答后等明确继续，分别恢复原播放／暂停意图 |
| 真实问题上下文 | 只读核对两次模型调用的input_basis，displayed_steps分别为5／4，恰好cursor+1；没有未来步骤。近期问答有界，问题记录与锚点已保存 |
| 进度与播放 | 摄影从0步保持暂停，明确播放后真实定时推进到第1步；在持久意图playing时刷新，游标和version原样保留、前端已暂停。手动逐步检查首／中／末步与页栏，无重复推进；看完不自动完成 |
| 独立回看 | asyncio从确认第5步回看第4页Mermaid，服务端cursor/version未变，提问仍锚定第5步。原图自然宽212.6px被放大到656.6px、高2706px的问题实际复现；保留viewBox自然宽后为212.6×876.2px，并新增直接回归检查 |
| 字体配置 | 字体配置已由后续替换任务取代，当前资源与验收见[字体参考](../../references/whiteboard-font.md)；本表不证明替换后的字体已验 |
| 公式边界 | 两门真实内容没有公式，KaTeX以真实渲染函数正常／异常检查验证，未冒称数学课浏览器已验 |
| 手动完成 | 摄影完整8步后仍未完成，明确标记后为1/4=25%、Course.version=2且next_item指向下一课；asyncio明确标记后为1/13，UI为7.7%、服务端保留精度，下一课为事件循环调度。完成不是掌握度 |
| 冷重启 | 确认无活跃run、核对本项目进程后停止并重启；8张表逐行完整哈希前后一致，包含2份讲义、2条问答和摄影完成事实，调用总数仍12。浏览器实际经历断连／真实HTTP失败后恢复WS；asyncio9步和问答恢复，之后才手动完成asyncio |
| 缓存与重进 | 进入、刷新、切页、字体加载与冷重启没有新增调用；新标签的问答继续确认属于本标签安全状态，不因历史意图自动播放。失败／中断只显式retry，不读取即收费 |

收口时另在860px桌面窗口发现既有运行恢复列表因grid隐式最小宽度导致页面横溢，实际检查右边界924.5px；改用minmax(0,1fr)轨道及flex项min-width:0，等待三条真实运行与两门课程均加载后复验，页面scrollWidth=845≤viewport=860。最终课程卡分别显示25%／7.7%，继续入口指向各自下一课。

本阶段新增5次真实deepseek-flash调用：2份讲义各1次基础调用、摄影1次修复、2条问题各1次。模型返回汇总为prompt_tokens=16025、completion_tokens=20272、total_tokens=36297；数据库累计由7到12次。不知道账单单价，不推测金额。

本地忽略证据：`data/validation/20261022-classroom-pre-migration.json`、`20261022-classroom-before-restart.json`、`20261022-classroom-after-restart.json`、`20261022-classroom-model-audit.json`、`20261022-classroom-builtin-browser.json`，以及前端检查／构建日志。迁移前备份和自动v1备份位于`data/backups/`；真实截图仅作为界面证据，不能代替数据库和实际调用。

## 未覆盖与下一阶段

- V04的数学课／复杂图类型与浏览器危险内容场景没有用真实模型覆盖；本次不是所有白板输入均已人工验收。
- 本次实际触发一次成功结构修复，补上此前覆盖缺口；真实模型传输失败后的重试、课堂生成／回答在途中硬重启，以及课堂取消的真实晚到响应未额外收费制造场景。相关门禁／中断／回滚／幂等有直接规则、真实SQLite和HTTP检查，不能外推为全部收费时序通过。
- 练习／考核执行、可交互思考题、项目成果保存和完整V12仍未实施。后续先接真实题组、显式提交／结果停留，再接项目与完整活动进度，不回退到模板答案或假执行按钮。
- Vite仍提示Mermaid／ELK等大分包；当前动态加载Mermaid并构建成功，后续按实际加载指标缩减支持面，不用提高警告阈值冒充优化。
