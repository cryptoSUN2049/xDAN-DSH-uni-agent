# Performance-9B 数据加工与 VERL 转换全局进度

更新时间：2026-09-25（performance-9b）

## 当前结论

数据已经完成“原版归档 → 统一母本 → VERL Parquet → train/validation 分片 → CPU dataloader smoke → GPU 启动前置检查”的主链路。当前仍缺真实 GPU `forward/backward`、checkpoint、W&B 与 rl-insight 后端三方对账，因此不能称正式 SFT 已完成。

本轮运行口径遵循用户确认的“来源/教师身份信任，先做格式适配验收”。历史质量审计仍保留 `training_ready=false`，它表示语言、许可证、语义质量、污染和固定验证集等门禁尚未重新授予，不应被格式 smoke 结果覆盖。

## 分阶段状态

| 阶段 | 产物/证据 | 状态 |
|---|---|---|
| 原始数据采集 | `/workspace/apus-data-cleaning/apus-source-archive-v1`，8 个来源，约 3.99GB，固定 revision 与 SHA | 已完成 |
| 中立母本 | `apus-sft-v1` 结构合同，62,030 行，流式校验 bad=0，SHA `c75aa706...` | 已完成 |
| 格式导出 | `/workspace/apus-data-cleaning/reports/verl-sft-v1/apus-sft-v1.parquet`，62,030/62,030，reject=0 | 已完成 |
| 数据分片 | `train.parquet` 59,164 行；`validation.parquet` 2,866 行；10 列 schema 一致 | 已完成 |
| VERL 适配 | JSON 动态列解码、Qwen 累计 chat-template、assistant header 零 mask、full-render 等价检查 | 已完成 |
| CPU smoke | 普通样本 1247 tokens / 48 loss tokens；真实 assistant tool-call 1341 / 135 | 已完成 |
| 远端环境 | `/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1`；adapter import exit=0 | 已完成 |
| GPU preflight | 正确账户的 `apus-openjev-serving`，pod `45ao3zsq6w7xck`，SSH `157.157.221.177:16358`，1× RTX PRO 6000 96GB | 运行中 |
| 真实 SFT | `run_verl_sft.sh`，原生 VERL，file/W&B，可选 rl-insight | 待 preflight 后启动 |
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

1. 等待 `sft_preflight.sh` 生成 `preflight.json`，确认 GPU、模型、Parquet、VERL adapter 和 W&B 凭据。
2. 用 `NPROC_PER_NODE=1`、`TRAIN_STEPS=1`、少量样本启动 `run_verl_sft.sh`，保留 `nohup`、`train.log`、`metrics.jsonl`、W&B 与 checkpoint。
3. 核对一步 loss/梯度有限、checkpoint 可读、W&B step 与本地 JSONL step 一致。
4. 设置 `VERL_RL_INSIGHT_ENABLE=1` 时再核对真实 insight 后端 trace；没有真实 trace 不标记 P4 完成。
5. smoke 通过后再决定全量 62,030 行或固定 20K 子集，不把候选数量当作质量准入。
