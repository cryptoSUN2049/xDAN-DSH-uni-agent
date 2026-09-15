# Tinker项目记忆 — 2026-09-15

主线：Tinker Qwen3.5-9B Student / Qwen3.8-27B Teacher；Harbor任务、Modal CPU控制与sandbox。
权威现状：docs/tinker-harbor-opd-rl/p0-cloud-closed-loop.md及p0-live-status.json。
用户强调每环节谨慎、完整系统、官方教程+源码+独立工程判断；research/debug已用，当前不用inkling。

P0工程闭环已验收：run hybrid-p0-20260915-02，部署代码b06728a；真实1batch、1179动作/3595masked。
同一client initial/final adapters改变53,520,850个LoRA元素；独立reload成功，任务仅1/2，训练前2/2。
service-config重写时漏需保留timeout和path字段。小样本无配对seed，不归因为训练退化；能力提升未证实。
本批同题两条轨迹奖励[1,1]，RL advantage=0；实际非零信号为OPD。不能报告联合学习有效。
286相关测试通过；10核心综合90.67%/分支83.23%，不是全仓覆盖。训练4+reload2+audit2沙箱cleanup，sessionsclosed。
原始capture/Store/logtree/eval/trace/checkpoints保留Volume和实现worktree outputs；历史01缺git失败证据不覆盖。

接下来补评估actual SamplingParams、grader原文/末次工具观察/耗时截断；区分度开发集与非零RL；官方TB单任务重复；optimizer恢复；最小Control Panel。
当前HTML仍为方案快照，不是实际网页控制台；正式Terminal-Bench与超越Opus4.6均未验证。
App=tinker-harbor-opd-controller，Volume=tinker-harbor-runs；都保留，不为清理证据而stop/delete。
实现sibling tinker-cookbook-opd-rl/feat-harbor-opd-rl，所有代码在worktree。用户10美元不是余额/硬预算；不自动扩大付费实验。
