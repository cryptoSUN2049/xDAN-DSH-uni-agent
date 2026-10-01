# MiMo 9B R21：实际训练范围、参数与完成证明

本次 `mimo9b-002549-r20f` 完成一个新 Code 任务的四轨迹 GRPO/LoRA 更新：从已验收 C4 原生恢复到 C5。联合验收19项通过；2026-10-01 01:45 UTC 再查询 W&B API 为 finished、step5。这不是全量数据集训练，也不是连续六小时训练。

## 数据与范围

数据来自 XiaomiMiMo/MiMo-V2.6-RL-oss，固定 revision `639865fd3374018d6cb29b9fb82dd531406fcf5f`。已盘点的 Code Parquet 有2698个独立任务；本轮选择源 row243 的 `format-code-task-002549`，涉及 Python Result 的 `unwrap_or_raise`。不是把2698行全部送入训练。

| 计量 | 本轮实际值 |
| --- | --- |
| 独立训练题目 / Parquet行 | 1 / 1 |
| 被训练消费的完整轨迹 | 4，四个唯一TQ key |
| 新 optimizer 更新 | 1：绝对step4→5 |
| 有效组奖励 | `[0, 1, 1, 0]` |
| 消费组模型生成调用 | 100：25+36+31+8 |
| 消费组模型输出token | 37,798：9130+13219+11093+4356 |
| 工具/context token | 35,425 |
| 展开轨迹总token（含四份prompt） | 79,047，W&B计量一致 |
| 已准入但未消费的预取轨迹 | 3，不计入训练样本 |
| 所属job / 已清理sandbox | 12 / 23，不当作12个训练题目 |
| Heldout能力评估 | 未运行 |

历史001661已完成另一 Code 任务的工程验收，是本次C4的来源；不能并入本轮样本数。Cyber、General、Visual/Webdev、Music在本链路仍未取得实际训练验收。最初HTTP524失败被严格拒绝，未伪造为reward0或消费样本；其失败记录保留。

独立grader先以原生产Python3.10.18执行 baseline/restored/public-candidate 校准，奖励0/0/1。这是验证评分器，不是模型训练轨迹。训练的0/1来自实际独立执行测试。

## 算法与实际链路

MiMo任务prompt/环境元数据 → Harbor任务打包 → Modal上的固定DSH执行多轮工具交互 → Uni-Agent Gateway调用双卡vLLM并记录轨迹 → 独立verifier运行任务测试 → TransferQueue → VERL GRPO → 原生C5及W&B/RL-Insight。

模型是 MiMo-V2.6-Distill-Qwen-9B，revision `2367e865d009c13ac81713a2878291d33ab28177`。DSH固定 `b2369692ea530007075ebcd18d39fdba0bbd3982`、SDK/runtime 0.1.3a2、sdk-minimal，任务派生镜像digest951f488e。它是用DSH/Harbor/Modal适配的Code实现，不是原样运行MiMo的mimoagent/K8s/Megatron五域配方。

每题采样n=4，以组内奖励均值/标准差形成优势。当前均值0.5、优势约±0.866024；使用clip=0.2的策略目标及token-mean聚合，工具返回对应token不作为模型动作学习。仅更新LoRA，基础权重冻结；本轮不是OPD/teacher蒸馏。

## 实际参数（由本run W&B config重读）

| 项目 | 本轮实际参数 |
| --- | --- |
| GPU / 拓扑 | 2×RTX PRO6000 Blackwell 96GB，单节点 |
| trainer | colocate_async，world2，FSDP1 |
| rollout | 两个TP1副本共享actor双卡，n=4、sessions=2 |
| 训练适配 | LoRA rank16 / alpha32，gradient checkpointing、SDPA |
| optimizer | AdamW、lr=1e-6、ppo_epochs=1、mini_batch=1 |
| 策略目标 | GRPO，clip_low/high=0.2/0.2，token-mean |
| KL / entropy | use_kl_loss=false、use_kl_in_reward=false、entropy_coeff=0 |
| 采样 | temperature=1、top_p=1、top_k=-1、seed42 |
| 上下文 / prompt / response上限 | 32768 / 2048 / 30720 |
| 模型生成预算 / 单次请求上限 | 每trajectory20480 / 每请求4096 |
| vLLM | gpu_memory_utilization=0.4、max_num_seqs=2、prefill8192、eager |
| 内存策略 | actor parameter/optimizer CPU offload；naive本机权重传递 |
| 任务沙盒 | CPU2、memory4096MB、wall1800秒 |
| 完成终点 | 从C4恢复；absolute total_training_steps=5；save_freq=1 |
| 验证 | test_freq=-1、val_before_train=false；没有heldout分数 |

`total_training_steps=5`与`total_epochs=5`包含恢复的绝对计数，不表示本轮完成五次更新或新任务训练五轮。环境目录的ws1是历史名字；实际训练是world2。上下文仍为32K，没有切到64K。

## 实际脚本与冻结身份

- 训练基础配置：`examples/harbor_opd_rl/base.yaml`；双卡覆盖配置：`examples/mimo_dsh_rl/mimo-9b-dual-colocate-observed.yaml`。
- 控制/准入：独立冻结 `audit-code/r21-operator-runtime/mimo_r20_operator.py`，来自commit b053bde；`supervise`启动原生进程。
- 原生入口：`examples.harbor_opd_rl.launch`，启用observability wrapper并传token journal、parent C4、absolute target5/save1。
- 固定训练源码：`/workspace/mimo-dsh-rl-20260928/run-src-r20`，source1ccc164、1003文件manifest99ac03f5；不是本地最新HEAD整树。
- uv Python：`/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python`；273依赖及CuPy/NCCL overlay已核验。

完整已执行命令见[实际preflight的command](evidence/r21-r20f-preflight.json)，当时私有run-spec/launch/凭据与固定deadline已绑定。不要把记录中的过期授权命令当作新的启动指令。

## 时间与W&B反馈

以下均为新加坡时间2026-10-01：原生监督进程03:33:02→04:23:18，共50分16秒（包含模型初始化/恢复）；ready-to-fit为03:57:34，至结束约25分44秒。六小时02:04:33→08:04:33是Pod分配窗口，完成后没有自动接续更多任务，不能描述为训练了六小时。现在Runpod API为EXITED。

| W&B指标 | 本轮结果 |
| --- | --- |
| state / native history rows / step | finished / 1 / 5 |
| reward mean / min / max | 0.5 / 0 / 1 |
| advantage min / max | -0.8660239 / +0.8660239 |
| actor grad norm / pg loss | 0.1611328 / -0.2480442 |
| actor lr | 1e-6 |
| response aborted ratio | 0 |
| rollout失败evicted_samples | 1；严格失败另存，不隐去 |
| rollout/actor logprob相关系数 | 0.9989936；不是独立model-forward重算证明 |
| 单有效step计时 | 1420.32秒 ≈23分40秒 |
| gen / old_log_prob / update_actor | 1244.60 / 58.27 / 75.89秒 |
| save_checkpoint / update_weights | 31.26 / 10.09秒 |

W&B77/77原生指标与实际console一致，审计没有写回/补写历史。本轮只有一个有效step的数据点，不能展示学习曲线或推断收敛。

## 完成证明与限制

[联合验收](evidence/r20f-current-joint-acceptance.json)19项全部通过；root再次对本地20个归档引用SHA、独立审计源码/测试SHA逐项核验，并重新读取在线W&B finished/实际config/summary。

1. 两个rank原生日志分别证明C4 model/optimizer/RNG/scheduler成功加载；当前native next-batch probe与实际四个job都绑定新002549。
2. 四唯一TQ真实消费且全部generation版本为policy4；四session token IDs/mask/有限logprob与NPZ一致。
3. 非恒定奖励、有正负advantage、有限非零梯度；496/716 LoRA张量改变，760个base张量不变；两个rank optimizer4→5、各992个moment张量变化。
4. C5十五个文件共19,151,369,958字节完整SHA验证，world2/FSDP1/latest5；训练exit0。
5. W&B finished、77项对账；RL-Insight当前三scalar实际Prom scrape与限定窗口Tempo154 traces（其中三类root payload各回读一份）。
6. 23个所属Modal sandbox fresh API终态active0；所属controller/Ray/端口/key已清理；现在GPU Pod EXITED。

旧world2审计只接受父spec SHA前缀，遇到合法裸SHA报FAIL。独立新离线审计仅修复这一个表示合同，181项云CPU回归/覆盖98.68%通过，再对同一C4/C5实物全hash审计通过。旧父manifest、训练源码、checkpoint和旧FAIL未改。

C5位于 `/workspace/mimo-dsh-rl-20260928/runs/r20f/rl-training/checkpoints/global_step_5`。本轮证明从C4恢复并完成新有效更新；未再启动新run重载C5，也未执行完整数据/五域/heldout能力实验。下一阶段应先明确多任务规模与更新数，并在终态后明确继续训练或回收策略，避免用六小时资源窗口代替训练完成标准。
