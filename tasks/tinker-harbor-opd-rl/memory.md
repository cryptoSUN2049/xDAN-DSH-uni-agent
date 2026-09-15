# Tinker项目记忆 — 2026-09-15

主线：Tinker Qwen3.5-9B Student / Qwen3.8-27B Teacher，OPD+RL，Harbor任务与Modal CPU/sandbox；模型能力目标尚未验证。
最新设计：docs/tinker-harbor-opd-rl/system-integration-review.md；先读此文再恢复实施。
用户强调测试/参数非零更新/reload/TB重复验收，不要过度精简；框架与控制面需同时参考官方教程代码及独立系统判断。
research/debug已使用；当前不用inkling。官方capture、Store、logtree、eval能力要核查实际接入，不能存在即视为启用。

实测：8/8原创任务nop/oracle；Student/Teacher各2/2；六轮1602 action、4482 masked Teacher评分通过。
云端Controller与cloud audit已成功；训练01缺git失败于日志初始化，未update；短付费预检已运行。
远端代码71176ee，本地76d8ac4修git未重新部署；无checkpoint/reload/能力提升证据；117相关测试通过。
用户已明确继续。A–D已完成本地集成：286项回归，新增核心模块覆盖率91%；下一关是新镜像云端bootstrap与同资源cloud audit，再有界重试一次。新训练尚未提交，不自动重试或扩大预算。

Cookbook源码在sibling tinker-cookbook-opd-rl分支feat-harbor-opd-rl，独立linked worktree。不要改主目录。
Modal App=tinker-harbor-opd-controller，Volume=tinker-harbor-runs，Secret=tinker-harbor-opd；子sandbox不携带Tinker key。
凭据未写仓库。用户充值10美元不等于实时余额或程序硬预算。正式Terminal-Bench兼容尚未验收。
