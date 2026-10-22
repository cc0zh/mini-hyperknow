# API、事件与客户端同步契约

状态：2026-10-22 造课／课程查询与 run 通知已实现；课堂、答题和成果端点仍为目标，不能据此调用未实现功能。
关联：[架构](../ARCHITECTURE.md)、[数据](data-model.md)、[交互](learning-experience.md)。

## 1. 基本约定

- REST 使用 `/api` 前缀，JSON 字段统一 snake_case；不要求兼容原站 `/api/v1` URL 与字段。
- 不做公开登录；本地固定身份，默认回环访问。前端开发通过代理同源访问。
- 查询返回已保存快照及 version；命令返回提交后结果。长任务返回 202 与 run_id，不阻塞 HTTP 到模型工作完成。
- 写命令携带 client_command_id；同 ID／输入重试返回原结果，不重复创建或提交；同 ID 异输入返回 409。
- 修改已有聚合携带 expected_version；冲突返回 409 和 error.latest_version，客户端重新读快照，不静默覆盖。
- 未知端点返回 404，错误使用相应 4xx／5xx，不返回 `success: true, stubbed: true`。

通用错误示意如下，仅为协议说明，不是测试桩或实际运行证据：

```json
{
  "error": {
    "code": "model_request_failed",
    "message": "模型请求失败，本次未生成课程",
    "retryable": true
  }
}
```

错误消息不含密钥；区分配置缺失、请求失败、内容校验失败、保存失败和状态冲突。

## 2. REST 功能面

当前 schema 由 Pydantic/OpenAPI 落实，前端有消费类型；不在文档另维护完整类型库。下表从 health 到 courses/{course_id} 已实现，其后的 session／quiz／project 为后续目标。

| 方法与路径 | 作用及保存边界 |
| --- | --- |
| `GET /api/health` | 服务、数据库与模型配置状态；已配置不等于真实模型连通 |
| `POST /api/course-runs` | 保存文字目标，建立生成 run，返回 202 |
| `GET /api/runs` | 最新 30 条运行，课程库恢复等待、失败、取消或中断的任务 |
| `GET /api/runs/{run_id}` | 运行阶段、澄清、结果引用或错误 |
| `POST /api/runs/{run_id}/answers` | 保存答案；`skip: true` 明确跳过，进入课程生成 |
| `POST /api/runs/{run_id}/cancel` | 显式取消，阻止晚到结果生效 |
| `POST /api/runs/{run_id}/retry` | 根据原输入建立新 run，不重写旧运行身份 |
| `GET /api/courses` | 课程列表及一致的进度摘要 |
| `GET /api/courses/{course_id}` | 完整目录、完成情况、课时比例和 next_item |
| `GET /api/sessions/{session_id}` | 课时元数据、脚本／进度／互动引用；不触发模型 |
| `POST /api/sessions/{session_id}/prepare` | 无讲义时建立真实生成 run；已有版本直接返回 |
| `GET /api/sessions/{session_id}/lesson` | 已保存讲义、位置及问答快照 |
| `PUT /api/sessions/{session_id}/progress` | 保存脚本版本、步骤与播放意图，验证步骤合法性 |
| `POST /api/sessions/{session_id}/questions` | 保存插话与锚点，建立回答 run；回答稍后保存 |
| `POST /api/sessions/{session_id}/thought-answers` | 保存思考题答案，返回判定或反馈 run |
| `POST /api/sessions/{session_id}/complete` | 手动完成，更新课程版本和进度 |
| `POST /api/sessions/{session_id}/practice/prepare` | 基于真实教学内容生成题组；已有版本直接返回 |
| `POST /api/exams/{exam_id}/prepare` | 基于单元内容准备考核题组 |
| `POST /api/quizzes/{quiz_id}/attempts` | 明确新建尝试；页面刷新不重复建立 |
| `GET /api/quizzes/{quiz_id}/attempts` | 查找未完成尝试或已完成结果 |
| `GET /api/attempts/{attempt_id}` | 题目、作答状态、当前位置与结果 |
| `POST /api/attempts/{attempt_id}/answers` | 保存选项／跳过及用时；服务端判定，不接受总分 |
| `POST /api/attempts/{attempt_id}/submit` | 全题已答／跳过后汇总、完成活动；重复提交不重复完成 |
| `GET /api/projects/{stage_id}` | 阶段要求、所属项目与已保存成果 |
| `POST /api/projects/{stage_id}/submissions` | 保存非空成果并完成阶段，同事务提升课程版本 |

本地单用户允许客户端取得题目答案和解释，不做防作弊；计分仍由后端执行真实规则，避免两套口径。活动 ID 必须属于所引用课程。

最后一题“看结果”：确认答案已保存 → 提交尝试 → 展示结果。“回到课程”只导航不再次提交。失败保留状态，可用同一命令身份重试。

## 3. WebSocket 只做通知

当前连接 `/api/events`，已实现主题 `run:{id}`；`course:{id}`、`session:{id}` 和 `attempt:{id}` 尚未实现。不通过另一套 WS 命令修改业务。

```json
{
  "type": "resource_changed",
  "resource_type": "run",
  "resource_id": "run_example",
  "version": 3,
  "state": "awaiting_answers"
}
```

事务提交后发送通知，不携带唯一正文，不是事件溯源日志，不承诺历史无限回放。前端按资源 version 忽略旧通知，收到更新后读取快照。

连接成功回复 `connected`；每次订阅成功回复 `subscribed` 和对应主题。初次连接或重连均先等待订阅确认，再拉取当前快照，避免先查询后订阅的漏更新窗口。读取期间收到的通知暂存并按 version 合并；快照返回后若有更高版本通知，再次查询，不能以旧快照覆盖新状态。心跳只代表连接，不代表模型仍在执行。

## 4. 播放与同步

- 一个前端播放器推进，reducer 用 script_id + step_id 避免重复应用；后端不开第二套讲课计时器。
- 进度串行保存；完成一个展示步骤后确认，期间不双重推进，不在每次渲染时发送写请求。
- 当前呈现步骤未确认前不提示“已保存”；断网暂停推进，不无限积累未保存步骤。
- 回看页栏不改变内容写入游标。恢复从脚本与保存位置重建，用户继续前保持暂停。

## 5. 复用与竞争

已有脚本／题组就返回版本；已有对应活跃 run 就返回该 run，不另启模型调用。显式 retry 只在 failed／cancelled／interrupted 状态建立新 run。

取消与模型完成竞争以事务内状态为准，已取消结果不提交；ready 后取消返回明确冲突，不删除课程。单进程事务和版本检查足够，不引入分布式锁。

内核 emit 不是本协议。当前 CI 用实际 Uvicorn HTTP／WS 检查缺配置、无效请求、空列表和不存在的订阅；没有凭据不能证明生成成功，未来课堂端点也未验证。生成 OpenAPI 不代表接口验收完成。
