# 业务提示维护入口

此目录维护模型应如何完成对应业务的教学/调研指令，不执行模型、工具、SQL或前端动作。
没有通用模板引擎、Prompt基类、注册中心，也不要求每次生成使用Agent或Skill。

本页只定位提示相关修改；完整业务链路、上下文/状态/保存/前端影响与验证入口统一查[现行业务地图](../../../docs/ARCHITECTURE.md#10-现行业务与改动影响入口)。不是所有教学表现都能只靠改Prompt解决，也不把详细协议复制到这里。

| 要改什么 | 主要入口 | 需要同时检查的边界 |
| --- | --- | --- |
| 是否需要课程澄清、如何规划范围与单元 | course.py | domain.Clarification、planning_context、课程阶段/保存 |
| 讲义讲解深度、课堂问题怎么答 | classroom.py | lesson_context/question_context；操作类型变化联动Board渲染 |
| 课程练习与考核怎么命题 | quiz.py | quiz_context资料范围、QuizDraft、来源校验；计分仍由代码负责 |
| 搜索阅读方法、调研结论与来源表达 | research.py | research.py工具执行、来源与报告校验、公开网页权限 |
| 即时教学、提示深度、计划/提问/建议 | assistance.py | TeachingResponse、ContinuationState；不共享课程会话/进度 |
| 具体产物如何制作 | assistance_generation.py对应工具描述 | ARTIFACT_SCHEMAS、数量/用户禁令/最终原子保存及前端渲染 |
| 添加真正专门的方法包 | skills/与TRUSTED_SKILLS白名单 | 可选get_skills、快照及name/version/sha256使用记录；不授予权限 |

模型缺资料时先查上下文构建，不靠新增一句提示让它获取未提供的信息。
修改字段或动作时同步Schema、前后端与测试，不靠文案推测动作。
权限在Prompt中告知、在代码中强制是必要双层保障；不要为消除文字重复删除校验。
基本教学不强制依赖Skill，不为当前空目录创建替代Skill。
