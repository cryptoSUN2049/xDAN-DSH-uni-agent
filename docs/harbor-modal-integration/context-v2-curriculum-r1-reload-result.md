# Context v2 十二步课程：独立 step12 reload 验收

本轮为真实 Linux GPU 运行的事后 CPU 审计，2026-09-09。工程 reload 验收通过；效果提升未通过，四条 dev 严格成功仍为零。

## 已核验事实

- 固定运行代码 `d3084f2a771804f011c4e641ecf0986c7166bc86`，既有 `uni-agent-rebuild-cf2d3f5` 环境。未修改远程源码。
- 新 run：`/root/runs/context-v2-curriculum-r1-reload-step12`；监督 child PID `178937`，exit `0`，470.012 秒。
- 真实日志 01:03:33–34 明确从母课程 `global_step_12/actor/` 加载 model、optimizer、rng 和 lr_scheduler。完整选取行见结果 JSON。
- 四个新的 Gateway session 均与母课程 session 集合不重叠；对应 dev-D/C/M/V，四份 `fresh`、finished、eligible 回执经原生 group/消费审计通过。四组仅属于 `val`，global_steps=12；零拒绝、零异常消费、零 legacy 不可关联记录。
- `val_only=True`，没有 actor/grad_norm 或 critic/advantages 训练指标，rollouts 目录为空。新的 checkpoint 目标目录确实被创建，但内部为空；因此没有新 checkpoint，不能描述为“目录不存在”。
- dev verifier reward：D=0.671875、V=0.72、M=C=0.1；平均 **0.39796875**，严格成功 **0/4**。与母课程最终 dev 相同。

## 母课程更新证据补全

专属 `deployment.checks.optimizer_delta` 在 CPU 上对本次 step6→12 实际 optimizer 文件运行，结果通过：504 个 active state 的步数均从 6 到 12；1008 个 moment tensors 全部变化且有限；37 个 empty state 保持。此报告补充已有参数差异审计（504 个 adapter tensor 变化、399 个 base tensor 不变），不复用旧的两步实验结论。

母课程仍保留原生 audit `eligible=false`：D3 的一条 sibling 因越界文件读取被拒，整组未消费；trainer 用额外 D2 补足批次。实际是 **12 个有效训练 batch、48 条消费、11 个唯一任务**，不能宣称十二个唯一任务全部完成。拒绝的具体根因见 [D3 审计](context-v2-curriculum-d3-rejection-audit.md)。

## 证据文件与云盘归档

- [Reload 结果与加载行](context-v2-curriculum-r1-reload-result.json)
- [原生四组消费审计](context-v2-curriculum-r1-reload-consumption-audit.json)
- [Optimizer step6→12 审计](context-v2-curriculum-r1-optimizer-delta-6-12.json)
- [归档路径及哈希](context-v2-curriculum-r1-evidence-archive.json)

云盘：`/workspace/reports/context-v2-curriculum-r1-step12-reload-evidence.tar.gz`，33,349 bytes，76 个成员，SHA256 `e98f4d3ef4e04f8cd18318a22d8fb8ac6d9cfcf6ec97b3b1ff8898a61f9d8a0f`。显式白名单仅包含本次 reload 与母课程的审计、参数/optimizer/终态报告和 trajectory JSON 元数据；内置逐文件 SHA256 清单。排除 token NPZ、prompt、环境、原始日志、模型和 checkpoint 二进制。

## 边界与真实踩坑

此前 PRINT_COMMAND 也会创建 run 目录及 completed manifest，首次监督因此在 GPU 启动前拒绝复用目录。父线程保留到独立 `-print-command-evidence` 路径后，用全新 run 路径监督重试；本报告只采信重试真实日志、轨迹与回执。后续 dry-run 必须独立 scratch RUN_ROOT。

该结果证明“已有训练产物→独立恢复→真实 DSH/Gateway 采样→验证消费”可运行，无需把提分和扩量前置为工程验收条件。四个已用 dev 任务不是独立留出效果研究；全项目 G1、记忆跨会话 RL、Harbor 与 RSI 后续里程碑不能据此一并宣称完成。
