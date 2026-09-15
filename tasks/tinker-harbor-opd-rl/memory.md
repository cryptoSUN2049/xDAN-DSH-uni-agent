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

评估actual SamplingParams、grader原文/末次工具观察/耗时截断已本地补齐，465项相关回归，8实现模块综合86.34%；尚未云复验。先读eval-evidence-validation.md。下一步区分度开发集与非零RL；官方TB单任务重复；optimizer恢复；最小Control Panel。
当前HTML仍为方案快照，不是实际网页控制台；正式Terminal-Bench与超越Opus4.6均未验证。
App=tinker-harbor-opd-controller，Volume=tinker-harbor-runs；都保留，不为清理证据而stop/delete。
实现sibling tinker-cookbook-opd-rl/feat-harbor-opd-rl，所有代码在worktree。用户10美元不是余额/硬预算；不自动扩大付费实验。

此前候选现作为Shell基础补充：OpenThoughts-Agent-v1-RL@39ab71434e90d8f87d2cd69c13b6d8a0cb2c238f；728任务、616original_nl家族，parquet SHA35decc7d...59092c。已静态审查全部归档，未执行。接入先适配/workspace与/output、按家族划分、防task_manifest答案进入sandbox；详见openthoughts-rl-integration.md。

用户现确认公开Harbor训练、Terminal-Bench2.1独立评测（Hub89题/rev6，正式运行需锁版本）。TaskTrove三源5830题已下载；首批6候选兼容状态见public-dataset-status.json，未云运行。joint-opd-rl-reference.md可给另一个会话：131回归+4本地payload通过，真实P0复算RL0、OPD1138；不能报告双非零云学习或能力提升。
