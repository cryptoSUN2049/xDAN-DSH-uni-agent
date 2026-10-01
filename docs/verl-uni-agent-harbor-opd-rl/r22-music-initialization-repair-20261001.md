# Music 初始化阻断与修复（2026-10-01）

本轮尚无有效训练更新。首次后台运行 `mimor22musica` 在原生初始化退出 1，W&B API 查询返回 `run=null`。这项失败不能由 R21 Code 的 `finished/step5` 替代。

## 当前调用链

- 新入口：`examples/mimo_multidomain_rl/launch.py --domain music`。
- 观测包装：`docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py`。
- 实际 native trainer：固定 MiMo source `a2ad9f6160b03ff2d47e59832bfb6b289f37c917` 的 `verl.trainer.main_ppo`。
- 原 uv 273 环境复用，未重装。R21 DSH Code 的独立 `run-src-r20` 保持原字节，本次未调用其 Code 训练配置。
- 当前 Music 使用原生 single-turn loop 与 `recipes.design.music.scorer.compute_score`；没有 DSH/Harbor 工具调用。其余域的 harness 仍有各自前置门。

## 实际日志与 API

- 首次运行开始 11:01:05 UTC；11:09:56 actor/ref engine 初始化，11:20:46 两个 vLLM 服务地址已返回。
- 此后 `verl/workers/rollout/llm_server.py:568` 报 `ValueError: Metrics monitoring requires disable_log_stats=False, but it is currently True.`。
- 原默认 `rollout.disable_log_stats=True`，与本项目明确要求启用的 RL-Insight 监控冲突；检查位于服务启动之后。
- 原生结束 11:21:08 UTC，`launch-receipt.json` 记录 `failed/exit_code=1`。
- 11:22:35 UTC W&B 独立 GraphQL 查询 `mimor22musica` 返回 `data.project.run=null`。尚未进入 native Tracking，不存在本轮历史或 checkpoint 验收。
- 11:21 UTC 两卡显存均释放至 0 MiB；不是双卡仅使用一张的训练结果。

原始失败证据见 `evidence/r22-music-a-failure-20261001.json`；日志/原运行目录保留于 `/workspace/mimo-dsh-rl-20260928/r22/runs/music-r22a/`。

## 修复与验证

- Music recipe 显式设 `rollout.disable_log_stats: false`，保留原生监控。
- launcher 在 Hydra 实际配置组合后检查统计开关，错误以 `preflight_failed` 留档并禁止启动模型 workers。
- 全参数 FSDP 主权重恢复默认 FP32；原生 MixedPrecision 仍为 BF16 参数计算、FP32 reduce/buffer。这避免只以 BF16 主权重执行 `lr=1e-6` 的更新舍入风险；实际参数更新须另验。
- 云端 launcher 回归 8/8 通过，覆盖错误监控配置在 GPU 分配前被拒绝、物理恢复路径、独立运行身份及仅所属进程超时清理。
- 新运行 `mimor22musicb` 于 11:25:03 UTC 启动，监督 PID 16468/startticks 366972613；运行目录 `music-r22b`，单阶段 7200 秒约束，不自动停 Pod。

## 下一验收门

1. 两个 vLLM 服务及监控注册通过，实际 W&B run 创建。
2. 原模型生成八条同组轨迹，原 Music grader 产生实际组奖励。
3. 有限非零 advantage/梯度、全参数实际变化、native checkpoint。
4. 当前 W&B history 与 native 日志、RL-Insight 指标对账。
5. 物理恢复后第二步与 heldout；完成后继续其他域。

这些门目前未通过，不能称五域或 Music 训练完成。
