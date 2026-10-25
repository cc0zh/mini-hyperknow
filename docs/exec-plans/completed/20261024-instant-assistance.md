# 即时协助、Skill 与四类教学产物

## 目标、范围与风险

- 用户于2026-10-24明确授权执行。新增独立教学会话，Skill驱动概念讲解／问题求解，并支持闪卡、聊天测验、独立文字白板和HTML动画。
- 不做资料整理、课程关联、上传、搜索／RAG、长期记忆、语音、外部集成、后端代码执行或发布部署。保留当前工作区已有课程删除与运行恢复改动，不清理用户数据。
- SQLite为唯一业务事实来源；共享串行模型worker，不宣称秒回或Token流。取消阻止后续调用及晚到提交，不承诺远端取消。
- 闪卡位置／翻面、测验作答和动画内部状态仅在浏览器内；生成内容持久化。白板位置须确认保存，恢复暂停。
- HTML使用无同源权限的sandbox iframe，CSP限制连接与第三方子资源；浏览器不保证阻止任意脚本导航iframe自身，也不是OS／CPU／内存沙箱。此发现已同步契约、SECURITY及UI，不能拿正则黑名单冒充严格出口隔离。生成内容、历史和技能均不能授予额外工具权限。
- 关联设计：[即时协助契约](../../design-docs/instant-assistance.md)。

## 进度与决定

- [x] 核对已有模块与未提交改动，确定范围和接口。
- [x] 会话／轮次、命令回执、取消重试、冷重启与事件通知。
- [x] Skill目录／按需加载／版本快照，真实工具循环及有界上下文。
- [x] 会话前端、闪卡／测验／白板／动画及交互校验。
- [x] 直接逻辑、临时SQLite、真实HTTP／WS、前端测试和构建。
- [x] 独立数据目录的真实模型与浏览器验收，包含一次真实在途取消晚到。
- [x] 同步长期设计、质量事实、history与必要learning后归档。

## 验收与交接

- 每个产物至少一次真实生成；核对Skill实际加载、内容针对性、显式继续及问答上下文隔离。
- 验证重复命令、版本冲突、在途取消与晚到拒绝、失败显式重试、刷新／冷重启不新增调用；持久化语义与临时交互状态分开报告。
- 动画以受控本地探针验证sandbox/CSP及展开／重置，不对外攻击，不以静态配置宣称完整沙箱。
- 费用授权仅限本次必要真实模型验收；不反复收费凑覆盖，不接入搜索供应商。
- 最终证据、命令、未覆盖项在本计划维护；全部原始证据只在忽略的数据目录保留，不提交密钥或原始模型会话。

## 实现与调用边界

- 新增`assistance_domain/storage/generation/api.py`、通用`agent_core/skills.py`及两个打包的`SKILL.md`；现有storage/runtime/main仅接入独立分支，课程和即时会话不相互冒充。SQLite通过幂等DDL新增两表，user_version保持3，原八表迁移／备份字节一致断言未削弱。
- Skill先公开目录元信息，模型调用get_skills后才获得正文；name/version/body/SHA-256固定在run输入，实际激活和每次模型上下文／usage可审计。工具仅get_skills和四种create，工具结果本轮暂存，最终回复和全部产物原子提交。
- 每轮最多8次Agent迭代、另允许1次有限格式修复，最多9次模型请求；执行准入时限360秒，同步请求仍受既有网络超时约束。上下文为64,000的保守UTF-8上界，预留8,192输出，非实际Token窗口；历史最近12个ready轮次、24,000字符，记录选择ID与截断标记，不裁当前问题。每个请求前／后、工具前、最终提交前检查任务存活。
- 前端拆为会话、产物、单白板播放器及命令／资源hook。命令完整method/path/body/ID按会话保存，不自动重发；白板保存确认后展示，提问先保存并冻结已确认前缀。产物位置独立按artifact.version合并，即使conversation.version未增长也不能丢事实。
- 路由`/assistance`、`/assistance/:conversationId`、`/assistance/boards/:artifactId`；首页和Shell增加入口。Vite支持HYPERKNOW_API_ORIGIN用于独立验收代理，默认仍为8000。

## 自动化与实际浏览器

2026-10-24 Windows／本地Edge，均未使用Mock、Fake、patch或HTTP拦截替身：

| 层级 | 命令或证据 | 结果与边界 |
| --- | --- | --- |
| 依赖 | `uv sync --frozen` | 成功；没有另建pip环境，没有新增依赖 |
| 仓库门禁 | `npm.cmd run ci` | 最终289项Python、21项仓库Node及文档／卫生／Action固定SHA通过；含真实临时SQLite、Uvicorn HTTP／WS和现有课程回归 |
| 前端规则 | `npm.cmd --prefix web test` | 最终90项通过，覆盖命令身份／作用域、独立产物版本、路由资源归属、选择题和白板规则 |
| 构建 | `npm.cmd --prefix web run build` | TypeScript与Vite成功；既有Mermaid／ELK大分包警告保留，不提高阈值掩盖 |
| 基础浏览器 | `web/e2e/assistance.spec.ts`，5188代理独立8037 | 6项通过：新入口、双击只创建一次、刷新只读、原回执显式重发、真实409保留输入与解锁、实际404与受控动画清理／opaque隔离探针；不调用模型 |
| 真实产物浏览器 | `HK_ASSISTANCE_EVIDENCE=<本次result.json>`，`HYPERKNOW_WEB_PORT=5187`执行`web/e2e/assistance-generation.spec.ts` | 1项贯通通过：真实闪卡翻面／切换、两题单多选正确判定／反馈、刷新清空本地作答、动画执行／展开／重置／宿主不可读、390px页面、白板保存／刷新恢复暂停；期间无新turn／retry命令 |
| 差异 | `git diff --check` | 通过；保留原dirty，未提交、未发布、不清空原数据库 |

最终两组浏览器合并运行7/7通过，证据位于`data/verification/instant-assistance/final-browser/`；最终CI、前端规则与构建输出分别保存在同目录`final-ci.log`、`final-web-tests.log`、`final-build.log`。没有在最终文档更新后重复收费生成。

最终只读审查找到并修复两个P2：同会话A白板的恢复命令不得替换B路由的资源；过大合法历史不得使待续讲状态失效。资源接收器现在按规范化查询路径核验身份；next-step状态从权威ready轮次独立冻结到run输入，不挤占可选历史。增加精确规则／真实SQLite回归，再通过上述最终门禁。未另为这两个确定性修复重复收费凑模型覆盖。

浏览器中途遇到的手机宽度断言是视口切换时壳层CSS过渡尚未完成，改用Playwright expect.poll等待布局稳定；没有用任意固定sleep或取消溢出断言掩盖问题。

## 真实模型、失败与恢复

独立数据目录：`data/verification/instant-assistance/`，后端8037／前端5187，模型为本地已配置的`deepseek-flash`，没有复制或修改用户课程。

- `scripts/verify_assistance.py --execute`，中断脚本后`--resume`重用已有run ID，不重复提交已知轮次；显式`--retry-failed`才创建失败轮次的后继。新增脚本不属于普通CI，也不自动批准课程或接入搜索。
- 共9个ready教学轮次：概念澄清→回答→继续、三张闪卡、两题含多选测验、三步独立白板、第一步白板追问、5,763字符自包含动画；另一个独立会话加载problem-solving，只给cos(3x)求导提示。新会话history为空，白板问题输入确为1个已确认步骤，不含未来步骤。
- 首次continue真实失败：模型输出自由文本，格式修复省略plan且等待不存在的下一步。没有保存伪完成；修复机制后显式重试。现给修复请求完整本轮上下文，要求六字段齐全，并强校验continue必须保留原plan、current_step严格+1；没有等待计划则命令事务拒绝。回归覆盖此失败。
- 独立一次真实取消：在get_skills成功后、第二请求在途时取消；模型调用数由1增至2，第二响应真实晚到，run仍cancelled、response为空、产物为空且无后续调用。证据`cancellation.json`。
- 完成态和取消态冷重启：13张表逐行SHA-256均一致，模型调用保持28，不自动收费续跑；四类产物内容、白板确认位置及会话保持。证据`before-restart.json`与`after-restart.json`。
- 本次总计28次实际模型调用，包含1个失败run及1个取消run；provider usage合计prompt_tokens=160,154、completion_tokens=27,853、total_tokens=188,007，未配置价格，不推算金额。证据`model-summary.json`；`result.json`记录真实轮次／产物，截图保存在其`browser/`子目录；基础截图在`web/.verification/assistance-basic/`。

## 内容与未覆盖边界

- 人工抽核链式法则公式、sin(x²)三步白板、单选题答案6x·cos(3x²+1)、多选a/b/e及cos(3x)提示，未泄露后一题的最终答案。**不代表全部教学正确**：真实闪卡“平均变化率之间不能这样相乘”表述过强；当中间差值非零时，有限差商可按相应区间相乘。该样本原样保留，不手改产物伪造模型质量，列入内容债务。
- 模型在回答澄清后将用户原先两步意图扩成六步；后继continue已强制沿保存计划前进，但普通message重新规划仍由模型决定，尚未引入独立的用户确认／锁计划协议。此语义质量限制不写成“完全遵循计划”验收。
- 暂无任意恶意JavaScript强出口／资源沙箱；不承诺iframe自身导航绝对封锁、CPU或内存配额。服务仍本地单用户，无公网部署、语音、RAG、上传、长期记忆或代码执行。
- 没有额外付费覆盖生成中硬重启、供应商传输失败、跨标签每种迟到时序；这些不能由完成态重启和直接事务测试替代。其他旧课程内容债与未完成项目活动不由此任务解决。
