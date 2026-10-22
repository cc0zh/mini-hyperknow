# Windows 使用说明

## 环境

使用 PowerShell、uv、Python 3.13（.python-version）、Node.js 22.12+（推荐 24）和 Git。完整工具测试还需 tar。不需要 Bash、rsync、Perl 或单独用 pip 管理项目依赖。

```powershell
uv --version
node --version
npm.cmd --version
git --version
tar --version
uv sync --frozen
npm.cmd --prefix web ci
```

PowerShell 使用 npm.cmd 避免 npm.ps1 的执行策略冲突；其他平台用 npm。uv sync 自动创建 .venv，uv run 使用项目环境，无需手动激活虚拟环境。

## 本地运行与配置

仅在 .env 不存在时复制 .env.example，在本地设置 OPENAI_API_KEY，可选 OPENAI_MODEL、OPENAI_BASE_URL。修改配置后重启服务，不覆盖已有密钥，也不搜索参考项目的凭据。

分别在两个终端、仓库根目录运行：

```powershell
uv run --frozen uvicorn hyperknow.main:app --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd --prefix web run dev
```

访问 `http://127.0.0.1:5173`。若端口被其他项目占用，改为 npm.cmd --prefix web run dev -- --port 5174，不盲停未知进程。后端只监听回环，前端代理 /api 与 WS 到 8000。

数据库默认 data/hyperknow.sqlite3，HK_DATA_DIR 可调整目录；本地数据、日志与凭据不提交。升级前先停止旧服务；当前升级到v3，自动使用SQLite backup保存原v1／v2一致备份（`hyperknow.sqlite3.v1-backup_*.bak`／`hyperknow.sqlite3.v2-backup_*.bak`），再顺序事务迁移。原v2八表保留，新增三张题组／目标状态／作答表与未提交尝试唯一索引。新库直接建至v3，更高版本拒绝降级打开；手动备份仍应先停服，不把运行中复制主文件当完整备份。结构见[数据模型](design-docs/data-model.md)。

课堂从课程总览点击课时进入。首次进入只读取，点击“准备本课讲义”才会调用模型；失败／取消／中断需明确重试，不因刷新或重启自动收费。讲义保存后初始暂停，即使 GET 中保留 `play_intent=playing` 也不会自动播放。FontFace 同时加载本地原始 `/fonts/Excalifont-Regular.woff2` 与 `/fonts/Xiaolai-Regular.ttf`，分别呈现英文／数字／西文标点与中文／中文标点；字体栈为 `Excalifont, Xiaolai, sans-serif`。任一字体缺失时有提示，Mermaid 等待两者加载完成后才测量，不使用 CDN 或系统安装字体冒充成功；当前资源与验收见[字体参考](references/whiteboard-font.md)。

练习从课堂或课时目录进入，考核从所属单元进入。进入只读，明确“准备题组”才调用模型；练习需要已有讲义，考核允许真实课时大纲及已缓存讲义。开始／再练明确建立尝试，逐题保存后停留反馈，下一题才记录新起点；末题明确“看结果”提交，结果保留不自动跳回课程。思考题及项目成果提交仍未开放。

## 检查与验收

```powershell
npm.cmd run ci
npm.cmd --prefix web test
npm.cmd run build
npm.cmd run check:docs
```

当前入口已迁移为无 Mock 的直接逻辑与真实本地服务检查。真实收费验收需配置后显式运行 uv run --frozen python scripts/verify_model.py；不配置时退出码 2，不能当作成功。细则见[真实验证](design-docs/real-validation.md)和[首切片计划](exec-plans/completed/20261022-real-course-library.md)。

首切片记录是原造课／课程库的历史证据，不自动覆盖课堂。当前局部模型调用与本地检查进展统一见[可靠性状态](RELIABILITY.md#验证与交付)；课堂冷重启与手动完成见[课堂计划](exec-plans/completed/20261022-real-whiteboard-classroom.md)，本阶段练习／考核真实出题、显式提交、结果停留及已保存作答冷重启见[完成计划](exec-plans/completed/20261022-real-practice-exams.md)；最终CI、前端与文档门禁已通过，不据此宣称全部V场景通过。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| npm.ps1 被执行策略阻止 | 使用 npm.cmd |
| uv 不存在 | 安装 uv 并重新打开终端，不用其他包管理器创建第二套项目环境 |
| 数据库正常但模型未配置 | 在本仓库 .env 设置真实凭据并重启后端；health configured 不等于真实连通 |
| 生成失败 | 检查配置、网络、额度和状态后手动重试；失败不会创建模板课程 |
| 重启后显示中断 | 这是防止自动重复收费的预期行为；等待澄清可继续，interrupted 手动重试 |
| 课堂打开后没有自动讲课 | 初次与恢复均本地暂停；点击准备生成或在已有讲义上明确开始播放，GET 的播放意图不是自动播放指令 |
| 显示上次写入结果待确认 | 保留原命令并点击“重试同一命令”；409 重新读取权威快照后检查位置，勿绕过版本检查 |
| 手写体／公式／图形未显示 | 检查 Excalifont WOFF2 与 Xiaolai TTF 两项本地请求和字体提示；公式／SVG 错误使用界面重试渲染，不以通用字体或源码视为通过 |
| 5173 被占用 | 选择 5174，确认浏览器标题属于本应用，不复用其他项目页面 |
| 构建缺依赖 | uv sync --frozen 与 npm.cmd --prefix web ci；不要手改锁文件 |

保留模板初始化／metadata 打包工具的边界见 [CI/CD](CICD.md)，本轮未部署或发布产品。
