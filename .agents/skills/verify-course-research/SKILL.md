---
name: verify-course-research
description: "验证课程生成重试保留已保存单元，以及research本轮问题ID和逐字证据闭合。修改课程取消、重试、晚到单元提交、validate_report或build_evidence_bundle时使用。"
compatibility: "Requires the repository uv.lock environment, Java 11 or later on PATH, and TLC tools 1.7.4 configured as TLA2TOOLS. Checks run offline."
---

# 验证课程恢复与research审计

课程重试不能丢失已经保存的单元。否则用户会丢失内容和稳定ID。调研报告必须保留本轮工具已用问题ID，证据必须指向保存原文。否则修复缺少上下文，课程依据无法审计。

## 执行检查

1. 按[验证入口](../../../docs/formal-verification/README.md)配置已固定版本的TLC。使用仓库的锁定Python环境。
2. 阅读[源码覆盖记录](references/coverage.json)及[research范围](references/research-coverage.json)。先核对覆盖函数，再执行检查。
3. 从仓库根目录运行 `uv run --frozen python scripts/verify_course_research.py`。只验证格式、源码摘要和故障锚点时加 `--validate-only`。
4. 检查新输出目录的 `summary.json`。正常模型、正常源码和恢复后的源码必须通过。模型变体必须违反指定性质，源码变体必须发生断言失败。导入错误、超时或解析失败不是有效反例。
5. 用 `/statechart` 阅读课程模型的正常与故障结果。采用[课程模型](assets/CourseRecovery.tla)、[配置](assets/CourseRecovery.cfg)及[视图](assets/view.mjs)。research结果是实际Python有限枚举，不把它画成字符串行为的替代模型。

查看已实跑的[正常状态图](../../../docs/formal-verification/charts/course-research/chart.mmd)及[最短故障路径](../../../docs/formal-verification/charts/course-research/mutation/report.md)。图表只作为本次核对记录，源码变动后仍须重新执行命令。

命令不访问作者数据库、不读取 `.env`，不调用产品模型或网页服务。真实源码故障只发生在临时副本中，不改工作区产品文件。

## 判断反例

- 课程性质为 `CommittedUnitsPreserved`。首个单元保存、停止、重试后，原单元仍须ready，完整保存内容与ID须等于首次快照。模型把守卫及写入作为一个SQLite事务，不能拆成有竞态的两步。
- research问题性质为 `CurrentRoundQuestionsClosed`。本轮每个搜索或阅读已用ID都须在报告声明，包括失败请求。旧轮和没有问题ID的兼容记录不强加新问题。缺失时错误必须带上全部缺失ID。
- research证据性质为 `VerbatimEvidenceBound`。未知来源或非逐字quote须拒绝。通过后每个片段的原文切片、主张、问题、关系和来源版本信息须与输入绑定。偏移使用Python字符索引，不是UTF-8字节索引。

课程主动故障将重试重置范围扩展到ready单元。research分别移除缺失ID拒绝、移除逐字quote拒绝，以及把片段结束位置错误设成起点。每一项均须被检查抓住。

出现当前实现反例时，按报告步骤用真实代码重放。若重放不成立，先修模型或检查。若重放成立，报告产品缺陷，不弱化性质，也不擅自修改产品代码。

## 保持源码同步

同步基线提交为 `e42d4cfe5eb79bec9e03ee18794328a6fd295038`。本次工作区有未提交修改，准确版本以覆盖记录的SHA256为准，不把HEAD说成包含这些修改。

源码漂移时门禁停止。用 `/maintain-formal-verification-skill` 重新核对事务、输入范围和故障见证。确认模型与当前代码对应后，才推进 `sync_commit` 与源码摘要。不要仅为变绿而刷新摘要。

## 解释通过结果

- TLC仅穷举一个已批准课程、两个单元、父子两个run及最多一次重试的有限模型。内容用有限符号表示，单元draft已通过领域校验是前提。
- research直接枚举两轮、两个声明问题、最多两个额外工具事件，以及三个有限Unicode原文、两个来源的保存组合、有限quote和引用组合。完整输入集合在覆盖记录及检查代码中定义。
- research枚举以已有成功搜索和可信已读原文快照为前提，不验证无成功搜索时的拒绝守卫，也不证明来源摘要与网络正文真实对应。该前提不能因检查通过而省略。
- 不证明无限输入、任意次数重试、SQLite自身正确性、网络真实性、主张语义支持、教学质量、最终必定成功或无损输出解析器。正常通过不等于整个课程生成系统已获形式证明。
- 已有课程全部ready门禁和调研工具预算仍分别由 `verify-course-flow` 和 `verify-research-flow` 负责。文件格式与检查实际运行不等于聊天界面的slash-command派发已经验证。
