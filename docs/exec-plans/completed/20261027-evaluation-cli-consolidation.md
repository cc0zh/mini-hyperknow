# 评测命令与旧执行路径收敛

## 目标与授权

用户确认清理旧评测命令与重复执行实现，统一日常入口；历史Case来源、回答、评分、轨迹、费用与验收记录原样保留。只做本地代码、测试和文档修改，不启动收费评测，不修改data中的历史实验或作者业务数据。

## 范围与步骤

- [x] 核对旧模块对新版的共享依赖、回归测试及文档引用；共享的隔离目录、回环URL、只读SQLite与Skill轨迹检查迁入eval_support，历史Case和结果读取迁入eval_legacy。
- [x] 统一scripts/run_eval.py至通用CLI，删除旧evaluation／eval_grading／eval_cases执行实现及专用测试；历史结果使用report只读JSON，拒绝旧结果恢复、重评、比较和伪装v2导出。新增入口与历史回归先失败后通过，迁移共享安全与Skill检查。
- [x] 更新根README、评测入口、通用说明、架构、安全与设计；历史审计保留当时事实，删除失效源码链接。完成最终CI、真实历史文件只读验证、history和学习记录，更新链接后归档。

## 决定与限制

- 工作区已有产品与通用评测的大量未提交修改；以当前文件为基础局部编辑，不回滚或覆盖其他任务。
- 历史结果保留不意味着保留可新增费用的旧执行器；必要读取与格式校验单独保留。
- 旧Case通过显式migrate转换，不静默改写资产、历史结果或评分含义。

## 实现边界

- scripts/run_eval.py仅转入hyperknow.eval_cli；prepare／run／grade／show明确报removed并提示替代用法，不做可能收费的隐式转发。
- 删除原evaluation.py、eval_grading.py、eval_cases.py以及旧专用测试；必要的文件原子性、样本关联、严格评分、失败恢复与身份保护由通用测试覆盖。共享安全与Skill轨迹测试迁入test_eval_support。
- eval_legacy只保留旧Case校验、原口径分类／预算披露和只读结果摘要，没有业务提交、模型调用或样本写入。旧Case来源与已迁移新版Case均不改写。
- 真实历史文件额外发现最早v1含固定skill_hint字段。增加仅限历史读取的显式兼容，保留该字段参与原始哈希；不能删除字段后冒充新版身份，也不扩大现行Case校验或恢复旧Skill依赖。
- report读取v1输出带legacy_read_only的JSON，保持原分项评分及在途状态；不重解析、不重发、不自动写入v2目录。v1不支持resume、regrade、compare、v2实验绑定或新版HTML导出；已有HTML文件保持可读。

## 验收

- 新增旧命令拒绝、统一帮助、旧模块不再导入、历史JSON只读和禁止旧结果执行类操作的回归，先观察旧行为失败再修复。最早skill_hint历史格式同样先有失败回归再修复。
- 最终npm.cmd run ci退出0：21项Node测试通过；Python执行500项，499项通过、1项因Windows符号链接权限不可用跳过。包含通用Runner／Adapter、SQLite／真实本地HTTP、评分、报告、旧格式兼容和现有业务测试；未将工程通过作为模型质量通过。
- 最终日志：data/evals/cli-consolidation-validation-20261027/final-ci.log。早期CI日志另保留ci.log及UTF8副本，不以其早于兼容补丁的499项数量作为最终结果。
- 实际读取data/evals/acceptance-20261026-1203/run/result.json：命令退出0、calls=0、legacy_read_only=true，读取前后SHA-256一致，仍披露原报告用量超过请求上限；未修改原分项、未知状态或历史证据。脱敏验证摘要位于同验证目录的legacy-readonly.json。
- 手工检查--help只有通用命令；validate读取正式新版概念解释Case成功，不调用模型。git diff --check与文档门禁通过。
- 本次不启动收费模型、不部署、不迁移或清理作者业务数据；初始工作区中其他产品及评测改动未回滚。模型质量、预算远端复验与独立真人校准状态均不因此改变，故不新增QUALITY_SCORE结论。

## 后续事项

无本次范围内的阻塞项。历史v1继续只读，不承诺将其转换为满足新版证据要求的Trial；如需新版本对比，使用固定新版Case另行授权真实执行。
