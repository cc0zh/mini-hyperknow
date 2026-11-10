# 修复课程生成偶发失败

状态：2026-11-10 完成两项根因修复、相关回归和有界真实验收。仅本地交付，未提交、推送或发布。

## 目标、范围与风险

- 目标是定位真实课程生成失败，修复证据指向的最小原因，并在原失败阶段复验。
- 范围包含调研输出、单元内容校验及相应回归。不得用假内容、放宽证据规则或无限重试换取成功。
- 默认课程库只读。运行验收使用独立 SQLite 副本，保留原失败记录。真实调用可能产生供应商费用，只执行有界修复验收，不启动批量评测。
- 本轮仅本地修改和验证，不提交、推送、创建 PR 或发布。
- 关联契约见[蓝图工作流](../../design-docs/course-blueprint-workflow.md)及[真实验证](../../design-docs/real-validation.md)。

## 进度与决定

- [x] 在真实界面复现已有失败。隔离副本展示第八单元失败，前七单元及 42 课时仍已保存。
- [x] 用记录和直接校验确认根因，排除网络与状态误判。
- [x] 补充失败先行回归并实施最小修复。
- [x] 在同一阶段复验，运行相关检查并审阅差异。
- 2026-11-10：默认库中的两次 research 失败均保存 `OpenAI response ended with length`，最终调用的 completion_tokens 均为 4096。另有一次 units 内容校验失败，需独立确认校验原因。尚不推断两者同源。
- 2026-11-10：源码和[既有修复记录](../../histories/2026-11/20261109-2255-research-report-repair.md)确认调研上限已统一为 8192，并已有一次真实成功证据。本轮不重复修改或增加截断重试。
- 2026-11-10：末单元两份真实模型输出分别多出 `lectures[*].project_stages=[]` 和 `lectures[0].sessions_note=null`。当前严格 schema 因这些无内容的附加字段失败。仅移除这几个空附加字段后，两份输出均通过完整 schema 和 `validate_expansion`，保留所有课时、项目阶段与批准边界。这是边界处理候选的机制证据，不是已实施修复。
- 2026-11-10：比较两个独立设计候选。评分准则为真实反例可恢复、不丢弃有内容字段、不修改批准结构、API兼容、单一schema来源与最小维护成本。
- 2026-11-10：工具后台模式连续返回零时长空执行，确认服务和副本均未创建后，改用会自动接管为可跟踪任务的前台启动。服务使用 8051 和 5176，最终只停止本轮持有进程。
- 2026-11-10：本轮真实调研重试发现当前代码仍有同源反例。第六次响应正常结束，completion_tokens 为 4438，但六条 finding 均多出 `evidence_note=""`。这些空备注触发整篇报告修复，第七次响应在 8192 token 结束为 length。只移除空备注，原报告即可通过完整来源和逐字证据校验，含 6 条主张和 10 条证据。
- 2026-11-10：推翻“继续加大输出上限即可解决”的前提。新范围是研究报告和课程 draft 的共同 JSON 边界，不触碰课堂、问答、练习或即时协助解析。
- 2026-11-10：选择候选 A 的边界策略并推广到共享纯函数 `validate_model_output(schema, raw)`。先严格验证，仅当所有错误都是未知字段且值为 null、精确空字符串、空列表或空对象时，复制输入、按校验路径移除、再次严格校验。0、false、空白字符串、有内容扩展、缺字段和类型错误仍拒绝。证据及项目／考核规则仍由原有校验负责，不改变批准数据。候选 B 的独立替代方案仍在评估。
- 2026-11-10：候选 B 完成独立比较并收敛到 A。否决 provider 结构约束扩展，因为当前接口未暴露相应能力且缺少目标端点兼容性证据。两候选均保留严格 Schema、一次模型修复和原始输入。独立 Grok reviewer 对五项准则均给出 pass，无阻塞问题；新增注释与抑制为 0。

## 吞吐检查点

- Blocking first steps. 真实失败元数据先行，未确认机制前不改代码。
- Independent workstreams. 子代理只读追踪生产调用和历史，主线程检查运行记录与界面。
- Shared mutable state. 作者库只读，隔离验收库单一服务持有，代码改动交给一个 owner。
- Smallest safe decomposition. 暂不重构流程，按已证明的故障边界修复。

## 验收与交接

- 已读真实 runs 和 model_calls，未改作者库。
- 基线 `uv run --frozen python -m unittest discover -s tests -p 'test_blueprint*.py' -v` 通过 31 项。
- 隔离库对原调研失败执行一次显式真实重试，只验证当前代码，不回放供应商响应。
- `data/validation/course-failures-20261110/check_saved_outputs.py --strict` 直接校验显式选中的两份单元输出与本轮报告，修复前退出 1。该工具只读原始记录，不伪装成模型或业务完成验收。
- 同一工具使用修复后入口退出 0。原文输出分别为 `PASS units 1 sessions_or_evidence 7`、`PASS units 2 sessions_or_evidence 3`、`PASS research 6 sessions_or_evidence 10`，作者库摘要不变。
- 新增 `test_model_output.py` 11 项直接回归。严格骨架阶段实际出现三类 `extra_forbidden` 并以 `FAILED (errors=17)` 结束；实施规范化后全部通过。
- 已通过 `uv sync --frozen`、Python 3.10 AST 语法检查，以及 `test_model_output.py` 11 项、`test_blueprint*.py` 31 项、`test_research.py` 25 项、`test_research_runtime.py` 11 项、`test_research_http.py` 12 项，共 90 项，无 skip。均为直接规则、临时真实 SQLite 或实际 HTTP，不以模型替身证明业务。
- 未运行现有 `test_research_exa.py` 与 `test_research_web.py` 中含 mock／patch 的路径，以遵守当前拒绝 Mock 的验收约束；未删除或改写这些既有测试。
- 浏览器在修复后显式继续原第八单元，`run_e63ab2ed591f4ab9b24778cad7c9c9d8` 首次真实响应即通过，未发起结构修复。原 course_id 和末单元 ID 保留，8/8 单元就绪、49 课时；前七单元完整内容与身份逐项相等。证据为隔离目录的 `unit-before.json` 与 `unit-after.json`。
- 浏览器刷新后仍显示课程已保存、8/8 单元及 49 课时。刷新前后均为 6 条 run、39 条 model_call，没有新增生成。计数证据为 `unit-refresh-before.json` 与 `unit-refresh-after.json`。
- 文档骨架 `npm.cmd run check:docs` 通过，已检查本轮 tracked 差异无空白错误。
- 对本轮调研失败在新版服务执行一次显式重试 `run_500d80e50d8943158c63869738477e42`，两次报告响应均完整结束，但又暴露第二个独立原因。工具曾使用 `scratch_api`，模型报告却改为 `scratch_scope`，有限修复后仍遗漏原 ID。当前错误仅为 `tool calls may reference only declared research questions`，没有列出缺失 ID，修复输入中也没有完整工具轨迹，因此无法知道必须补回哪个标识。
- 直接规则实验仅在输入中补入缺失的 `scratch_api` 未解决问题及限制说明后，两份完整报告都通过 Schema、来源与逐字证据校验，确认剩余机制；实验结果未保存为报告，不冒充模型成功。
- 第二个修复仅在 `validate_report` 原循环收集并列出当前轮全部缺失 ID，让既有一次修复收到可操作的错误；初次及修复指令明确保留工具已使用 ID，包括失败请求的问题。无新 API，不自动补造问题、不放宽引用审计、不增加模型轮次。先加错误上下文回归再改实现。
- 本轮不做新的课堂、题组、教学质量或全部 V 场景验收。
- 第二个修复的失败先行输出含 `AssertionError: 'scratch_api' not found in 'tool calls may reference only declared research questions'`、`AssertionError: 'safety' not found in 'tool calls may reference only declared research questions'`，并以 `FAILED (failures=2)` 结束。修复后原有错误前缀保留，同时列出全部当前轮缺失 ID，旧轮、无 ID 及失败工具记录规则保持。
- 最终代码的相关无 Mock 回归共 92 项通过，包括 `test_model_output.py` 11、`test_blueprint*.py` 31、`test_research.py` 27、`test_research_runtime.py` 11、`test_research_http.py` 12。追加差异由主线程读取完整 diff 复核；此前无损边界另经独立 reviewer 五项准则审查。
- 最终真实重试 `run_4618f53141d84584a98adcce3bc994dd` 成功完成调研及蓝图保存。实际读取 3 份来源，报告 6 条主张和 11 条逐字证据，全部 3 个工具已用问题 ID 均保留。调研第 5 次响应正常结束，未调用结构修复；蓝图第一次响应通过，保存 2 个单元并等待显式确认。
- `check_live_research.py` 只读验收输出 `REAL_RESEARCH_BLUEPRINT_PASS`，结果在 `live-research-after.json`。浏览器也显示“查阅参考资料 已完成”和“请确认课程方向”。此处未批准新蓝图，不冒充另一门新课程已全部展开；完整展开的真实证明是前述原失败课程 8/8 恢复。
- 最终 `final-integrity.json` 证明作者库 SHA-256 与初始值相同，隔离库无在途生成。关闭本轮浏览器页，并停止本轮持有的 8051 后端和 5176 前端，保留所有隔离数据和失败记录。
- 已同步统一输出边界、蓝图和调研契约，并在学习记录说明空扩展字段与真实契约错误的区别。仓库另有并行文档工作，本轮未修改或回滚其文件。无旧 active 路径链接需要改写；历史文本仅提及当时出现的文件名，保留事实不改。

## 交接位置

- `src/hyperknow/model_output.py` 为无损 JSON 边界唯一实现，`generation.py` 与 `research.py` 接入。
- `research_domain.py` 输出全部当前轮缺失问题 ID，`prompts/research.py` 维护稳定 ID 指令。
- `tests/test_model_output.py` 及 `tests/test_research.py` 固化两个根因和严格拒绝边界。
- 实际服务需加载本次源码。旧失败任务保留原状，显式“继续生成剩余内容”才创建后继 run，不自动重新收费。
- 默认 5173 服务不可达，改为本次持有的隔离服务。
- 验证结果待补充，不将历史成功或模型配置存在视作本轮通过。
