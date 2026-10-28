# 评测产物收敛

## 目标、范围与风险

- 用户已授权同时简化后续产物生成与整理现有 data/evals；目标是每次测评一个目录，日常只打开 report.html，原始材料收进 details。
- 新目录默认采用 report.html + details/result.json、details/trajectories；复用既有 Runner、评分、报告，不重写判定。未迁移的旧schema-v2目录与显式JSON输出保留兼容；schema-v1仍仅report只读，不能恢复或重评。
- 现有证据全部保留；不改写历史 Trial、Case、评分身份或费用事实，不调用教学或评分模型，不修改作者业务库。
- 最大风险是移动历史 backend 改变 storage_id、移动 JSON 破坏绝对路径。历史整理先按实际绑定制定边界，不以移动目录覆盖恢复安全。
- 报告是派生展示：仅带管理标记的固定入口可更新，历史快照保留；重复导出同一内容不再堆同义快照。
- 关联设计：[后端评测](../../design-docs/backend-evaluation-pipeline.md)。

## 进度与决定

- [x] 核对用户授权、现行 CLI、报告目录及仓库规范；工作区已有大量未提交修改，保留全部既有工作。
- [x] 实现统一结果路径解析、新目录布局与单次报告入口；补充6项目录回归及1项首页回归。
- [x] 按安全边界整理现有产物，并记录可核对的迁移清单。
- [x] 核对历史证据哈希、报告链接、旧路径兼容与相关测试。
- [x] 同步现行说明、设计、history并归档计划。
- 2026-10-27：新目录仅展示report.html与details；绑定既有数据库的历史目录保留backend原位例外。固定入口为data/evals/index.html，报告目录只突出最近导出的一份，不将最近导出冒充最新实验。
- 2026-10-27：4个工程验证目录收进details/validation；固定答卷核查收进runs下的单目录。8个v2 Trial连同相对轨迹整组收纳，1个v1结果不迁移；10个backend不移动、不复制替换。历史脚本仅作证据归档。
- 2026-10-27：私有清单data/evals/details/organization.json记录126项文件/目录移动、567项原文件摘要及数据库device/inode。除可重建的review/index.html与catalog.json正常更新外，原文件逐项原字节保留，9个结果及评分摘要不变。旧路径可按清单from→to查找，不伪造原始环境中的路径。
- 2026-10-27：两份历史README含原相对链接，归档为.md.txt以保留原字节和历史语境，不再当作现行导航；当前导航全部使用新HTML入口。

## 验收与交接

- uv run --frozen python -m unittest discover -s tests -p test_eval_artifacts.py -v：6项通过；报告目录回归11项中10项通过、1项因Windows符号链接权限明确skip。
- 完整npm.cmd run ci退出0：514项Python中513项通过、1项上述skip；21项Node通过，包含文档、仓库与分发门禁。唯一CI日志位于忽略的data/evals/details/validation/artifact-layout/ci.log。
- 检查15个主报告/导航页面，无缺失或越界链接；正式离线report从新目录成功读取原failed结果，再次导出前后均为20份快照，没有新增同义快照。源文件哈希与数据库原路径、device/inode再次核对通过。
- git diff --check通过；归档后仅做文档与空白检查，不因纯文档归档重复完整CI。
- 本次没有教学/评分模型请求，没有恢复或重评历史任务，没有修改作者默认业务库；不以工程或导航检查声称模型质量或独立真人校准通过。被测版本unknown等原始事实不变。
- 长期约束已同步后端评测设计及安全说明；质量状态未变，不额外改写质量评分。目录使用说明见evals/README.md和evals/general/README.md。
