## [2026-11-09 23:00] | Task: 实施证据驱动课程调研

### 索引分支（已有完整 execution plan）

- **User Query:** 按Architect已选方案推进下一阶段，实现单一本地调研Agent、多搜索源及贯通课程生成的证据契约。
- **Result:** 完成Tavily/Exa适配、问题—主张—原文证据关系、蓝图/课时/题目claim范围校验，以及蓝图反馈后的同Agent补充调研。原实现的后端441项测试、前端113项测试、类型检查、构建、文档检查和评测配置验证通过；未发起付费搜索或模型课程实验，未声称Exa优于Tavily或已改善课程效果。
- **Follow-up:** 对抗审查发现单元生成会收到未分配的全局research报告。现已限制`planning_context()`只在蓝图阶段投影完整报告，单元阶段仍保留已分配主张及逐字证据，并在预算检查前省略全局报告。蓝图专项16项测试和预算专项12项测试通过；同一复现输出`unselected_quote_in_unit_input False`。文档、仓库卫生和diff检查通过。后续全套测试运行在`ResearchReportTests.test_questions_and_claims_have_a_bidirectional_typed_relation`失败，但`test_research.py`单独运行的25项测试通过；全套测试中的失败原因尚未查明。
- **Execution Plan path:** `docs/exec-plans/completed/20261109-evidence-driven-research.md`
