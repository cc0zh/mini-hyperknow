# 即时协助：产物选择交给模型与感知层补强

## 目标、范围与风险

- 目标与验收标准：把「产物种类」从学习者可选的操作枚举变回模型按内容决定的实现细节；补上持久步骤日志、富文本块与产物反馈；新增结构图产物。验收为：显式文案仍保真（说了要闪卡就必须有闪卡）、明确拒绝必须被尊重、一轮只存一个产物、真实模型与真实浏览器各跑通一次。
- 包含与不包含：包含 `action` 枚举收缩、`TeachingSuggestion` 去掉 `action`、文本意图派生（请求与拒绝两个方向）、单产物上限、`create_diagram`、callout 块、持久步骤、产物反馈、闪卡与 quiz 题面富文本。不包含白板形态重构（原站 `whiteboardSession` 独立会话与计价不做）、长期记忆、分享链接、网页搜索、语音、上传、日历。
- 风险及缓解：文本意图判定是启发式，可能把「引用已有产物」误读为新建请求 —— 真实模型的第一轮就撞上了这个错误，已用 `REFERENCES` 抑制并补直接回归；模型自由选择产物可能让每轮都附赠产物 —— 用「一次技能调用一个产物」的硬上限和 SKILL 里的判据约束；`create_diagram` 的 Mermaid 源码可能含配置指令 —— 复用既有 `%%{` 与 `---` 拒绝逻辑，不新增正则黑名单冒充沙箱。
- 已有授权与需要确认的边界：契约变更与一次真实模型复验已获批准（方案 A：服务端从文本派生意图以保住「点名的产物必须存在」）。费用授权仅限本次复验。
- 关联设计文档：[即时协助契约](../../design-docs/instant-assistance.md)。

## 进度与决定

- [x] 核对受影响模块：`assistance_domain`、`assistance_storage`、`assistance_api`、`assistance_generation`、两个 SKILL、前端会话/产物/白板页与样式、三份测试与验收脚本。
- [x] `action` 收缩为 `message | continue`；`TeachingSuggestion` 只留 `{label, text}`；前端删除「教学方式」「本轮操作」两个下拉。
- [x] 文本意图派生：`requested_artifacts`（点名）与 `forbidden_artifacts`（明确拒绝）各自落 run 输入，工具层与提交层双重强制。
- [x] 产物上限从「一轮最多两个」收紧为「一次技能调用一个」；闪卡 20→6 张、测验 8→6 题。
- [x] 新增 `create_diagram`（Mermaid 源码 + 图注），复用 `Board.tsx` 的 `Mermaid` 渲染器，不引入服务端渲染。
- [x] 正文 callout：`:::definition / :::example / :::warning / :::note` 四种封闭类型。
- [x] 步骤日志持久化：`run.steps` 在 ready 与失败/取消/中断三种终态都写入 turn，前端 `<details>` 折叠展示。
- [x] 产物反馈：`PUT /api/assistance/artifacts/{id}/feedback` 记录在产物上而非消息上。
- [x] 闪卡答案、测验题面与选项、澄清问题都走富文本；行内 `$…$` 与 `**加粗**` 生效。
- [x] 测试与验收脚本改为自然语言驱动，删除按 action 断言产物的写法。

2026-10-24：关键决定与依据。

- **分类法不暴露给用户**：原站把 `conceptExplanation`、`whiteboardSession` 这类内部标识符直接画在界面上，比下拉框更糟。学习者想的是「这段没懂」「帮我记一下」，不是「本轮 action=flashcards」。
- **一次技能调用一个产物，不是一轮一个**：分享页证据显示一轮里可以「讲 + 一块白板」，而「闪卡」是新的用户轮次。限制加在工具调用上比加在轮次上更贴合真实形态，也不额外收紧预算。
- **不抄 `1 / 1` 单卡**：想要 5 张卡要发 5 轮、5 次模型调用，比一次生成 5 张贵得多。真正该收的是「单个体积有界」而不是「只装一条内容」。
- **拒绝也是意图**：`requested_artifacts` 为空只表示「不强制」，无法表达「禁止」。真实模型在「不生成新白板」之后仍创建了白板，因此把拒绝单独建模，而不是靠空列表隐含。
- **反馈挂在产物上**：用户不满的通常是这张卡或这组题，不是那段对话。这是本项目目前唯一的内容质量用户侧信号。

## 验收与交接

已执行的命令及结果：

| 层级 | 命令 | 结果 |
| --- | --- | --- |
| Python | `uv run --frozen python -m unittest discover -s tests -p "test_*.py"` | 294 项通过 |
| 前端规则 | `npm.cmd --prefix web test` | 90 项通过 |
| 构建 | `npm.cmd --prefix web run build` | TypeScript 与 Vite 通过；既有 Mermaid／ELK 分包警告保留 |
| 文档与卫生 | `npm.cmd run check:docs`、`check:repo` | 通过 |

真实模型（`deepseek-flash`，独立数据目录 `data/verification/instant-assistance-v2/`，端口 8037）：

- `scripts/verify_assistance.py --execute` 十个轮次全部 ready：两轮澄清→回答→`continue`、闪卡、测验、结构图、三步独立白板、白板追问、动画，以及另一个会话的 problem-solving 提示。产物分布为 quiz×2、flashcards、diagram、whiteboard、animation。
- 普通教学轮次 `artifacts == []` 断言通过：没有在讲课时强行附赠产物。
- 白板追问那一轮 `requested_artifacts == []` 且 `forbidden_artifacts == ["whiteboard"]`，未再生成白板，`whiteboard.steps` 只有 1 个已确认步骤。
- 结构图由真实模型产出的 Mermaid 源码渲染成 SVG（见 `screenshots/artifact-diagram.png`）。
- 过程中记录了一次真实失败与修复：文本意图规则把「解释当前白板第一步」读成新建白板请求，run 以 `artifact_not_created` 显式失败、未保存伪完成；随后用 `REFERENCES` 抑制引用性措辞并补直接回归，另建一轮验证。该失败保留在观察记录里，没有删除伪造。

真实浏览器（Edge，`HYPERKNOW_WEB_PORT=5187`）：

- `web/e2e/assistance-generation.spec.ts` 通过：闪卡翻面与切换、测验按选项 id 作答并判定、刷新清空本地作答、动画 sandbox 与重置、白板保存与刷新恢复暂停。
- `web/e2e/assistance-screenshots.spec.ts` 产出留存截图，位于 `data/verification/instant-assistance-v2/screenshots/`：`step-trace.png`（持久步骤）、`teaching-turn.png`（callout 与富文本）、`artifact-identity.png`（产物头与反馈）、`artifact-*.png`（五类产物）、`conversation-full.png`、`conversation-mobile.png`、`entry.png`。

未执行的检查、阻塞和遗留事项：

- 未做白板形态重构（原站独立会话 + 计价），按本轮决定暂缓。
- `requested_artifacts`／`forbidden_artifacts` 仍是关键词启发式：中英混写、复杂否定（「不是要闪卡而是……」）与多类并列都只取其一，属于已知近似，未用分类器替代。
- 未覆盖生成中硬重启、供应商传输失败、跨标签迟到时序。
- 产物反馈只有写入路径，尚无汇总视图；读侧目前靠快照里的 `feedback` 字段，没有统计端点。

必要的复验方式：`HK_ASSISTANCE_EVIDENCE=<result.json>` 加 `HYPERKNOW_WEB_PORT=5187` 运行 `npx playwright test assistance-generation assistance-screenshots`；真实模型需重新授权。

归档前检查：已更新所有入链；长期决定已回写[即时协助契约](../../design-docs/instant-assistance.md)与[参考差异](../../design-docs/reference-and-gaps.md)；质量状态变化已更新。
