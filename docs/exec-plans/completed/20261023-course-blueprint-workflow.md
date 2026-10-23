# 调研驱动的蓝图确认与逐单元生成

## 目标、范围与风险

- 用户要求：调研Agent成功后提交，进入下一阶段。调研提交为 `acd1029`；本阶段实现此前已确认的全局蓝图形成后确认一次，再自动逐单元展开，非单元逐个审批。
- 目标链路：澄清 → 真实网页调研 → 全局蓝图（课程／单元骨架）→ 等待确认或调整意见 → 按顺序展开单元内讲次／小节／考核／项目阶段 → 完整目录；讲义继续逐课按需准备。
- 包含：来源进入规划上下文、确认版本与幂等、部分课程持久化、局部提交、生成进度／来源展示、失败／取消／中断保留已生成内容。
- 不包含：项目成果提交、思考题反馈、语音、上传／知识库、通用图编辑器、自由聊天和多Agent。课程内项目仅生成要求，不恢复暂缓的提交功能。
- 风险：重复收费、未确认提前展开、晚到结果覆盖确认版本、部分目录误报100%、全局项目引用不一致。以显式阶段、SQLite事务、稳定ID、版本与来源校验及统一进度派生约束。
- 授权：本地实施／真实验证及已完成阶段commit；不发布部署，不写只读参考仓库，不混入先前项目暂缓相关未提交改动。

## 进度与决定

- [x] 复核调研真实成功证据并独立提交，保留无关工作区变更。
- [x] 明确服务端／前端契约与实施边界。
- [x] 后端分阶段课程运行、全局蓝图确认／调整、逐单元保存与恢复。
- [x] 前端真实阶段／来源／蓝图与单元结构展示、确认／调整命令与继续入口。
- [x] 直接规则／真实SQLite／HTTP回归、前端测试与构建。
- [x] 独立数据目录真实模型／搜索／浏览器贯通，记录费用与未覆盖项；缺外部依赖不伪造通过。

### 契约与接入

- 2026-10-23用户补充：不需要保留旧课兼容。统一课程run为 `workflow=blueprint-v1`，不增加历史run／目录转换或旧造课降级分支。SQLite仍用v3 JSON扩展，不主动清空真实数据；验证使用独立数据目录，旧数据读取不作为本阶段要求。
- 通用run status增加 `awaiting_blueprint`；生成中的 `stage` 为research／blueprint／units（澄清仍用clarifying）。course_id关联唯一Course结构，不另存可独立编辑的run目录副本。research记录复用既有来源／报告结构。
- 蓝图形成即保存Course骨架：`structure_status=blueprint`、`blueprint_version`、`creation_run_id`；units保留稳定ID、目标、预计规模、计划项目引用和考核目标，lectures/exams/project_stages暂为空。预计规模不作为已生成课时统计。
- `POST /api/runs/{id}/blueprint` 接受client_command_id、expected_version、approve、feedback（调整时非空）；批准进入自动units阶段，调整仅重做未批准的全局规划并提升蓝图版本；绝不因折叠／GET触发确认或模型调用。
- 单元 `generation_status` 为pending／generating／ready／failed／cancelled／interrupted。每次仅生成一个单元，保存后通知更新Course与run，再推进下一单元；没有第二次用户审批。新小节包含教学深度标签（直觉／定义／推导／理论／实操），进入实际讲义上下文。
- `structure_status=expanding`直到全部单元通过校验后才ready；部分课程不宣称完整目录或整门课100%。next_item可为generation，关联creation_run_id；项目／考核完成语义不变，不为旧数据做迁移。
- 显式重试建立新run，复用已保存调研／蓝图和已生成单元，保持课程／活动ID，恢复未完成阶段；不得重新设计已开始学习的单元。等待蓝图状态可重启恢复，在途任务重启标为interrupted，不自动发起费用。

## 验收与交接

### 自动检查

- `node scripts/ci.cjs`：242项Python与21项仓库Node检查通过。蓝图相关27项包括领域／SQLite13、实际HTTP／WS3及预算／锁恢复11。
- `npm.cmd --prefix web test`：61项通过；`npm.cmd run build`：TypeScript和Vite通过，保留已有大chunk提示；编译、文档及`git diff --check`通过。
- 并行审查修复同阶段队列去重丢推进、收尾SQLite锁导致worker退出、自动读取恢复后确认按钮不恢复、慢GET被轮询无限标脏、历史摘要及修复提示预算不匹配。直接规则检查不冒充外部服务成功。

### 本阶段真实证据

独立目录：`data/validation/blueprint/20261023-flow/`；模型deepseek-flash，API8018、前端5178，未访问用户原课程库或停止其他项目服务。

- 内置浏览器输入周末四小时Python asyncio目标，真实澄清后明确跳过。实际Tavily搜索2次，网页阅读尝试6次、成功2次、失败4次；报告仅引用实际已读来源并保存限制。
- 蓝图先保存为2单元／0课时；浏览器提交修改意见后v1→v2，未重新调研，仍0课时等待一次全局确认。同一course_id与单元ID保持。
- awaiting_blueprint时强停并重启API，前后run／course快照相同，模型调用仍9次；页面同步恢复后可确认，未自动批准。证据：`waiting-restart-evidence.json`。
- 浏览器只批准一次，单元自动按序生成。首单元完成、第二单元真实调用在途时显式取消；第二单元真实响应随后返回但未写回，首单元及run／course不变。证据：`partial-cancel-evidence.json`、`late-unit-rejected.json`。
- 浏览器重试新建run，只补第二单元，不搜索、不重做蓝图或首单元。同一课程最终2单元／4课时，目录ready、课时进度0%。原run为`run_95788e5f1ca548dabd5afc4b137e7337`，重试为`run_51f0a1cb5b18409296f39fb05ae99197`，课程为`course_b8045a3e672b4e8bb13dae00b69678c0`。
- 造课与取消／重试合计12次真实模型调用，返回98,650 tokens（prompt72,095／completion26,555）。核对实际model_calls的blueprint／units输入均有同一研究报告、有效source_id及真实摘录，hash和UTF-8预算匹配。未根据未知单价推算费用金额。证据：`evidence.json`与保留的SQLite／阶段快照。
- 浏览器进入首课只读，明确准备才新增1次真实讲义调用，形成8步；实际输入有intuition／definition／practice。再次强停／冷重启后课程、讲义、位置快照相同，总调用仍13，页面暂停且未重复生成。证据：`lesson-restart-evidence.json`。
- 1600×1100真实Chrome截图为`desktop-blueprint.png`／`desktop-ready.png`，两栏无重叠；内置面板窄视口沿用纵向降级，项目仍桌面优先，不宣称移动端验收。
- 即时重启对比通过后，活跃验收页的阅读进度继续推进到cursor=7；后续复核仍为同一讲义和目录、总调用13。另存`post-restart-reading.json`，不覆盖较早的重启证据，也不把后续正常进度变更误称为冷重启丢状态。

### 保留边界与交接

- 仅一个新主题，不等于两主题教学审计或V01–V12整体完成；旧课兼容、项目成果提交、思考题反馈均不在范围。
- 实际已读官方页面为当前3.15.1版Runners／Exceptions，任务／contextlib等页面失败；报告明确缺TaskGroup／shield及具体版本语义证据。课程固定3.11+，相关细节仍需目标版本核查；来源有效不保证全部教学结论正确。
- 真正在途取消已验；在途硬重启、所有模型修复／限额／DNS／重定向故障组合仍未全覆盖。预算及SQLite锁的本地检查不冒充这些外网故障证据。
- 长期契约已同步蓝图、API、数据、架构及学习体验。无新依赖、部署或用户库迁移；本阶段按用户授权单独提交，调研阶段提交为acd1029。
