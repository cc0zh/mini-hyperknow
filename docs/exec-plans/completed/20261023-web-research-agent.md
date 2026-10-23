# 网页调研 Agent 切片

## 目标、范围与风险

- 目标：实现真实 Tavily 搜索、公开网页阅读、有限工具循环、带引用的结构化调研报告及 SQLite 运行恢复，供后续全局课程蓝图消费。
- 包含：独立 research run、REST 创建与现有查询／通知／取消／重试、工具及模型调用事实、来源校验、显式真实验收脚本。
- 不包含：自动接入造课、全局蓝图确认及逐单元展开、前端调研视图、上传／知识库、浏览器自动化、JavaScript／PDF 解析、多 Agent。
- 用户已选择 Tavily；凭据只在本地配置，不写入运行输入、工具结果或日志。初次验收因缺key阻塞；用户补齐后真实链路通过，见下方验收记录，不用替身代验。
- 风险：不可信网页指令、SSRF／DNS rebinding、超大正文、来源幻觉和重复费用。用只读工具集、固定公网连接与重定向校验、字节／字符／轮次／工具次数预算、实际已读来源引用校验及事务取消门禁约束。
- 相关：[模型工作流](../../design-docs/agent-workflows.md)、[V1 内核](../../design-docs/agent-core-v1.md)、[API](../../design-docs/api-and-events.md)、[安全](../../SECURITY.md)。

## 进度与决定

- [x] 核对现有 V1 Agent、同步 provider、单 worker、SQLite JSON 记录和无 Mock 测试约束。
- [x] 实现真实搜索／安全网页读取并直接检查解析及网络边界。
- [x] research run 接入同一个 worker；保存过程、来源、报告及取消／恢复／重试语义。
- [x] 编写直接逻辑、实际磁盘 SQLite 与真实 HTTP 检查；运行相关回归及文档门禁。
- [x] 显式运行真实验收入口，缺配置返回 blocked（退出2），没有发起收费请求。
- [x] 用户配置后真实Tavily搜索／网页读取／模型报告通过，复核已保存证据及引用与摘录哈希一致；不等于全部外网故障时序或内容准确性全覆盖。
- 2026-10-23：本轮仅先做网页调研 Agent，不提前实现用户已明确的“全局蓝图确认一次后逐单元展开”。已有完整目录生成不改变。
- 2026-10-23：研究报告及来源存到 research run 的 JSON；沿用 SQLite v3，不新增可独立修改的课程目录或通用 JSONL 业务事实。内部工具循环只注册 web_search／read_webpage，无文件或命令执行工具。
- 2026-10-23：只读审查发现并修复三项边界问题：TCP／TLS交接前触发的watchdog信号不能丢失；提前EOF或超时的正文不能被当成完整响应；上下文应按实际UTF-8／JSON负载裁剪并预留收尾空间。最终采用64,000保守估算窗口、100%阈值、创建前预算检查、工具动态摘录及无工具的有限修复；不新增摘要模型费用。

## 验收与交接

- 新增文件：`src/hyperknow/research.py`、`research_web.py`、`research_domain.py`、`research_storage.py`；接入既有配置／API／worker／存储及前端run类型。新增四个research测试文件及 `scripts/verify_research.py`；无新依赖或数据库迁移。
- `uv sync --frozen`：通过，29 packages；没有改锁文件。
- `uv run --frozen python -m unittest discover -s tests -p 'test_research*.py' -v`：51项通过，含真实Uvicorn、临时SQLite、并发、重试／取消／重启门禁、实际工具的无网络拒绝路径、URL／正文解析，以及审查问题的预算／超时状态／正文长度规则回归。测试数据仅是规则输入，不是伪造服务响应或成功研究证据。
- 最终 `npm.cmd run ci`：全仓213项Python、21项Node通过，包含上述51项调研检查及文档／仓库门禁。
- `npm.cmd --prefix web test`：49项通过；`npm.cmd run build`：TypeScript／Vite通过，保留既有大分包警告。
- `npm.cmd run check:docs`、`git diff --check`、Python编译检查：通过。
- `uv run --frozen python scripts/verify_research.py`：实际输出 `BLOCKED: configure TAVILY_API_KEY locally; no paid requests were made.`，捕获进程退出2。无模型或搜索费用，不新增演示课程。
- 独立真实网页读取尝试：`fetch_page('https://docs.python.org/3/library/asyncio-task.html', timeout=20, max_chars=1500)` 返回 `web_timeout`；没有将超时正文保存为已读来源，不能称公网读取成功。没有切换代理或绕过网络权限。
- 后续真实成功：用户确认成功，`data/validation/research/20261023T024740-c499fa/evidence.json` 为passed，7次实际模型调用、8条工具过程、2次成功搜索、1次成功阅读；报告已保存并通过重新打开恢复。只读复核SQLite的ready状态、报告与证据相同、所有引用有效、所有摘录SHA-256正确，未新增模型或搜索费用。
- 未完成的验收：报告内容逐项人工准确性核对、在途外网取消／硬重启及跨站重定向故障时序未全部覆盖。前端和造课集成明确不在本轮。单条真实成功不替代这些检查。
- 复验：在本地配置 TAVILY_API_KEY 与 OPENAI_API_KEY，显式运行本轮提供的 scripts/verify_research.py；会使用实际服务和产生费用。
- 长期契约已回写模型工作流／设计索引／API／数据／架构／安全及README，并新增学习速记。保留用户已有产品范围、产品感知、质量文档和项目暂缓history改动；未提交Git、未发布、未操作用户数据库。
