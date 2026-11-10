# 维护现有形式验证与源码同步

## 目标与授权

用户执行`maintain-formal-verification-skill`。维护项目已有七项检查，仅改模型、检查工具、覆盖记录及技能文档。不修改产品源码，不读取作者数据库、`.env`或受限评估目录，不调用产品模型，不提交或发布。已有未提交成果保持。

当前HEAD为`e42d4cfe5eb79bec9e03ee18794328a6fd295038`。六项旧检查的同步基线为`c7a05d71dce441f1ddad8c8be2651f3c3cb39450`，组合检查已同步至HEAD。旧记录均另存dirty工作区摘要，不能把旧提交当作精确源码快照。

## 计划与吞吐

- [x] 定位七项检查、性质、边界和同步记录。
- [x] 修改前逐项实际运行并记录。
- [x] 阅读覆盖源码的提交及工作区差异，判断是否需要修改模型。
- [x] 从当前代码更新验证，不弱化性质或缩小边界。
- [x] 重跑、故障注入、恢复及反例判定。
- [x] 更新技能、同步记录、图表及最终逐项结果。

主线程持有全部验证文件写权限。两个只读scout分别审阅课堂`lesson_storage.py`与共享任务`runtime.py`，不得修改文件或重跑模型。主线程准备Git证据，负责其余摘要一致模块的提交审阅、原始运行、验证编辑和收尾。

每个检查仅在独立临时副本中运行真实源码故障。最多两个检查并行，输出文件按检查和阶段隔离，原始与后续输出不覆盖。原型数据为检查ID、性质、覆盖文件摘要、sync_commit、阶段及退出码，复用现有manifest和两个CLI，不建立另一套验证框架。

## 初始发现

七项检查为assistance-flow、classroom-flow、course-flow、course-research、quiz-flow、research-flow、run-lifecycle。仅`lesson_storage.py`和`runtime.py`的已记录源码摘要不同，其余覆盖摘要与当前一致。先保留这两项原始失败，不直接改摘要。

本地证据目录为`data/validation/formal-maintenance-20261110-0847/`，包含每项原始与更新后运行输出、所有相关Git差异、提交说明和未提交源码快照摘要。

## 提交与有效源码快照

已审阅`954568372be1f264119dac04690084636697a710`、`3a10fdfd27ea0fcf54c5f68a0f29c0c39043cfe5`和`e42d4cfe5eb79bec9e03ee18794328a6fd295038`的提交说明及覆盖文件差异。旧记录虽然写c7a05d7，但另存了脏快照。`source-history-matches.json`确认旧lesson_storage摘要匹配基线及后两个提交，旧runtime摘要匹配9545683和3a10fdf。runtime的继续生成机制不是e42新增，不能将它误判为本轮漂移。

其余覆盖文件摘要与现工作区一致。research_domain仍是此前已记录的未提交源码快照，不把HEAD冒充其内容。全部同步记录现指向实际核对的e42d4cf，工作区摘要仍是执行内容的依据。

## 维护判定

七项既定性质的最终命令全部退出0。下表的源码故障均只在隔离副本注入，基线、变体、恢复依次退出0、1、0。可读取的逐项统计保存在[维护结果](../../formal-verification/maintenance-20261110.json)。

| 检查 | 结论 | 验证变化与故障见证 |
| --- | --- | --- |
| assistance-flow | in sync | 同一源码快照。把拒绝两个产物的条件改成只拒绝三个产物，真实测试捕获。 |
| classroom-flow | updated | Ask允许首次确认前的cursor=-1。未改Summary性质。禁用最后summary门禁，真实测试捕获。 |
| course-flow | in sync | 同一有效源码快照。把全部单元ready改为任一单元ready，真实测试捕获。 |
| course-research | in sync | 同一已记录工作区快照。重置已存单元、取消问题闭包、取消逐字引用及破坏引用结束偏移四个变体均捕获。 |
| quiz-flow | in sync | 同一源码快照。禁用答完所有题目的守卫，真实测试捕获。 |
| research-flow | in sync | 同一有效源码快照。将十步预算拒绝条件从>=10改成>10，真实测试捕获。 |
| run-lifecycle | in sync | 新teacher路径不改变回执性质，只更新摘要和Start、Finish对应说明。禁用指纹冲突检查，真实测试捕获。 |
| 课堂再生成互斥探针 | bug | 当前实际代码允许较新teacher任务遮蔽活跃再生成。探针退出1，未作为通过计数。 |

finish_lesson_basis和finish_teacher_turn在各自事务中完成状态提交，不直接写command_receipts。创建请求仍经Database.command写回执。新增路径对NoConflictingReplay没有影响，因此run-lifecycle判为in sync，不因文件摘要改变就认定模型语义漂移。没有证据表明最后summary或固定命令指纹的承诺有意改变，因此没有改写性质。

课堂的有限单脚本模型此前多限制了cursor>=0，删除该限制后正常模型从18变成19个可达状态。新图将19个底层状态显示为8个标签状态，没有缩小常量。主动破坏Summary门禁时，最短反例仍是四个动作。全图的22个故障状态与运行器在首次违反处停止时发现的11个状态属于不同运行方式，不相互替代。

## 当前代码的真实反例

引入提交为e42d4cfe5eb79bec9e03ee18794328a6fd295038。下面五步已通过真实临时SQLite重放，不调用模型或网络。

1. 保存一份合法旧脚本。
2. 发起讲义再生成，确认旧脚本提问此时被lesson_generation_active拒绝。
3. 创建较新的lesson_basis任务，generation_run改为指向它。
4. 再对旧脚本提问，当前代码错误接受并保存pending问题。
5. 完成原再生成并替换脚本，当前交互列表变为空，数据库中该问题仍有一条记录。

损害是学生已提交的问题从当前课时交互列表消失。此问题不是CompletionRequiresSummary反例，不能靠修改该性质处理。完成后再生成重置cursor但保留完成事实的行为早已存在，本轮没有将其错误归因e42。

复现命令为`uv run --frozen python scripts/verify_classroom_regeneration.py`。`REGENERATION_GUARD_BUG`及`FAILED (failures=1)`是当前未修复产品缺陷，不是主动故障的预期成功。只保留验证探针和[已知缺陷](../../../.agents/skills/verify-classroom-flow/references/known-findings.json)，没有修改产品源码。

## 验收及工具故障

- 修改前五项通过，课堂和共享任务两项因源码摘要漂移退出2。它们是未能运行的门禁，不是两个已证伪性质。
- 第一次更新后，课堂TLC解析退出150。日志显示标准库读取共享全局Temp，发生NullPointerException，不能当作性质反例。运行器增加每JVM独立java.io.tmpdir，随后课堂检查和最终七项并行检查均通过。共享临时文件竞争是对工具故障的原因推断，不冒充已捕获的产品反例。
- 最终final-results.json记录七项既定性质全部退出0。七个主动故障模型均触发目标性质，十个真实源码故障见证均满足0、1、0。
- 最终独立产品探针仍退出1，确认脚本已替换、交互列表为0而存储记录为1。它没有混进七项通过统计。
- 已按最终技能命令重跑，静态验证七项覆盖及组合检查四个变异锚点。课堂statechart及Pele图表已重建。
- 覆盖产品源码摘要与修改前一致。Python3.10语法检查和check:docs通过。Git检查发现flows.md末尾多空行后，修复生成器trimEnd而不是手工修输出，重生成后定向diff检查通过。

命令、原始stdout、各阶段summary和版本信息均在前述本地证据目录。本次不提交、不发布，不启动产品服务。没有验证聊天UI的slash命令注册或分发。

## 未覆盖与后续

新增teacher_led教学回合协议尚无完整形式模型。旧脚本模型不穷举脚本替换、完成后的再次问答、所有位置写入交错或跨协议交互。当前已确认的互斥路径由独立真实代码探针覆盖。无限重试、数据库实现、网络来源真实性和教学质量仍不是本次证明对象。

本轮维护已完成。产品互斥修复需要作为另一次获授权的产品代码任务处理。之后必须保留失败探针，先验证其在修复前失败，再验证修复后通过，不能仅刷新覆盖摘要。
