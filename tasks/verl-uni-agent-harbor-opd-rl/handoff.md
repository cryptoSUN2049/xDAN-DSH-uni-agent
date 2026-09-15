# TL;DR
Uni-Agent主线新分支已创建，基线9075dfa。实施已授权；升级合并预检已完成，7个冲突待处理，无训练或实际合并。
# 本轮交付物
docs/verl-uni-agent-harbor-opd-rl/integration-design.md：架构、来源、合同与验收。
# 设计约束
保留Gateway/DSH/任务准入/TQ/VERL；Tinker仅参考，不移植主trainer。
# 已发现的真实行为
entry.py拒绝teacher_client；TQ预留Teacher字段；VERL有Teacher manager。自定义Harbor执行器仍依赖Docker。
# 下一里程碑
- [x] 用户明确授权创建隔离worktree并启动实施
- [ ] 逐项审计Teacher字段生成、消费、mask和版本
- [ ] 挑选Harbor在线分支独有修复，设计Modal执行器
# 分支/部署状态
verl-uni-agent-harbor-opd-rl；未启动远端服务，未提交推送。本worktree的verl子模块待按pin初始化。
# 冷启动
先读integration-design.md，再查git状态；不要把Tinker P0当VERL验收。

## 持久记忆入口
先读[memory.md](memory.md)，包含用户授权、固定SHA、阶段顺序及7个冲突文件；下次不重复询问实施授权。
