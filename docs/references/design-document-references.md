# 设计文档组织方式参考

核对日期：2026-10-22。本文只记录外部资料的参考范围，不将其产品或架构要求直接继承到 mini-hyperknow。

## ActSpace

用户指定入口：[actspace-agent 设计目录](https://github.com/WakeUp-Jin/actspace-agent/tree/main/docs/design-docs)。本轮实际阅读：

- [设计索引](https://github.com/WakeUp-Jin/actspace-agent/blob/main/docs/design-docs/index.md)：区分设计、实施计划、外部参考与验证证据，明确专题职责及阅读路线。
- [数据存储结构与职责](https://github.com/WakeUp-Jin/actspace-agent/blob/main/docs/design-docs/core-data-storage-design.md)：明确权威数据、内存、查询数据的角色，区分目标、现有实现和未验证项。
- [存储职责、决策记录与实现边界](https://github.com/WakeUp-Jin/actspace-agent/blob/main/docs/design-docs/core-data-storage-responsibilities.md)：用职责表、决策记录及恢复边界避免“设计即完成”的误读。

本项目只借鉴文档方法：入口集中、每份文档边界清晰、状态诚实、决定有依据、验收不夸大。文档数量较少，先使用平铺专题文件，不为空分类创建目录。

明确不继承 ActSpace 的插件化 Host/Harness、多人／多 Agent 产品、权限平台、JSONL 权威日志及 SQLite 派生索引体系。本项目选择单个 SQLite 保存业务事实，见[本项目架构](../ARCHITECTURE.md)和[数据模型](../design-docs/data-model.md)。

外部 `main` 分支会变化；本次仅以核对日期说明阅读时点，后续引用不能自动推导其实现状态仍相同。

## 工程选择参考

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)：单进程连接管理及断线处理，不引入多进程广播系统。
- [Python asyncio.to_thread](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)：同步 I/O 不阻塞事件循环；取消等待不代表线程或远端调用已停止。
- [SQLite 事务](https://www.sqlite.org/transactional.html)：相关业务写入纳入事务，模型网络请求和 WS 通知不在同一数据库原子操作内。

本轮已读取相关内容支持选型和边界，不代表本项目服务已实现或完成故障实验。

## Hyperknow 规格参考

hyperknow-clone2 是外部只读参考仓库。实际阅读入口、证据等级和必要缺口见[参考与缺口](../design-docs/reference-and-gaps.md)。不复制抓取 token、真实用户样本或其他非必要原始数据到本项目。
