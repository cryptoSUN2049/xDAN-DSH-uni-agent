# R17 双卡 colocate_async 全链路验收

验收时间：2026-09-30 03:30 新加坡时间。结论：**MiMo 9B → DSH → Harbor/Modal → TransferQueue → 双 rank GRPO → checkpoint/权重反馈 → W&B/RL-Insight 工程闭环通过**。这是一个真实 Code 任务上的三步验收，不是完整数据集训练或能力提升证明。

## 实际运行与证据

- Run：`mimo9b-001661-r17`；源码冻结 `4a499cfcf8e5fa361b20f009d2c1472e7b49dd73`；分支/worktree `verl-uni-agent-harbor-opd-rl`。
- Runpod `db7kewdkd71js6`，两张 RTX PRO 6000 Blackwell；actor FSDP world size 2，共置两个 TP1 rollout replicas，`colocate_async` / native naive IPC。
- 两 replica 真实请求/生成 token、两 actor rank 和两个环境任务实际并发已有[双卡采样证据](evidence/r17-real-dual-sampling-20260929.json)。
- 原生训练完成 steps 1–3，exit 0，耗时 3375.206 秒，健康检查失败 0；C1/C2/C3 均保存，latest checkpoint marker 为 3。
- [W&B 原生运行](https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/mimo9b001661r17)：fresh API + 无 keys 的 `scan_history()` 获取全部三行，状态 `finished`；**264/264 console 指标一致**，全部有限，没有补写或修改状态。见[API 对账证据](evidence/r17-wandb-final-20260929.json)。
- RL-Insight terminal ack 查询实际 Prometheus，step 3、grad 0.1513671875、reward mean 0.25 匹配；Tempo 524 traces，含 498 gateway、13 task、13 session。13 中仅 12 条被训练消费，另 1 条为完成的预取。

| 训练 step | 真实奖励 | actor grad norm | actor pg loss |
|---|---|---|---|
| 1 | [1,0,0,1] | 0.126953125 | 0.04191888868808746 |
| 2 | [1,1,0,0] | 0.1279296875 | -0.030729874968528748 |
| 3 | [0,0,0,1] | 0.1513671875 | -0.21434767614118755 |

三步 learning rate 均为 1e-6。最终[batch 审计](evidence/r17-final-batch-audit-20260929.json)逐条验证 12 条消费记录的 receipt、NPZ、TransferQueue key、奖励、组完整性及 Gateway policy version。generation→consumer 对应 1→1、1→2、2→3；保留真实 budget-terminal 状态，未将预算终止改写为完成。

## 参数实物及组合验收

[最终 world2 验收](evidence/r17-world2-acceptance-20260929.json) PASS：独立重算 C1/C2 原始 checkpoint 文件 SHA，关联真实 step 2 console、消费组和严格参数审计。

- 760 个 base tensor 全部原 dtype 精确不变；716 个 LoRA tensor 中 493 个变化；全部有限。
- 两 rank optimizer 均从 step 1→2，各 716 active states / 60 empty states；各 992 个 moment tensor 变化。
- 原生模型格式为 DTensor，逻辑 CUDA mesh `[0,1]` / `fsdp` / `Shard(0)`；审计使用 CPU local tensors，验证分片完整、不重叠、rank 归属，CUDA 始终未初始化。
- Step 2 有正负 advantage（约 ±0.8660238981）、非零有限梯度、不同奖励，与更新证据属于同一步。
- [完整参数报告](evidence/r17-sharded-checkpoint-audit/README.md)无损压缩保存；解压 SHA256 `9bc05301a4ca1c3e039ef101246104e09cb9f4822177e4f7617df77275a17760`。

## 固定版本与范围

| 项目 | 固定值 |
|---|---|
| Model | XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B @ `2367e865d009c13ac81713a2878291d33ab28177` |
| Data | XiaomiMiMo/MiMo-V2.6-RL-oss @ `639865fd3374018d6cb29b9fb82dd531406fcf5f`；实际 Code Task 001661 |
| DSH | `b2369692ea530007075ebcd18d39fdba0bbd3982`，SDK/runtime `0.1.3a2` |
| VERL | `a9f2985159536a607211dcac730d3f5d55028950` |
| 环境 | 复用固定 Python 3.12 / Torch 2.11 cu130 / vLLM 0.23；273 项依赖约束 |
| 训练 | 32K context，20480 episode generation，4096 per call，LoRA rank16/alpha32，seed42，n4，sessions2 |

训练原始源目录 `/workspace/mimo-dsh-rl-20260928/run-src-r17` 未改动；checkpoint 位于 `runs/r17/rl-training/checkpoints/`。后续审计修复在独立 cloud CPU stage 执行；Mac 未运行模型、训练或下载大权重。

## 阻塞根因与修复验证

1. R13：prepare 环境覆盖 recipe，把 sessions2 改回1；最终配置预检拦住。修正真实 prepare→compose 绑定。
2. R14：手动 controller PATH 错误，首次注册无法找到已有 cloudflared；修正路径并加入实际二进制/HTTPS 预检。
3. R15：训练并发2，但 worker/SQLite ledger 仍单任务，第二请求 HTTP409；修复端到端有界容量，真实 HTTP 两接受、第三拒绝、取消/清理隔离回归通过。
4. R17 审计：旧同步 auditor 错把采样 step 当消费 step；增加显式 async v2，以唯一 TQ key 关联真实消费并保留两个时间轴。旧默认同步行为保留。
5. R17 参数检查：旧工具仅支持 ShardedTensor，实际 FSDP2 为 DTensor；新增严格原生格式支持，保留第一次 unsupported-type 失败证据，未降低数值判断标准。

最后一批云端 CPU 回归：async/world2 **87 tests** 通过，两个文件覆盖率分别 **82.91% / 98.44%**；原生双 rank checkpoint **17 tests** 通过，checker 覆盖率 **89.88%**。覆盖率包含分支且无排除行。证据：[回归报告](evidence/r17-async-world2-audit-validation-20260929.json)、[checkpoint 测试](evidence/r17-sharded-checkpoint-audit/dtensor-fixture-status.json)。源码 SHA 与本地待提交文件逐一一致；提交后推送前在该精确 commit 的干净 worktree 执行全仓 Ruff 双门禁。

## 资源与未覆盖项

[清理证据](evidence/r17-cleanup-final-20260929.json)：controller/driver/timeline/archiver 已退出，两卡 0MiB、无 compute process；28 个本轮 Modal sandbox 独立 API 确认结束。13 个成功 job 中仅 12 个被消费，2 个取消的预取 job 保留 pending 归档记录。GPU Pod 和共享观测服务保留，**Pod 未停止，仍可能计费**。

训练在既定截止前自然结束，未因完成而新开 GPU 运行。两个 qwen3coder malformed XML 解析异常由框架处理，未导致训练失败；原始错误仍保留用于后续协议质量分析。

**未验收：** 新 R17 world2 独立重启恢复、精确恢复在途队列、64K、完整2698条 Code 数据训练、其他四领域、能力提升。历史 R12 separate_async 独立恢复已通过，但不能替代本轮 world2 恢复。下一步优先在相同 world2 上做一次有界独立恢复及多任务留出评测，再考虑长程训练；不以更高 GPU 利用率单独判定训练质量。
