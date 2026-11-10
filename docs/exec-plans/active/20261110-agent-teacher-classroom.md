# 实施产品与 Agent 协同的教师课堂

状态为待用户审阅的执行方案，2026-11-10。仅规划，尚未开始产品实现或收费教学验证。
两候选综合与 Cross-judge 缺口见[arena 综合记录](20261110-agent-teacher-classroom-arena.md)。
学生得到可回应反馈、允许打断且讲解与板书对应的单个老师。维护者继续使用现有运行、白板、SQLite 和命令机制。
目标设计见[产品与 Agent 协同的教师课堂](../../design-docs/agent-teacher-classroom.md)，当前基线见[前一阶段计划](teacher-led-classroom.md)。
实施顺序是 PR01、PR02、PR03、PR04、PR05、PR06。标识表示本地可评审切片，尚未创建远端 PR。

## How to read this

One box is one unit of work. Every box names the evidence that checks it. Check a box only when its evidence exists.
正文是 how-to。新类型、字段、格式号、端点与性能阈值都是待验证的实施提案，不是已有能力。
执行采用 `C:/Users/cc/.agents/skills/poteto-mode/playbooks/autopilot-stack.md` 的依赖顺序和不合并原则。权限以本仓库约定为准，本轮不武断套用云 VM、自动推送或开 PR。
用户尚未授权实施、收费模型、推送、发布或真人参与。获得相应明确授权才进入对应门禁，未授权项保留 blocked。
Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] 获得本地实施授权后再改业务代码。获得单独的真实模型预算授权后再运行收费验收。保存脱敏的授权记录。
- [ ] 固定代码基线、目标设计内容摘要和用户已有未提交文件。初次读取的 `master` HEAD 为 `dce1b47a9e075b7ddc588313e5088cade6e6dd20`。规划期间其他操作将 HEAD 推进到 `18bc510a3e293ad42e2fe94c99920a709aafd1a9`，本会话未执行提交，不能回退该变更。开工重新确认实际基线。
- [ ] 保留现有 `teacher-led-classroom.md` 的历史验收，不把本方案的目标写成已完成，不修改旧失败记录。
- [ ] 先用已有数据库备份机制验证新旧格式读取。不能自动替用户重新备课、转换历史回合、删除引用或覆盖旧板书。
- [ ] 从当前实际默认分支读取工作规范。仓库没有可确认的 `origin/main`，不能直接执行模板中的 `git show origin/main:`。
- [ ] 当前没有已验证的持久调度器，不假设 `/loop 1h` 存在。长任务使用有限执行及显式交接点，只有实际状态改变时发出 status message。
- [ ] 本地 origin 是磁盘路径，不假设 GitHub PR 能力存在。下文的 PR 标识只表示可独立评审的本地切片。提交、推送、开 PR 和合并另需授权。

### Spawn owners

- [ ] 明确开工后由一个端到端 owner 持有共享教师协议、存储和命令，不让多个 writer 修改同一文件。以实际分支与提交为证据。
- [ ] PR01 后做 PR02，随后 PR03 和 PR04 的独立文件可并行，PR05 收口后才进入 PR06。每片自己通过再推进依赖。
- [ ] PR01 至 PR05 都改变交互，最终合入前由用户查看截图与真实演示。PR06 若只改检查与证据，不改变交互。
- [ ] 吸收候选 B 的白板最小改动。复用现有安全布局，只为新段落分组、对象定位和展示结果补能力，不先重写布局算法。

### PR mechanics, for every slice

- [ ] 未授权提交、推送和开 PR 时只交付本地 diff、检查回执及用户文件保护哈希，不尝试解析 forge 或创建 PR。
- [ ] 获得相应授权后再按 opening-a-pr.md 解析实际 forge，不能把本地 origin 当成 GitHub。保持 hooks、锁文件和仓库门禁，不自动改用户工作。

### Verdict and merge, for every slice

- [ ] 一个 verdict 只对应已验证提交。改动后的新提交重跑受影响验证；基线既有失败单列，不伪装本片引入或已修复。
- [ ] 最终停止在经过验证的本地交接或获准的 merge-ready，不自动合并。交互审阅和真人结果不能由模型代签。
- [ ] 十条 live lane 是验证场景，不是假定十台云 VM。使用配置的 `OpenAI/gpt-6.1-sol` 执行，可在互不干扰的本地数据目录顺序运行。

### Boot recipe, for every live lane

- [ ] 使用精确 head SHA 和获准真实隔离课程。记录基线 SHA、head SHA、场景、模型与数据身份。基线没有功能时如实记录，不能编造对等结果。
- [ ] 按附录的真实 Windows 命令启动自有后端和 Vite，以 health.storage_id 核对。禁止使用作者默认库、API 拦截、假模型或响应回放。
- [ ] 每 lane 的截图放到已创建的 `data/validation/teacher-classroom-run/live/PRxx/lane-n.png`，该目录必须绑定唯一 run；预算未批或驱动缺失时标 blocked。
- [ ] 每片性能检查先记录实际 trunk 基线。此处 trunk 指当前确认的默认分支，不写死 main。不运行 `/loop 1h`，也不执行不存在的 `git show origin/main:`。

## 贯通新备课并保护旧数据 (PR01)

**Depends on.** None. 允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `src/hyperknow/teacher.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/lesson_domain.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/prompts/classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/generation.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/lesson_storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/main.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/types.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/pages/Classroom.tsx`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_teacher_classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_lesson.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_lesson_http.py`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 在 `teacher.py` 提案新增 `TeachingPreparationDraft`、`TeachingPreparation` 和独立校验器。保留旧 `TeachingBasisDraft` 的读取，不把旧引用字段改成默认空值伪装迁移。
- [ ] 在 `lesson_domain.py` 提案新增 `teacher_preparation_context()`。从目标、课时提纲、概念与必要背景装配，不经过旧 `lesson_context()` 的来源门禁。研究材料若选用只作可选材料，其缺失和失配不能挡新备课。
- [ ] 同步 `prompts/classroom.py`、`generation.py` 的 schema、校验、结构修复与文案，允许教师用自身知识补充。不删研究、蓝图和题组的证据规则。
- [ ] 在 `lesson_storage.py` 按显式格式版本读取旧聚合和新聚合。新字段使用判别联合，未知版本给出格式说明，不篡改原文。格式号 `2` 是提案，开工先检查冲突。
- [ ] 提供绑定 `client_command_id`、预期版本和旧聚合身份的显式重新准备命令。新准备成功前保留旧课堂，失败、取消或中断不能丢内容。成功事务中归档原聚合后才切活动版本。
- [ ] 同步 `main.py`、`types.ts` 和 `Classroom.tsx`。新材料面板不再要求来源数量，历史来源仍可读。进入、刷新和 GET 不转换、不建 run、不收费。
- [ ] 运行教师、旧讲义规则和真实 HTTP 测试，新增无引用准备、损坏研究证据不挡准备、旧数据原文保留、重复命令、替换失败回滚检查。

**You see.**

- [ ] 学生可见结果是新课时可以无来源门禁地准备，旧课只读历史不消失。通过条件是新路径贯通而其他业务来源校验原样有效。 以快照、界面及请求记录核对，不只听模型自述。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `uv run --frozen python -m unittest discover -s tests -p test_teacher_classroom.py -v` 与 `uv run --frozen python -m unittest discover -s tests -p test_lesson.py -v` 及 `test_lesson_http.py` 同形命令。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 对同一真实课时准备入口比较当前基线与本片，基线无新版时记录缺失，只验新按钮与数据保护。Save `data/validation/teacher-classroom-run/live/PR01/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. 无引用真实课时能明确准备；缺配置不伪造成功。Save `data/validation/teacher-classroom-run/live/PR01/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. 旧来源面板只出现在历史依据，新材料不要求引用。Save `data/validation/teacher-classroom-run/live/PR01/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. 刷新没有付费 POST 或新 run。Save `data/validation/teacher-classroom-run/live/PR01/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. 重新准备需要明确确认且旧文仍可查看。Save `data/validation/teacher-classroom-run/live/PR01/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. 取消准备保留旧课堂且有停止原因。Save `data/validation/teacher-classroom-run/live/PR01/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. 失败时不把旧课堂清空。Save `data/validation/teacher-classroom-run/live/PR01/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. 双标签旧版本得到明确冲突而不覆盖。Save `data/validation/teacher-classroom-run/live/PR01/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 课程研究与题组原引用仍原样可读。Save `data/validation/teacher-classroom-run/live/PR01/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 不支持格式有说明且不自动转换。Save `data/validation/teacher-classroom-run/live/PR01/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** The operator reviews before merge.

- [ ] 保存 screenshot，覆盖本片新增交互与异常状态，给 operator 核对真实位置和输入。
- [ ] 在已核验录制能力后保存30至60秒 video。若无录屏工具，保持这一证据缺口并请用户决定替代方式，不造文件。
- [ ] operator 看过实际截图与视频或明确批准的替代证据后才解除审阅门禁。没有合并授权则仍不合并。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## 生成段落并装配按需策略 (PR02)

**Depends on.** PR01。允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `src/hyperknow/teacher.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/lesson_storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/prompts/classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 新增提案 `src/hyperknow/teacher_strategies/`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `pyproject.toml`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_teacher_classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_assistance_domain.py`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 在 `teacher.py` 提案新增 `TeachingSegment`、`PresentationUnit`、`ClassroomContext` 和 `ClassroomRecord`，明确数据职责后再接工具循环。段落处理一个小目标，不预生成整堂课。
- [ ] 一个展示单元可以只有讲解、只有板书或两者都有。保存稳定的 segment、unit 与 object 身份，不用 board version 或每六个操作切帧来生成身份。
- [ ] `BoardLedger` 只以已展示板书初始化。校验单元顺序、对象归属、唯一身份、对象级 focus 和引用，禁止引用未来或被废弃后缀的对象。
- [ ] 段落、候选板书与必要持续记录一起校验并事务保存，状态只表示 `saved_pending_display`。不得保存即进入已授课或等待答案。第一版只在段落末尾交出作答权，避免隐藏后半段泄露答案。
- [ ] `_teacher_context()` 改成冻结本次实际 `ClassroomContext`。区分原话、暂时判断和未知，装入已展示前缀、实际提示程度、失败与待展示内容及连续事项。摘要不能取代原始记录。
- [ ] 需要补读时只提供当前课时、指定记录身份的有界只读入口，不给模型路径或跨课权限。上下文不足时明确停止，不截掉必要待答证据。
- [ ] 复用 `SkillRegistry` 和即时协助按需加载机制，提案新增独立可信目录 `src/hyperknow/teacher_strategies/`。先交付少量策略，最终数量由开工课例门槛决定，不先建策略平台。
- [ ] 每策略写问题、动作、观察与换法条件。run 冻结名称、版本、正文和摘要，初始只披露元信息，按需 `get_skills`，retry 使用原快照。空目录合法，学生不能指定路径，加载不增权限。
- [ ] 同步 `pyproject.toml` 的 package-data 并验证安装后的策略读取。纯策略正文可以与前端在独立文件并行，协议和共享存储保持单一 owner。
- [ ] 新增未来引用、稳定身份、讲解独占单元、前缀上下文、必要原文、策略越界、摘要失配和 retry 快照的规则、真实文件及 SQLite 检查。

**You see.**

- [ ] 学生可见结果是一小段可关联教学，而非固定五阶段播放器。待验证假设是策略按需加载能改善讲法，不能用策略标签变化证明。 以快照、界面及请求记录核对，不只听模型自述。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `uv run --frozen python -m unittest discover -s tests -p test_teacher_classroom.py -v` 与 `uv run --frozen python -m unittest discover -s tests -p test_assistance_domain.py -v`。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 同一真实课堂基线与本片对比段落入口，基线无段落则记录缺失并只验新增状态。Save `data/validation/teacher-classroom-run/live/PR02/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. 段落只处理当前目标且不会一次显示整堂课。Save `data/validation/teacher-classroom-run/live/PR02/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. 纯讲解单元不制造空白板。Save `data/validation/teacher-classroom-run/live/PR02/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. 新单元关联真实稳定对象并可定位。Save `data/validation/teacher-classroom-run/live/PR02/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. 已保存待展示的后缀没有进入已讲历史。Save `data/validation/teacher-classroom-run/live/PR02/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. 教师只按需加载策略且课堂目标不重置。Save `data/validation/teacher-classroom-run/live/PR02/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. 用户策略路径注入没有文件或新权限。Save `data/validation/teacher-classroom-run/live/PR02/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. 切换策略后原输入和待答仍能追溯。Save `data/validation/teacher-classroom-run/live/PR02/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 刷新复用保存段落且无付费请求。Save `data/validation/teacher-classroom-run/live/PR02/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 过大或无效段落明确失败且不显示半块板书。Save `data/validation/teacher-classroom-run/live/PR02/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** The operator reviews before merge.

- [ ] 保存 screenshot，覆盖本片新增交互与异常状态，给 operator 核对真实位置和输入。
- [ ] 在已核验录制能力后保存30至60秒 video。若无录屏工具，保持这一证据缺口并请用户决定替代方式，不造文件。
- [ ] operator 看过实际截图与视频或明确批准的替代证据后才解除审阅门禁。没有合并授权则仍不合并。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## 确认实际展示并关联讲解与白板 (PR03)

**Depends on.** PR02。允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `src/hyperknow/lesson_storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/main.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/types.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/use-teacher-classroom.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 新增提案 `web/src/lib/teacher-presentation.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/pages/Classroom.tsx`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/components/Board.tsx`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/board-scene.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 新增提案 `web/tests/teacher-presentation.test.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/e2e/teacher-classroom.spec.ts`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 在 `lesson_storage.py`、`main.py`、`types.ts` 提案新增 `presentation` 命令与独立展示版本，绑定课堂代次、段落、单元、前置位置、渲染尝试和命令身份。只允许确认当前前缀的下一单元。
- [ ] 在 `Classroom.tsx`、`use-teacher-classroom.ts` 提案引入展示控制。先渲染当前单元，等字体、公式和 Mermaid 等组件报告结果，再发确认。确认成功后才展开下一单元。
- [ ] 扩展 `Board.tsx` 和 `board-scene.ts` 的对象级结果回调与分组定位。取消六操作分帧和所有历史帧使用最新讲解，纯讲解不伪造空板书。
- [ ] 页面隐藏、离线、渲染失败或确认结果不明时停住。重放相同命令，不能生成新段落；失败不推进已展示前缀。
- [ ] 提问单元确认事务才激活待答。服务器记录的是客户端报告的渲染成功，不证明屏幕被看见、阅读或理解。
- [ ] 渲染后回执丢失允许恢复时重复展示同一个未确认单元，接受至少一次展示，不能承诺精确一次视觉出现。
- [ ] 只让历史定位访问已确认前缀。回看不回退服务端进度，纯讲解、focus、当前单元总览和输入草稿保持同步。
- [ ] 新增 `web/src/lib/teacher-presentation.ts` 与 `web/tests/teacher-presentation.test.ts` 的纯规则检查，覆盖稳定身份、排序、重复确认、失败、混合讲解与板书及历史定位。
- [ ] 用真实 SQLite 和 Uvicorn 检查乱序、旧版本和丢失回执；真实浏览器检查异步渲染与定位，不把函数测试算成体验通过。

**You see.**

- [ ] 学生可见结果是讲解、板书和强调对应，刷新恢复暂停，未展示后缀不进入教师的已讲上下文。自动展开已存单元与收费下一段必须清楚分开。 以快照、界面及请求记录核对，不只听模型自述。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `npm.cmd --prefix web test` 与 `npm.cmd --prefix web run typecheck`，以及教师 SQLite 与真实 HTTP 定向检查。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 同一已存课堂在基线与本片展开，基线缺独立确认时如实记录并验新前缀。Save `data/validation/teacher-classroom-run/live/PR03/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. 首单元讲解与板书对应。Save `data/validation/teacher-classroom-run/live/PR03/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. 1440×1000 桌面当前单元可读。Save `data/validation/teacher-classroom-run/live/PR03/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. 1024×768 桌面无关键内容裁切。Save `data/validation/teacher-classroom-run/live/PR03/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. 公式和 Mermaid 完成后才确认，失败不推进。Save `data/validation/teacher-classroom-run/live/PR03/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. 对象 focus 指向本单元已出现对象。Save `data/validation/teacher-classroom-run/live/PR03/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. 暂停后已保存内容不继续展开。Save `data/validation/teacher-classroom-run/live/PR03/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. 刷新恢复暂停且不增加模型调用。Save `data/validation/teacher-classroom-run/live/PR03/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 确认响应未知重试同命令不重计进度。Save `data/validation/teacher-classroom-run/live/PR03/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 只可回看确认前缀且草稿不丢。Save `data/validation/teacher-classroom-run/live/PR03/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** The operator reviews before merge.

- [ ] 保存 screenshot，覆盖本片新增交互与异常状态，给 operator 核对真实位置和输入。
- [ ] 在已核验录制能力后保存30至60秒 video。若无录屏工具，保持这一证据缺口并请用户决定替代方式，不造文件。
- [ ] operator 看过实际截图与视频或明确批准的替代证据后才解除审阅门禁。没有合并授权则仍不合并。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## 接通学生请求、打断与串行恢复 (PR04)

**Depends on.** PR03。允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `src/hyperknow/teacher.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/lesson_storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/runtime.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/main.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/use-teacher-classroom.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/lib/types.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/pages/Classroom.tsx`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_teacher_classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_http.py`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 提案新增 `ClassroomInput` 和 `PendingQuestion`。保存原始输入及锚点，模型意图解释另存。明确继续、先示范、跳过不自动结算为答案，混合文本允许同时含答案和请求。
- [ ] 待答绑定问题身份与版本、段落、单元和真实提示程度。旧标签页回答不静默绑定新问题，空白拒绝但单字符合法。
- [ ] 输入建 run 前先可靠保存，模型失败仍能恢复。问题可明确暂缓或跳过，不把无法判断当错答，不把提示后正确写为独立掌握。
- [ ] 输入或暂停先停止本地展开，保存最近确认位置与未确认尝试。被打断原段落保留，后缀标为废弃或被替代，不自动续播。
- [ ] 有在途请求时保留 `runtime.py` 的真实网络调用占槽。取消回执不代表远端取消，旧调用返回或超时后才允许新教师调用，不并发追加两个回合。
- [ ] 对 `_RecordingLLM.complete()` 和 `storage.py` 只做教师路径需要的发送前 in_flight、结果补全及 unknown 记录。不建设全业务新引擎，仍禁 SDK 自动重试。未知不重发，完整响应格式错才可在预算内有界修复。
- [ ] `finish_teacher_turn()`、准备完成与 retry 严查 run 状态、pending ID、课堂代次、准备 ID 和绑定版本。新版缺版本不能采用当前值缺省放行。
- [ ] 准备替换、取消或新版本后晚到结果不可覆盖。段落、板书、记录与 run ready 同事务提交，展示确认另事务处理。
- [ ] 前端 prepare、turn、cancel、retry、presentation 共用可靠命令身份和同步互斥，不能只靠异步 busy 渲染。HTTP 未知保留原 UUID，409 后读权威快照再决定新操作。
- [ ] 以真实函数、文件、SQLite、HTTP 与自有进程退出检查单字符、混合输入、待答过期、重复命令、取消晚到、未知恢复和事务回滚，不用假 provider。

**You see.**

- [ ] 学生可见结果是可以打断、先看示范和暂不作答，失败后原话不丢，恢复不隐式收费。真实 provider 在途取消与 retry 完成留到 PR06 验。 以快照、界面及请求记录核对，不只听模型自述。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `uv run --frozen python -m unittest discover -s tests -p test_teacher_classroom.py -v` 与 `uv run --frozen python -m unittest discover -s tests -p test_http.py -v`，另跑前端测试。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 相同控制输入在基线与本片提交，基线拒绝一字符须记录并验新版合法提交。Save `data/validation/teacher-classroom-run/live/PR04/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. 单字符有效答案被接收且原文保存。Save `data/validation/teacher-classroom-run/live/PR04/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. 混合答案与请求都进入上下文而非强制分类。Save `data/validation/teacher-classroom-run/live/PR04/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. 先示范暂缓原问题且不记错答。Save `data/validation/teacher-classroom-run/live/PR04/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. 跳过不变成答对或掌握。Save `data/validation/teacher-classroom-run/live/PR04/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. 打断在当前位置停止，不续播废弃后缀。Save `data/validation/teacher-classroom-run/live/PR04/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. 取消中实际网络槽未提前释放为第二回合。Save `data/validation/teacher-classroom-run/live/PR04/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. 旧问题版本冲突不静默换绑定。Save `data/validation/teacher-classroom-run/live/PR04/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 刷新恢复未知命令身份和原始输入。Save `data/validation/teacher-classroom-run/live/PR04/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 晚到结果不能覆盖新版本或新备课。Save `data/validation/teacher-classroom-run/live/PR04/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** The operator reviews before merge.

- [ ] 保存 screenshot，覆盖本片新增交互与异常状态，给 operator 核对真实位置和输入。
- [ ] 在已核验录制能力后保存30至60秒 video。若无录屏工具，保持这一证据缺口并请用户决定替代方式，不造文件。
- [ ] operator 看过实际截图与视频或明确批准的替代证据后才解除审阅门禁。没有合并授权则仍不合并。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## 收口完成和下游入口 (PR05)

**Depends on.** PR04。允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `src/hyperknow/lesson_storage.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `src/hyperknow/main.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/src/pages/Classroom.tsx`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `README.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/ARCHITECTURE.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/design-docs/learning-experience.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/design-docs/data-model.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/design-docs/api-and-events.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/design-docs/real-validation.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/SECURITY.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_teacher_classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_quiz.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `tests/test_quiz_http.py`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 默认不跨段自动收费。下一段只能来自明确用户命令，已保存段落自动展开不等于授权新模型调用。
- [ ] 将继续、等待和建议收束分开。建议收束保存回扣与未解决事项，不直接写课程完成。预算、超时、取消和结构失败保留运行停止原因。
- [ ] 保守提案是用户明确确认完成后才写 `activity_progress`，绑定当前课堂与已确认收束单元。该产品决定仍待确认，不授予教师自动结束权限。若未确认，就保留完成入口限制并明确说明，不自行扩大规则。
- [ ] 复用已有课程版本和进度更新效果，但新完成不依赖旧 script 的 summary。完成不表示掌握，重新准备不撤销原完成事实，未解决事项不被清空。
- [ ] 保留 `quiz_context()` 的现有题组规则。有旧讲义才显示清楚标注的历史讲义练习；没有旧讲义时明确尚未接入新版教师练习，不给注定失败的按钮。接通新教师练习另立产品范围。
- [ ] 同步 README、架构影响入口、学习体验、数据模型、API、安全与真实验证文档。质量状态只在新证据改变事实时更新，旧计划验收不重写。
- [ ] 检查未展示收束不可完成、模型声称结束无副作用、重复完成、刷新保持、旧完成保留和题组入口。先运行教师与 quiz 定向测试，再跑全量门禁。

**You see.**

- [ ] 学生可见结果是可以离开并保留进度，能明确区分讲完、主动完成和理解。新版练习未接入是已知边界，不伪装闭环。 以快照、界面及请求记录核对，不只听模型自述。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `uv run --frozen python -m unittest discover -s tests -p test_quiz.py -v`、`test_quiz_http.py` 同形命令及教师测试，然后 `npm.cmd run ci`、`npm.cmd --prefix web test`、`npm.cmd run build`。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 比较相同真实课时的完成入口，基线无新完成则记录并验新增显式确认。Save `data/validation/teacher-classroom-run/live/PR05/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. 模型声称结束不更改课程完成。Save `data/validation/teacher-classroom-run/live/PR05/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. 未确认收束单元不能完成。Save `data/validation/teacher-classroom-run/live/PR05/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. 取消或预算停止没有冒充老师总结。Save `data/validation/teacher-classroom-run/live/PR05/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. 用户确认完成只提升行为进度不显示掌握。Save `data/validation/teacher-classroom-run/live/PR05/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. 重复完成不会二次副作用。Save `data/validation/teacher-classroom-run/live/PR05/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. 重备课不撤销已有完成事实。Save `data/validation/teacher-classroom-run/live/PR05/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. 无旧讲义时新版练习入口明示未接入。Save `data/validation/teacher-classroom-run/live/PR05/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 有旧讲义时历史练习来源清楚且仍可用。Save `data/validation/teacher-classroom-run/live/PR05/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 主动离开后课堂状态仍可恢复。Save `data/validation/teacher-classroom-run/live/PR05/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** The operator reviews before merge.

- [ ] 保存 screenshot，覆盖本片新增交互与异常状态，给 operator 核对真实位置和输入。
- [ ] 在已核验录制能力后保存30至60秒 video。若无录屏工具，保持这一证据缺口并请用户决定替代方式，不造文件。
- [ ] operator 看过实际截图与视频或明确批准的替代证据后才解除审阅门禁。没有合并授权则仍不合并。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## 补齐真实教学、浏览器和 retry 证据 (PR06)

**Depends on.** PR05。允许的并行仅见 Program checklist。

**Files.**

- [ ] 修改 `scripts/verify_teacher_classroom.py`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `web/e2e/teacher-classroom.spec.ts`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/design-docs/real-validation.md`。以实际 diff 和对应检查回执为证据。
- [ ] 修改 `docs/exec-plans/active/20261110-agent-teacher-classroom.md`。以实际 diff 和对应检查回执为证据。

**Build.**

- [ ] 扩展 `scripts/verify_teacher_classroom.py`，记录冻结场景输入、策略快照、展示前缀、原始模型与工具、结果未知和源库哈希。显式 `--source-db`，新目录不覆盖旧 real-* 证据。
- [ ] 将取消场景与真实 retry 最终完成分开。重试必须实际 ready 且只提交一个新段落；创建后立即取消不能通过完整重试门禁。预算不足就保留 blocked 或 not_run。
- [ ] 按 T1 至 T7 从相同真实基线分支。每分支由人工核对内容正确、具体回应、教法变化、板书对应和未泄露检查答案，不要求非确定模型逐字一致。
- [ ] 扩展 `web/e2e/teacher-classroom.spec.ts`。写入前核对 health.storage_id、课程、课时、准备和段落身份；无证据 skip 必须报告未验。
- [ ] 用 1440×1000 与 1024×768 桌面检查字体、公式、Mermaid、对象定位、讲解滚动、暂停、打断和重连。保留截图与脱敏请求序列，不拦截或回放 API。
- [ ] 用自有服务做进程退出与网络中断，不杀未知进程。恢复只读先核对 run 与回执，证明没有新增收费调用后才继续。
- [ ] 真人学习效果独立安排并另获参与及材料授权。保存独立作答、迁移和必要前后测，控制重复题泄露，不把控制输入、模拟学生或满意自述当成收益证据。
- [ ] 四层分别记 pass、fail、blocked 或 not_run。没有真人结果时只写学习效果未验证，不影响诚实报告已经证实的工程与体验结果。

**You see.**

- [ ] 本片依赖前五片和预算批准。固定同一知识点、准备版本和展示前缀，逐项执行附录 F 的 T1 至 T7。学生原话、教法变化、板书和恢复状态在界面与权威记录对应，不能用旧证据代跑。

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] 运行 `npm.cmd run ci`、`npm.cmd --prefix web test`、`npm.cmd run build`，收费命令必须先按附录批准预算。保存用例计数与退出码，并检查零匹配或 skip 不冒充通过。

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `OpenAI/gpt-6.1-sol` at the PR head. 实际模型验证与交互写入均受附录预算门禁约束。

- [ ] Lane 1. Regression lane against trunk. 重跑基线与本片证据读取，旧脚本无新场景须记录，新增门禁不伪通过。Save `data/validation/teacher-classroom-run/live/PR06/lane-1.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 2. T1 正确解释得到减少重复与适当新任务。Save `data/validation/teacher-classroom-run/live/PR06/lane-2.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 3. T2 具体误解得到针对性修正。Save `data/validation/teacher-classroom-run/live/PR06/lane-3.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 4. T3 没听懂时实际改变例子或步骤。Save `data/validation/teacher-classroom-run/live/PR06/lane-4.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 5. T4 先示范与暂不答不被逼问。Save `data/validation/teacher-classroom-run/live/PR06/lane-5.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 6. T5 未备课知识可以适当补充。Save `data/validation/teacher-classroom-run/live/PR06/lane-6.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 7. T6 提示后正确不写独立掌握。Save `data/validation/teacher-classroom-run/live/PR06/lane-7.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 8. T7 打断刷新后位置与待答一致。Save `data/validation/teacher-classroom-run/live/PR06/lane-8.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 9. 真实 retry 达 ready 且恰好提交一个新段落。Save `data/validation/teacher-classroom-run/live/PR06/lane-9.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。
- [ ] Lane 10. 冷重启读取无新增模型调用，四类证据分开报告。Save `data/validation/teacher-classroom-run/live/PR06/lane-10.png`. Pass when 对应断言在真实界面和权威记录一致，证据不足写 blocked。

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. 记录同一真实已保存课时的无模型快照 GET p95、命令响应到当前内容可读的浏览器时间，以及本片新增动作的请求数。新模型生成耗时单列，不用旧整回合与新首单元做虚假比率。
- [ ] Probe. 固定两个 SHA、相同获准隔离内容和本地启动配置。先各预热五次，再按 trunk、head、head、trunk 顺序做十组不收费采样，各得二十个样本。冷启动字体另列，不能混入暖机比率。
- [ ] Baseline. 先填写实测 trunk 值、机器与数据量，再开始 head 比较。本轮未测，不能填假数。基线没有新动作时标缺失，分别测本片新增工作及端到端可读状态。
- [ ] Rule. 提案门槛为共同 GET p95 不超过 max(500ms, trunk×1.25)，已保存内容展开至可读不超过3000ms，未授权模型请求为0。数值是待开工确认的性能预算，不是实测或既有承诺；任何修改需证据与明确决定，不为绿灯自动抬高。

**Review gate.** None. PR06 is not review-gated. 若实施改变了产品交互，必须升级为有截图与视频的用户审阅。

**Merge.**

- [ ] 核对本片实际 diff、对应 SHA、所有检查回执及已知 blocked，形成不可混用旧提交的 verdict。
- [ ] 当前权限只允许方案交接。实施获准后仍停止在本地验证或获准的 merge-ready，提交、推送、开 PR 和合并另取授权。

## Close the program

- [ ] 六片与七个教学分支均有逐项证据或明确未执行原因，没有用历史通过替代新协议。
- [ ] 按工程、教学、体验和真人学习效果分别报告，不宣称没有真人证据的收益。
- [ ] 按仓库规则写 history，只有知识和权衡满足门槛时写 learning。归档前更新所有入链，长期决定回写设计，质量状态仅在事实变化时更新。
- [ ] 交付本计划、真实命令结果、已授权范围、未完成项和下一步，不启动新的未授权工作。

## Appendix A. Prototype evidence

本轮没有代码原型、教学模型、浏览器或性能实验。只读源码足以确定实施顺序。真实策略收益、段落可读边界、异步渲染回报和 provider 工具兼容仍待开工后的隔离门槛实验。
实验前固定一个知识点、数据、模型与批准预算。失败或不确定结果原样保留，不因设计目标宣称有效。

## Appendix B. Alternatives rejected

- 只删 Prompt 不够，schema、校验、上下文、UI 和测试仍会卡来源，因此采用 PR01 的全链路新备课。
- 不就地改写旧数据或补造默认引用，采用显式版本读取与成功后替换，保留原文。
- 不做逐 token 教学执行或每单元一次模型，采用有界段落一次提交，复用最终屏障。
- 不把保存当展示。采用单元确认，接受刷新可能重复显示一个未确认单元，而非假称精确一次。
- 不因取消回执释放真实调用槽，保留串行占槽与 unknown 边界。
- 不顺手重写题组或多 Agent 平台，明示新版练习未接入，保留既有其他业务约束。

## Appendix C. Risks

- PR01 的旧记录保护必须验原字节与版本，不只验新数据可读。
- PR02 的长课聚合与策略轮次可能增成本，先有界，真实瓶颈出现前不拆通用事件系统。
- PR03 的渲染成功只是客户端报告，不表示学生真的看见或理解，未知确认要能恢复。
- PR04 涉及多标签与同步网络槽，不能把业务 cancelled 写成远端停止计费。
- PR05 的教师结束权限、显式完成和新版练习范围尚待决定，计划采用保守默认但不冒充产品批准。
- PR06 的模型预算、数据许可、真人参与与录屏能力未获本轮授权或核验，分别保留门禁。

## Appendix D. Links and reading list

- [目标设计](../../design-docs/agent-teacher-classroom.md)。
- [现有教师阶段与真实 retry 缺口](teacher-led-classroom.md)。
- [仓库计划规则](../../PLANS_GUIDE.md)、[安全边界](../../SECURITY.md)与[真实验证](../../design-docs/real-validation.md)。
- 实施 PR01 至 PR05 先读 `C:/Users/cc/.agents/skills/how/SKILL.md`。设计争议在实施前读 `C:/Users/cc/.agents/skills/interrogate/SKILL.md`，不能将其评审冒充已执行。
- 未来长任务按 `C:/Users/cc/.agents/skills/show-me-your-work/SKILL.md` 留本地决策轨迹，不把含隐私的原始课堂材料提交仓库。

## Appendix E. 当前源码与吞吐检查点

- `teacher.py` 的 `TeachingBasisDraft`、`validate_basis()`、`validate_turn()` 仍要求允许引用。`lesson_storage.py` 的准备入口仍调用带研究证据门禁的 `lesson_context()`，因此只删提示词不能贯通新设计。
- `_teacher_context()` 只取最近六回合并携带完整累计白板，没有区分已保存和已展示后缀。新上下文不能继续把整个候选板书当作课堂现场。
- `finish_teacher_turn()` 成功后直接切到 `awaiting_student` 或 `ready`，没有独立 presentation 确认。提问必须实际展示并得到确认后才激活待答。
- `start_teacher_turn()` 当前拒绝少于两个字符的回答，也禁止等待状态下无答案继续。这与单字符答案、先示范和暂不回答冲突。
- `_RecordingLLM.complete()` 在 provider 返回后才记调用，不能覆盖发送后进程退出的结果不明情况。新审计需要发送前记录，但不重建所有业务运行时。
- `quiz_context()` 的 practice 分支要求旧 `BoardScript`。新教师备课不能伪造成旧讲义来解锁练习，也不能借此把旧题组来源政策一起删除。
- `web/playwright.config.ts` 的真实入口是本地 Vite 与 Windows msedge。没有已核验的云 VM、持久调度或录屏工具，不把这些写成已经具备。

- [ ] Blocking first steps. 先定格式读取边界、模型提交与展示确认的差异、输入归属及收费门禁，再启动实施并行。证据是同一份协议测试。
- [ ] Independent workstreams. 协议稳定后，策略正文与前端展示可以在不同文件并行。真实模型验收等待端到端接通，不能提前宣称完成。
- [ ] Shared mutable state. 教师聚合、SQLite 提交、命令版本和学生待答事项由一个 owner 负责。不同作者使用独立分支或输出目录，禁止同改共享存储文件。
- [ ] Smallest safe decomposition. 不拆多教师或通用编排平台。每片完成当前路径和对应验证，再进入依赖片，避免只有 schema 没有可运行入口的长期中间态。

## Appendix F. 验收分支与收费门禁

学生原话、独立作答、提示后作答、跳过和无法判断分别保留。合法单字符回答不能因字数拒绝，混合输入不用学生先拆。

固定一个真实知识点、备课版本和已展示前缀。每个分支使用从该获准基线复制的独立临时库。只改变本次学生输入，不把不同随机课例的措辞差异算成教法适应。

| 分支 | 操作 | 通过条件 |
| --- | --- | --- |
| T1 | 提交有具体理由的正确解释。 | 老师使用实际理由，减少重复，给合适的新任务，不直接写掌握。 |
| T2 | 提交本课内的具体误解。 | 老师针对错误因果改变对照或示范，不只泛化表扬。 |
| T3 | 明确说出没听懂的位置。 | 老师换例子、补背景或缩小推演步骤，不能只改措辞。 |
| T4 | 请求先示范、跳过或暂不回答。 | 不持续逼问，不记错答，待答事项按真实请求暂缓或跳过。 |
| T5 | 请求与本课相关但未写进备课的知识。 | 老师允许补充，确有不确定时说明，不恢复来源白名单，也不获得网络或文件权限。 |
| T6 | 在明确提示后答对。 | 保存提示程度，不把回答记为独立掌握，下一步可以减少帮助或换情境检查。 |
| T7 | 中途打断，再刷新、重连或冷重启。 | 讲解、板书、输入锚点和待答仍对应，恢复暂停，不自动续播废弃后缀或自动收费。 |

### 收费验证先过预算门禁

- [ ] 收集待批准的模型、供应商、真实课程来源、隔离目录、场景清单、外部请求数上限、单次输出上限和整体停止条件。未经授权不执行。
- [ ] 先批准一个知识点的最小闭环，确认 provider 兼容后再批准分支验证。金额、请求次数和价格目前未定，不将现有循环上限冒充已批准费用。
- [ ] 每次内部模型调用、结构修复和显式 retry 都占用同一批准预算。预算不足、usage 未知或结果不明时停止后续收费动作，保留 not_run。
- [ ] 发送前落盘 in_flight 及命令身份。超时、断连、取消本地 await 和进程结束都不能证明远端停止计费。结果未知不自动重发、不自动换模型。
- [ ] 真正完成一次 retry 并检查最终提交。旧计划的 `retry_completed=false` 不因重试命令创建成功而变成已覆盖。
- [ ] 只复制获准的真实课程与必要创建记录，明确 `--source-db`。目标库不得等于源库，前后记录源库哈希，只停止本次拥有的服务。
- [ ] 保留全部失败和证据不足的结果。禁止访问 `eval_result/2026-10-29/`，禁止扫描或上传整份用户历史。

工程检查核对真实命令、事务、版本、取消、恢复及原始轨迹。教学检查由人工核对内容正确与针对性。浏览器检查验证实际展示。真人学习效果需要独立作答、迁移和必要的前后测。四类结论分别报告，不以模拟学生、schema 通过或模型自述替代真人收益。

### 复用真实命令而非猜测入口

以下命令是实施阶段入口，本轮尚未运行业务检查。先执行所改切片的定向检查，再跑全量。新测试文件必须先创建才调用，不把零匹配当通过。

```powershell
uv run --frozen python -m unittest discover -s tests -p test_teacher_classroom.py -v
uv run --frozen python -m unittest discover -s tests -p test_lesson.py -v
uv run --frozen python -m unittest discover -s tests -p test_lesson_http.py -v
uv run --frozen python -m unittest discover -s tests -p test_assistance_domain.py -v
uv run --frozen python -m unittest discover -s tests -p test_quiz.py -v
uv run --frozen python -m unittest discover -s tests -p test_quiz_http.py -v
npm.cmd --prefix web test
npm.cmd --prefix web run typecheck
npm.cmd run ci
npm.cmd run build
npm.cmd run check:docs
```

收费验收在取得模型与数据授权后执行。使用显式源库、课程和课时身份，端口占用时换空闲端口，不停未知服务。命令中的环境变量必须在开工审批时赋真实值，不从用户默认库自行取值。

```powershell
uv run --frozen python scripts/verify_teacher_classroom.py --execute --source-db $env:TEACHER_VALIDATION_SOURCE_DB --course-id $env:TEACHER_VALIDATION_COURSE_ID --session-id $env:TEACHER_VALIDATION_SESSION_ID --data-dir $env:TEACHER_VALIDATION_DATA_DIR --port 8047
```

脚本停止自有后端后，在独立终端把 `HK_DATA_DIR` 指向同一绝对隔离目录，再运行真实后端。

```powershell
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8047
```

另一个终端使用实际证据文件。Playwright 配置负责本地 Vite。浏览器验收默认只消费已保存真实证据，新增任何教学调用仍占已批准预算。

```powershell
$env:HYPERKNOW_API_ORIGIN = 'http://127.0.0.1:8047'
$env:HYPERKNOW_WEB_PORT = '5174'
$env:HYPERKNOW_TEACHER_CLASSROOM_EVIDENCE = $env:TEACHER_VALIDATION_EVIDENCE_FILE
npm.cmd --prefix web run test:browser -- teacher-classroom.spec.ts
```

每个独立终端都显式设环境，不能假设上一 shell 的赋值保留。现有配置只在失败时截图，实施时需给每个要求采证的场景加显式截图。当前未核验录屏能力，交互审阅需视频时保留缺口，不编造文件。

## Appendix G. 规划轮的实际验证与交接

2026-11-10 已完成两份候选的完整阅读、逐项评分和综合。采用 A 的状态边界，吸收 B 的共享文件串行责任和白板复用。没有独立跨家族 Cross-judge 通过。

- [x] 本机 `check-plan.mjs` 已实际运行，输出 `6 PR sections, 0 problems`。这仅证明计划结构，不证明产品或性能。
- [ ] 最终仓库文档链接检查、用户已有文件哈希复核和差异检查在交接前更新实际结果。
- [ ] 教学模型、真实 retry 完成、浏览器、性能实验和真人效果本轮未执行。保留在对应实施门禁，不能勾成完成。

本轮采用 Sequence work into verifiable units，把改造拆成六个可核查切片。采用 Separate Before Serializing Shared State，使共享教师聚合只由一个 owner 修改。采用 Model the Domain，将生成、展示和待答分别建模。采用 Prove It Works，要求真实模型产物、界面及权威记录互相核对。采用 Laziness Protocol，沿用现有教师、白板和运行机制。
