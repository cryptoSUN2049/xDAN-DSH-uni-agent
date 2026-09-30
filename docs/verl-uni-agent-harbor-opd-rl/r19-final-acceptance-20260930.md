# MiMo 9B Code RL 最终工程验收（R19）

2026-09-30：R19 以独立运行身份从 R17 原生双 rank C3 恢复，完成真实 Harbor/Modal DSH 采样、独立 verifier、有效 GRPO 更新并保存 C4，正常 exit 0。W&B 原生 API 状态为 finished，step 4 的 88/88 项指标与同一次 TaskRunner 原始日志一致。联合证据见 [r19-final-joint-acceptance-20260930.json](evidence/r19-final-joint-acceptance-20260930.json)。

## 实际链路与结果

Runpod 双 RTX PRO 6000 → VERL/Uni-Agent `colocate_async`（actor world-size 2、FSDP1、两 TP1 rollout replicas）→ 同机 CPU controller/gateway → Harbor 在 Modal 执行固定 DSH → 独立 verifier → TransferQueue/token/mask/logprob → GRPO → 双 rank checkpoint。控制器独立进程，同 GPU Pod 的 CPU 上运行，无 CUDA；无需再租控制 Pod。

| 验收项 | 本轮实际结果 | 原字节证据 |
|---|---|---|
| 独立恢复 | 新 run `mimo9b-001661-r19`；两 rank model/optimizer/RNG/scheduler 原生成功日志，initial step 3，进入 fit | [native resume](evidence/r19-native-resume-proof-20260930.json) |
| 实际消费 | 4 个唯一 TQ key；所有 generation 均使用 policy 3；step 4 消费奖励 `[0,1,1,0]` | [batch](evidence/r19-final-batch-audit-20260930.json) |
| Token 合同 | 四条消费轨迹均通过原始 backend journal → context/rollback/commit → NPZ token IDs、mask、finite float32 logprob 重放 | [token audit](evidence/r19-consumed-token-audit-20260930.json) |
| 有效更新 | advantage ±0.866023898；grad norm 0.13671875；pg loss −0.160664834；760 base 项不变，496/716 LoRA 项变化 | [joint update](evidence/r19-world2-acceptance-20260930.json) |
| Optimizer/C4 | 两 rank step 3→4，各 992 个 moment tensor 变化；原生 C4 双 rank 文件及 SHA 已核 | [native checkpoint](evidence/r19-native-checkpoint-audit-20260930.json) |
| W&B | 原生 finished；1 行历史/绝对 step 4；88/88 指标对账，无补写/回填 | [W&B API](evidence/r19-wandb-final-20260930.json) |
| RL-Insight | Prometheus 三项终态真实 scrape；Tempo 本 run 范围内 166 traces | [native observability](evidence/r19-native-observability-final-20260930.json) |
| 回收 | 10 个所属 Modal sandbox API 确认结束；所属进程退出，6 个专用端口释放；两卡 0MiB；精确移除本轮 SSH 授权项 | [cleanup](evidence/r19-cleanup-final-20260930.json) |
| 版本/成本 | 固定 release、任务与模型/数据来源；GPU 分配成本约 $2.09/native window 或 $2.24/driver window，两者不可相加 | [pins](evidence/r19-final-pin-audit-20260930.json)、[cost](evidence/r19-cost-reconciliation-20260930.json) |

[实际 W&B Run](https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/mimo9b001661r19)。API 报告查询时间约 03:05 UTC；训练在约 02:52 UTC 正常结束，后续空 GPU 是完成后状态。

## 复查入口

- 冻结训练源码 commit `4dbd87ad4f6123f99a1f715a6637322a44cff6a5`；1003 文件 manifest SHA `04fb0fcd1eb0b62aa89dce193211080ce4b6000f8df6a97a225a027c946564af`。
- Run spec SHA `5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33`。R17 C3 parent manifest SHA `8046c24e335682ec67fdf71b1c3f1fc0dc05e016ee17246950858ef5f9001706`。
- 云端根目录 `/workspace/mimo-dsh-rl-20260928`；C3 `runs/r17/rl-training/checkpoints/global_step_3`，C4 `runs/r19/rl-training/checkpoints/global_step_4`。权重及原始 token journal 保留云端，不下载 Mac。
- 公共报告保存原始 SHA 与私有原件路径。4.89MB 全量 CPU checkpoint 审计保留 `integration-check/r19-c3-c4-checkpoint-audit.json`，公共摘要不是完整逐参数报告。
- 云 CPU preparation 回归 116 项通过，helper 覆盖 99.07%、preflight 98.74%；token/runtime 审计相关既有云回归 145+23 项。R19 实际 prepare/preflight exit 0、CUDA 未初始化。最终报告收尾不修改冻结运行源码或共享 273 项环境。

## 验收边界与失败保留

- 本阶段只验收 MiMo Code task 001661 的小样本工程闭环，不证明能力提升、全数据训练或五领域复现。R17 三步成功与 R19 独立恢复分别保存证据；R18 控制宿主不可用、fit 前失败的记录保留。
- 四条消费轨迹为 `completed, budget_exhausted, budget_exhausted, completed`。两个预算终态在冻结的 budget-terminal-v1 合同下经真实 verifier 得到正奖励；不能称四条都正常完成。另有两条取消预取，不计训练样本。
- checkpoint 差异报告自身的 `resume_verified:false` 不改写；恢复由独立原生加载日志证明，再与 policy 3 采样及 C4 更新组合。TransferQueue 在途任务精确重放未验收，新队列重新采样。
- Token 审计证明传输及上下文/mask/logprob 语义一致，未独立重算模型 forward 概率；不宣称概率校准。Prometheus 每项只有一次真实终态 scrape，query_range 重复求值不算第二次采样；Tempo 每个 root type 抽取一条真实 payload 复核，未逐条审核全部 166 payload。
- Modal API 返回码 137 表示已终止，不能据此诊断 OOM。此链路没有 Docker sandbox backend，未宣称做了 Docker 全局清理。
- GPU Pod `db7kewdkd71js6` 按用户要求保留；共享 RL-Insight/Prometheus/Tempo 保留。训练自然结束不等于 Pod 停止计费。Modal、存储/传输完整账单未知；Runpod 最新 API 网络失败，不用历史 bucket 冒充本轮实际成本。
- 安全事件：收尾子代理曾用过宽的私有 JSON 遍历误读 Cloudflare TunnelSecret，进入该工具输出；未写入公共报告、代码或 Git，未复制或全局轮换凭据。公共交付扫描禁止私钥/token 明文。建议按隧道使用影响安排 scoped 凭据轮换；不能无归属核验影响其他会话。
