## [2026-10-27 11:24] | Task: 编写通用教学评测重构设计

### Execution Context

- **Agent ID**: 当前会话主助手。
- **Base Model**: 会话未提供可核实的具体版本，不推测。
- **Runtime**: Enso／pi，Windows PowerShell。

### User Query

> 为eval架构重构编写design-doc，保留Case Pipeline与评测Pipeline，参考阿里云手册、美团文章及Penguin的通用评测机制；先不写代码。

### Changes Overview

- 更新既有评测专题为待评审的通用设计，明确首切片实现事实与未完成项；保留原路径作为统一入口。
- 定义两条Pipeline、通用内核与业务接入边界，覆盖任务、实验／Trial、动作、检查点证据、评分与版本比较。
- 明确全业务覆盖、真实前置资料、有限交互、恢复／费用和历史结果边界，写出目标验收要求。
- 补充阶段评分与业务执行收尾的区别：零澄清自动进入调研时须披露后续调用预算并跟踪收尾，不能用轮询取消伪装严格阶段隔离。
- 将执行侧采证计划与私有评分标准分区，明确检查点如何在运行期收集，同时避免整份Rubric进入执行／被测上下文。
- 同步设计索引、评测README导航及参考资料，区分外部片段阅读与本项目决定；纠正README将8192上下文预留写作即时协助输出上限的旧说明。
- 根据后续核对意见补齐observe的统一观察契约：状态、可执行动作、资源版本与采证事实由接入层提供，动作提交仍由真实业务服务端校验。
- 统一规则／LLM的check_id结果身份，区分Rubric判据与checkpoint_id采证时点；旧规则id及rubric_id通过显式映射导入，不改写历史。
- 明确澄清的固定资料回答与可选有界回答器、真实问题／选项绑定、失败归因及答案恢复；回答器请求在调用前保存并绑定Trial及步骤，预算独立，未知响应不自动重发，旧问答不冒充本次执行。
- 修正旧计划的非原文引号转述，补齐Benchmark版本／哈希、安全入口和当前路径／命令映射；保留已有阶段收尾与Pipeline别名约定。

### Design Intent

沿用“先单次跑通，再扩展全部业务”的路线，在已知业务需求上集中设计统一契约。Case Pipeline形成可信且可版本化的任务，评测Pipeline检验指定版本的真实表现；新增业务主要扩展接入、Case和检查，不复制或反复改动公共恢复与证据机制。

### Files Modified

- [通用教学评测设计](../../design-docs/backend-evaluation-pipeline.md)
- [设计索引](../../design-docs/index.md)
- [评测入口说明](../../../evals/README.md)
- [外部参考笔记](../../references/evaluation-refactor-sources.md)
- [参考资料索引](../../references/README.md)
- 本history。

### Verification

- `npm.cmd run check:docs`通过：文档骨架及本地链接有效。
- 初稿以`npx.cmd --loglevel=error --yes markdownlint-cli2@0.24.0`检查六份文档通过，0问题；`git diff --check`通过。
- 复核修订后再次运行文档骨架检查、两份修改文档的Markdown检查及`git diff --check`，均通过；本次仅修改主设计和本history。
- 仅编写文档，未修改业务／评测代码、配置、依赖或质量状态；未调用业务、回答器或Grader模型，未启动服务或浏览器验收，不宣称通用框架已实现。
- 独立只读复核因上游API错误中断，不作为评审通过证据；主助手另行核对交互恢复、业务收尾及新旧结果隔离。
- 外部来源本轮仅取得可检索正文片段，直连受限；未宣称全文或上游源码已完整核验。
