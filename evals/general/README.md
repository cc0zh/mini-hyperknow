# 通用评测：schema v2

这里保存人工编写的开发Case，不保存模型输出。它们覆盖B01–B08和五类产物，结构校验不等于业务执行、评分校准或内容验收；所有Case均标记development／uncalibrated。实际交付与检查见[实施计划](../../docs/exec-plans/active/20261027-general-evaluation-framework.md)。统一入口与历史只读方式见[评测入口](../README.md)；旧执行命令已移除，原始事实保留。

## 日常只看一个文件

每次测评选一个输出目录，例如 `--output data/evals/runs/trial-001`。新目录自动生成：

总入口固定为 `data/evals/index.html`；只看某次结果时打开该次的 `report.html`。本地历史整理清单位于 `data/evals/details/organization.json`，记录旧路径到新路径及哈希核查；绑定身份的历史数据库仍原位保留，旧脚本只作证据归档，不再作为执行入口。

```text
trial-001/
  report.html          # 打开这个：题目、回答、结论和评分理由
  details/             # 排障或复查时才需要
    result.json        # 原始 Trial、冻结证据和全部评分记录
    trajectories/      # 教学调用轨迹
    backend/           # 建议放置本次隔离后端；启动服务时指定
```

`execute`／`resume`／`regrade`取得汇总后自动更新本次 `report.html`，`report --result` 和 `review --result` 也可离线重建。固定报告只是带管理标记的派生展示，不改原始证据；不同内容的历史 HTML 快照仍保留在统一 review 目录，同一内容重复导出不再新增同义快照。不要再手工为每次运行追加多份 report、summary 或 HTML 副本。stdout 已含汇总，确需保存 CLI／服务日志时统一放 `details/`。

旧 `result.json` 目录与显式 JSON 文件参数继续沿用原位置，不自动搬迁；若同一目录同时存在根目录与 details 下的 result.json，命令拒绝猜测。已有后端绝对路径参与身份核对，不能为了美观直接移动数据库。

## Case Pipeline

```powershell
uv run --frozen python scripts/run_eval.py validate --case evals/general/assistance-two-turns/case.json
uv run --frozen python scripts/run_eval.py migrate --case evals/concept-explanation/case.json --output data/evals/migrated-concept.json
uv run --frozen python scripts/run_eval.py publish --case data/evals/migrated-concept.json --reviewed-by "assistant:local-review" --library data/evals/v2
```

这些命令不调用模型。migrate产生新schema文件，不覆盖旧Case；publish记录调用方明确声明的复核身份，不把字符串冒充独立真人校准。Case以规范内容哈希存放在library/cases，已发布同一ID／版本不得换内容。运行及重评只追加unreviewed样本，不自动改题、标准或留出集。

2026-10-27启动修复将13个人工Case升级到内容版本2，迁移Case升级到1.general-2，Benchmark升级到版本2；schema_version仍为2。首步显式支持Adapter的preparing状态，并直接用正式资产验证真实本地HTTP首步及收据。请发布新版本并新建实验，不修改旧内容寻址资产或原实验内嵌Case；旧单轮Case与历史结果不改写；旧执行器已移除，历史结果仅支持report只读JSON。

这里的[benchmark.json](benchmark.json)固定14个开发Case，包含旧单轮显式迁移及13个人工任务；不是已校准黄金集。Benchmark manifest包含schema_version=2、id、字符串version、title、usage及members数组；每个成员固定id、version和validate返回的case_hash。先逐个publish全部成员，再执行：

```powershell
uv run --frozen python scripts/run_eval.py benchmark --manifest evals/general/benchmark.json --library data/evals/v2
uv run --frozen python scripts/run_eval.py experiment --benchmark data/evals/v2/benchmarks/BENCHMARK_HASH.json --subjects data/evals/subjects.json --library data/evals/v2 --grading-config data/evals/grading-config.json --repetitions 2 --output data/evals/experiment.json
uv run --frozen python scripts/run_eval.py report --experiment data/evals/experiment.json
```

BENCHMARK_HASH须替换为benchmark命令实际返回的文件名。subjects.json是被测版本快照数组；只有真实服务构建或可信装配记录才能声称代码版本，不采用CLI目录Git HEAD。尚无可信身份时明确写unknown，不能据此声称某次提交带来改善。experiment只生成固定矩阵，不启动业务；report包含全部计划任务，尚无结果的任务保留pending。

含LLM检查的实验必须通过grading-config固定model、base_url、timeout、max_output_tokens、context_budget五个公开字段，不能含api_key。该配置不验证真实连通；execute所用评分配置必须与固定定义一致，不一致在业务写入前blocked。超时90和90.0数值相同时保留固定计划的数字表示，以核对原定义哈希，不重写历史实验。默认评分上下文预算16384、请求输出2048；可用--grader-context-budget显式指定上下文估算与输出预留的总预算。它属于评分身份，调整后须新建计划或显式重评，不能冒充原固定配置通过；旧预算异常仍保留。它们不是实际费用保证。

## 评测 Pipeline

每次Trial使用独立后端及数据目录。模型密钥仅从既有环境／本地配置注入；Grader模型须显式配置，执行前先验证规则注册、评分配置、服务及资源身份。以下命令会产生真实费用，须获得明确执行授权；工程实现不等于真实内容验收：

```powershell
uv run --frozen python scripts/run_eval.py execute --case evals/general/assistance-two-turns/case.json --data-dir data/evals/runs/trial-001/details/backend --output data/evals/runs/trial-001 --grader-model YOUR_AUTHORIZED_MODEL --execute
uv run --frozen python scripts/run_eval.py resume --data-dir data/evals/runs/trial-001/details/backend --output data/evals/runs/trial-001 --grader-model YOUR_AUTHORIZED_MODEL --execute
uv run --frozen python scripts/run_eval.py regrade --output data/evals/runs/trial-001 --grader-model YOUR_AUTHORIZED_MODEL --execute
```

先按[隔离后端启动方式](../README.md#隔离后端)启动专用服务。execute不是后台服务启动器；缺配置或前置材料时blocked，不替用户建课、换题或自动补救。也可通过execute的--experiment及--trial-id使用既定矩阵成员；每个成员仍须提供自己的独立后端，矩阵不隐式共享业务数据或并行运行。--subject可传可信装配记录；不传则版本unknown。

- 新目录的details/result.json保存固定Case、被测／环境身份、有限步骤、精确动作请求、资源绑定、检查点证据、用量及独立评分attempt。
- details/trajectories/按业务run导出ATIF-v1.7文字子集，不把历史回答记作当前调用，不把Grader混入教学轨迹。无法导出时记录缺口，不生成伪轨迹。
- 统一观察由接入层解释业务状态；公共Runner只匹配state、合法动作及检查点。可用动作是观察时事实，提交仍由服务端校验expected_version。
- 每项check_id明确规则或模型评分器、判据、证据checkpoint_id及可选evidence_fields顶层字段投影。完整原始证据保留，模型只读声明的字段，不静默截断后声称完整评分。
- 已发送但回执／响应未知时保守阻塞，不自动重POST、不生成替代run、不重新选择分支或答案。恢复使用原绑定；重评只读冻结证据，新建attempt。
- 恢复、评分、报告和轨迹导出共用证据完整性校验，核对data及checkpoint_id／observation身份。评分attempt以evidence_set_hash绑定Trial、Case和完整冻结证据集合；新增证据或旧v2评分缺少绑定时，报告标记stale_grading／待判，不再沿用旧通过。resume不自动追加评分费用，须明确regrade；原评分记录保留。
- 规则检查与内容结论、业务失败与测量错误、用量未知与实际零分别记录；未收尾、缺证据、评分错误或已知超预算均不整体通过。报告退出码不能代替真人校准。

预算按本Trial已持久化的调用计数，model_calls_coverage=saved_calls_only不表示全部供应商调用已记录，也不把未知token用量补零。调用预算为零或已用尽时不再发送新动作；执行观察／结束和离线报告都核对已知调用数、动作数及时长的超限，刚好达到调用上限的已完成任务允许收尾。在途业务可能继续消耗，评测不保证远端取消或硬费用封顶。

## 真实前置材料

lesson-generation要求已有真实课程但没有目标准备记录；classroom-question及quiz-practice要求已有真实讲义；quiz-exam要求真实单元大纲。prerequisites.resources只声明session／exam等别名与kind，实际ID必须从私有fixture manifest绑定，不在Case中编造。

先由SQLite备份API建立一致性真实副本；不能直接复制活跃主文件或修改作者默认库。fixture命令只读取已隔离的副本，不执行备份、不生成课程：

```powershell
uv run --frozen python scripts/run_eval.py fixture --data-dir data/evals/backend-fixture --origin real-backup-001 --bindings data/evals/fixture-bindings.json --resource-sources data/evals/fixture-producers.json --output data/evals/fixture.json
```

bindings为别名到{kind,id}的映射；resource-sources为每个物理表／行ID到真实生产run_id的显式映射。导出器要求完整资源清单与来源，记录一致性逻辑快照摘要，不将调用方声明当作模型质量证明。执行时提供--fixture-manifest，并检查目标尚无旧讲义／题组／生成记录；prepare复用旧输出不能算新版本生成。

## 覆盖与限制

| Case | 能力与前置条件 |
| --- | --- |
| concept-chain-rule | 旧B07单轮Case的显式schema迁移，原题及判据保留来源 |
| assistance-two-turns | B07两轮计划及合法continue；新会话 |
| course-clarification | B01零问题／真实资料回答；自动后续research须跟踪收尾与费用 |
| web-research | B02真实搜索及已读来源支持；模型与搜索配置 |
| course-blueprint | B01–B03创建、澄清、批准与单元展开；模型与搜索配置 |
| lesson-generation | B04固定真实课时大纲；fresh session fixture |
| classroom-question | B05合法cursor推进后提问；已保存讲义fixture |
| quiz-practice／quiz-exam | B06讲义／单元来源出题；真实前置fixture |
| artifact-flashcards／quiz／whiteboard／animation／diagram | B07–B08五类真实提交产物；新会话 |

澄清当前只实现固定公开资料／明确选项映射及显式skip；需语义判断的有界模型回答器尚未实现，显式blocked，不偷偷启用用户Agent。不能只凭零问题或skip宣称真实回答分支已验证。

源端没有持久历史检查点日志，轮询错过的蓝图／单元版本不能从最终Course补造；证据gaps保留。源端不保证异常调用全部落盘，max_model_calls仅为已报告观测的本地门禁，不是供应商硬费用封顶。health只暴露路径指纹与模型／搜索配置状态，不证明供应商连通、代码版本或认证。浏览器显示、动画交互和真人学习效果仍须另行验证。

## 离线报告与比较

```powershell
uv run --frozen python scripts/run_eval.py report --result data/evals/experiments/dev/trials/trial-001
uv run --frozen python scripts/run_eval.py compare --baseline data/evals/baseline/trial-001 --candidate data/evals/candidate/trial-001
```

report／compare不读取业务数据库、不请求模型。比较固定Case、真实前置摘要、评分定义与配置、环境策略和重复编号，不能只比较双方成功子集；不可配对及缺失任务单列，不默认总分或自动接受候选版。execute／resume／regrade退出码0为完整自动检查通过、1为明确不合格、2为阻塞／待判／错误；离线命令0只表示操作成功，不代表内容已通过。

## 离线 HTML 查看

日常总入口为 `data/evals/index.html`，报告目录仍位于 `data/evals/review/index.html`。目录默认只突出最近导出的一份，其他来源及历史快照折叠；“最近导出”不是按所有私有文件的修改时间推断最新实验。schema-v2 的 execute／resume／regrade 在取得汇总后，以及 report／compare 在成功读取结果后，都会自动收录；stdout JSON 和退出码口径不变。仅导出报告不启动后端、不调用模型，页面也没有执行／重评按钮；schema-v1历史结果仅支持report只读JSON，不收录此v2目录。

已有结果可显式导入；不扫描整个 data 目录，也不会把工程预览自动当作真实验收。无参数的 review 只根据目录清单重建入口，不重新读取来源或评分：

```powershell
uv run --frozen python scripts/run_eval.py review --result data/evals/experiments/dev/trials/trial-001
uv run --frozen python scripts/run_eval.py review
```

同一来源内容变化后再次导出会更新最新链接，旧快照保留在 `data/evals/review/snapshots/`；内容相同则复用快照。入口只是可重建目录，不汇总成跨实验通过率，也不代表全部计划任务已完成。上述命令均可用 `--review-dir` 指定其他私有目录；自动导出失败只在 stderr 告警，不改写已有评测结果或退出码，可用 review 显式补导。

在 report／compare 后添加 `--html` 还可另存一份指定路径的自包含报告；同样会收录统一入口：

默认按普通读者的顺序展示：结论解释 → 用户题目 → 已保存回答 → 分项评分理由。题目与回答不再要求先展开证据JSON；长ID、完整身份、动作及评分记录放在默认折叠的“技术详情”里，仍可从回答或检查项跳转到对应原始来源。重复快照里完全相同的对话仅合并展示，保留所有来源；不同内容分别展示。

“还不能下结论”不等于回答未达标。例如自动评分器报错时，页面会直接说明评分未完成，实际保存的AI回答仍可阅读；所有解释依赖现有状态，既不补造答案，也不重新判分。

```powershell
uv run --frozen python scripts/run_eval.py report --result data/evals/experiments/dev/trials/trial-001 --html data/evals/review/trial-001.html
uv run --frozen python scripts/run_eval.py report --experiment data/evals/experiment.json --result data/evals/experiments/dev/trials/trial-001 --html data/evals/review/experiment.html
uv run --frozen python scripts/run_eval.py compare --baseline data/evals/baseline/trial-001 --candidate data/evals/candidate/trial-001 --html data/evals/review/compare.html
```

路径按实际保存位置替换。可重复提供 `--result`／`--baseline`／`--candidate`；实验报告须显式传入已有结果，未提供或身份不匹配的计划任务仍为 pending，不自动扫描目录或执行任务。只有 `--experiment`、没有任何结果时也能生成完整待执行清单。

双击生成的 HTML 即可离线查看：支持任务／状态／被测版本筛选、私有判据与评分理由、证据定位、检查点原文、动作过程、用量及评分记录；比较报告保留配对结论和不可配对原因。所有结论复用 Python 汇总，页面不重新判分，不将 unknown、未校准、缺证据或未知用量解释为通过或零成本。

报告内容只在命令导出时更新；来源改变后须再次导出，已打开的入口须刷新页面。报告快照与 `--html` 输出必须是新 `.html` 文件，放在忽略的 `data/` 内或仓库外，不覆盖源文件或已有报告。只有带管理标记的统一 `index.html` 和单次 `report.html` 可由写锁保护并原子更新；catalog.json 保留目录记录，删除索引后可用 review 重建，不要手工修改清单。包内模板无需网络依赖，模型 HTML／Markdown 仅按文本展示，不运行教学动画。

报告包含原始用户内容、私有评分标准及冻结证据，不是脱敏分享件，请勿提交 Git 或直接外发。CSP 禁止联网、框架及对象嵌入，只允许固定查看器脚本；安全转义不等于自动识别所有个人信息或秘密。实现与验证见[HTML 报告计划](../../docs/exec-plans/completed/20261027-evaluation-html-report.md)。
