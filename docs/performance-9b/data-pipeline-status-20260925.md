# Performance-9B 数据加工与 VERL 转换全局进度

更新时间：2026-09-25（performance-9b）

## 当前结论

数据已经完成“原版归档 → 统一母本 → VERL Parquet → train/validation 分片 → CPU dataloader smoke → 双卡 GPU pilot”的主链路。pilot 已完成真实 GPU `forward/backward`、checkpoint 和 W&B 对账；rl-insight 的 Ray monitor 仍未收到 trace，因此不能称观测闭环和正式全量 SFT 已完成。

本轮运行口径遵循用户确认的“来源/教师身份信任，先做格式适配验收”。历史质量审计仍保留 `training_ready=false`，它表示语言、许可证、语义质量、污染和固定验证集等门禁尚未重新授予，不应被格式 smoke 结果覆盖。格式链路已进入真实训练 pilot，但这不改变数据质量门禁状态。

## 分阶段状态

| 阶段 | 产物/证据 | 状态 |
|---|---|---|
| 原始数据采集 | `/workspace/apus-data-cleaning/apus-source-archive-v1`，8 个来源，约 3.99GB，固定 revision 与 SHA | 已完成 |
| 中立母本 | `apus-sft-v1` 结构合同，62,030 行，流式校验 bad=0，SHA `c75aa706...` | 已完成 |
| 格式导出 | `/workspace/apus-data-cleaning/reports/verl-sft-v1/apus-sft-v1.parquet`，62,030/62,030，reject=0 | 已完成 |
| 数据分片 | `train.parquet` 59,164 行；`validation.parquet` 2,866 行；10 列 schema 一致 | 已完成 |
| VERL 适配 | JSON 动态列解码、Qwen full-render offset mask、assistant header 零 mask、完整渲染校验 | 已完成 |
| CPU smoke | 普通样本 1247 tokens / 48 loss tokens；真实 assistant tool-call 1341 / 135 | 已完成 |
| 远端环境 | `/workspace/verl-uni-agent-harbor-opd-rl/envs/performance-9b-sft-py312-cu128`；FlashAttention/causal-conv1d smoke、adapter import | 已完成 |
| GPU preflight | `high-performance`，pod `db7kewdkd71js6`，SSH `157.157.221.177:11403`，2× RTX PRO 6000 Blackwell，cu128 | 已完成 |
| 真实 SFT pilot | `verl-sft-cu128-pilot-v3-20260925T0508Z`，2 卡 FSDP、16 步、512 train / 64 validation samples | 已完成；exit=0 |
| pilot 证据 | `global_step_8`、`global_step_16`；W&B [92602dg0](https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/92602dg0)；最后 `val/loss=1.0285366` | 已完成 |
| rl-insight | 服务已启动，但原生 torchrun 未初始化 Ray，pilot 日志为 monitoring disabled | 服务可用；本次 trace 未验收 |
| 质量门禁 | 历史 v5：provisional 10,494、quarantine 51,536、approved 0 | 未重新授予 |
| 20K 抽取 | 尚未生成正式 20K 训练版 | 待质量/配额决策 |

## 当前数据字段

VERL Parquet 的固定列为：

`messages`, `tools`, `enable_thinking`, `data_source`, `ability`, `record_id`, `task_group_id`, `split`, `teacher_family`, `audit_json`

`messages` 与 `tools` 保存为 JSON 字符串，是为避免动态工具参数造成 Arrow nested struct schema 不稳定；运行时由 `ApusMultiTurnSFTDataset` 解码，不是改变 APUS 中立母本协议。

## 运行身份

本轮正确的 Runpod 账户是 `l98348740@gmail.com`。之前本机默认 key 属于 `xdanwork@gmail.com`，余额不足且看不到当前 pod；该 key 已确认是错误账户，不能用于本训练链路。

| 项目 | 值 |
|---|---|
| pod | `45ao3zsq6w7xck` / `apus-openjev-serving` |
| SSH | `157.157.221.177:16358` |
| volume | `72jdno5cuk` / `RL-Harbor-sky_volume` |
| GPU | 1× NVIDIA RTX PRO 6000 Blackwell Server Edition，约 96GB |
| 源码 | `/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent` |
| 数据 | `/workspace/apus-data-cleaning/reports/verl-sft-v1` |

## 下一步验收顺序

1. 用 pilot v3 的同一环境重跑固定 20K 训练子集，先完成分域配额和 sealed validation 的准入记录。
2. 对 `global_step_8/16` 做可读性检查和固定验证集回归，确认 loss mask、长度截断和工具轨迹不出现漂移。
3. 再决定全量 59,164 行还是分阶段训练；不能把当前 16 步 pilot 直接外推成全量完成。
4. 若需要 rl-insight trace，必须为 SFT 增加明确的 Ray 初始化/事件发送路径；在此之前以 W&B、`metrics.jsonl`、`train.log` 和 checkpoint ledger 为准。
