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

数据库默认 data/hyperknow.sqlite3，HK_DATA_DIR 可调整目录；本地数据、日志与凭据不提交。备份请先停止服务再复制 SQLite 文件。

## 检查与验收

```powershell
npm.cmd run ci
npm.cmd --prefix web test
npm.cmd run build
```

当前入口已迁移为无 Mock 的直接逻辑与真实本地服务检查。真实收费验收需配置后显式运行 uv run --frozen python scripts/verify_model.py；不配置时退出码 2，不能当作成功。细则见[真实验证](design-docs/real-validation.md)和[首切片计划](exec-plans/completed/20261022-real-course-library.md)。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| npm.ps1 被执行策略阻止 | 使用 npm.cmd |
| uv 不存在 | 安装 uv 并重新打开终端，不用其他包管理器创建第二套项目环境 |
| 数据库正常但模型未配置 | 在本仓库 .env 设置真实凭据并重启后端；health configured 不等于真实连通 |
| 生成失败 | 检查配置、网络、额度和状态后手动重试；失败不会创建模板课程 |
| 重启后显示中断 | 这是防止自动重复收费的预期行为；等待澄清可继续，interrupted 手动重试 |
| 5173 被占用 | 选择 5174，确认浏览器标题属于本应用，不复用其他项目页面 |
| 构建缺依赖 | uv sync --frozen 与 npm.cmd --prefix web ci；不要手改锁文件 |

保留模板初始化／metadata 打包工具的边界见 [CI/CD](CICD.md)，本轮未部署或发布产品。
