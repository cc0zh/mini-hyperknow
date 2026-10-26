# 可选产品 Skill

当前没有内置教学 Skill；普通教学与产物创建不以加载 Skill 为前提。

未来确有专门方法时，在此添加受版本管理的 `<name>/SKILL.md`，并在
`assistance_generation.py` 的 `TRUSTED_SKILLS` 显式白名单中装配。不会自动扫描
用户目录或任意文件。通用 `SkillRegistry` 保留目录读取、快照、版本和 SHA-256
校验；非空目录才向模型注册 `get_skills`，实际加载进入使用记录和执行轨迹。

Skill 正文不能授予工具、网络、文件或命令权限。
