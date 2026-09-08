# Context v2 train-r1：消费、参数与动量 CPU 审计

2026-09-09。本次仅审计 `context-v2-train-r1`，显式 `CUDA_VISIBLE_DEVICES=''`、OMP/MKL线程2，未启动GPU、未改checkout、未读取其他任务产物。原生训练已595.014秒exit0；本报告不替代独立reload。

运行清单实际源码 `a9c7b0a155da9b8d29da3d4d46a7c337156a54f3`，VERL `fefb080262e1c015a0ea05f958822a6a512dc795`。实际运行根 `/root/runs/context-v2-train-r1`；checkpoint根 `/workspace/uni-agent-g1/checkpoint/context-v2-train-r1`。CPU审计输出在该run的 `audit-cpu-r1/`，对应JSON已逐字节回传本worktree。

## 消费与身份

复用 `examples/dsh/ops/audit_qwen3_4b_online_rl.py`：整体 eligible=true，14/14 groups均 eligible-and-consumed，0拒绝、0缺失消费、0意外消费、0旧版不可关联文件。包括2个训练组（各n=4）和12个验证组（step0/1/2各4题、n=1）。检查覆盖NPZ字节摘要、真实token/logprob/mask、Gateway/DSH身份、原trace/artifact/receipt摘要、新鲜eligible奖励，以及实际trainer输出中的TQ消费键。

| 实际步骤 | task ID | 同题4次reward（session序） | model tokens合计 | 有效任务信号 |
| --- | --- | --- | ---: | --- |
| step1 | `dsh/context-v2/train-M1` | `[1,1,0.1,1]` | 1816 | 有：奖励差异、非零advantage及梯度 |
| step2 | `dsh/context-v2/train-C3` | `[0.1,0.1,0.1,0.1]` | 862 | 无新增reward学习信号：advantage和梯度均0 |

两个task是12条可用课程中实际消费的两题，不能写成12题全部训练。train-M1是“当前权威配置缺字段，历史有诱饵值，需正确弃答并完整引用”；train-C3是“范围错误/已弃用/当前有效来源的多重冲突”。

step1 group `f6ceb7b1-8951-4e1b-a676-8bf73fb6aaad`，step2 group `86ef257e-f98d-4f4b-81ca-bdffb699d395`；每组四个不同Gateway session/receipt与TQ key，详见 consumed-task-summary JSON。`model_token_count`是生成mask中的模型token数量，不能与含工具内容的response长度混用。

## 梯度、checkpoint 与optimizer

原始metrics固定路径 `/workspace/rebuild/uni-agent-native-n0-r1/dsh-context-v2/context-v2-train-r1.jsonl`，摘要见 consumed-task-summary。

- step1：`pg_loss=-0.3535234630`，`grad_norm=0.267578125`，advantage范围约`[-1.4999965,0.4999989]`；reward均值0.775。这一组证明本次真实online GRPO产生并消费非零任务奖励梯度。
- step2：pg_loss、grad_norm、advantage min/max/mean全部0；四条reward都是0.1。
- 复用 `checkpoint_delta.py` 比较global_step1→2的全部903个tensor：504个LoRA tensor中252变化；399个base tensor全部不变；全部finite。该比较证明两checkpoint间更新/冻结事实，不是initial→final独立比较。
- 复用 `optimizer_delta.py`：optimizer step 1→2，504个active state、37个empty state，全部finite；252个moment tensor变化，两个checkpoint均有504个非零moment tensor。
- 额外CPU动量诊断：对全部504个一阶moment逐张量，step2精确等于step1×0.9；全部504个二阶moment精确等于step1×0.999（bfloat16运算）。两类最大残差均0。AdamW weight_decay=0.01。

因此step2的252个LoRA变化与已有动量/weight decay继续作用一致；不能把它解释为第二个非零任务学习步骤。第一步的真实梯度证据与第二步的状态延续分别保留。

## 当前效果边界

step0、step1、step2各4条dev验证的reward均值均0.255，严格准确率均0。该工程训练已产生真实任务梯度和checkpoint，但目前没有dev能力提升证据。独立reload与其新回执由主线程另外验收；本报告不预判reload结果，也不宣称完成多context、跨会话记忆或RSI训练。

## 审计产物

- `context-v2-train-r1-trajectory-groups.json`：原生严格消费审计。
- `context-v2-train-r1-consumed-task-summary.json`：task/session/TQ/token/receipt绑定及关键metrics。
- `context-v2-train-r1-checkpoint-delta.json`：903个tensor逐项差异及两份9GB权重文件摘要。
- `context-v2-train-r1-optimizer-delta.json`：optimizer结构、步数、moment差异及文件摘要。
- `context-v2-train-r1-momentum-diagnostic.json`：零梯度动量衰减的精确数值证据。

复用检查命令为原生trajectory audit的 `RUN --output ...`、checkpoint/optimizer checker的 `before after --output ...`；每项均退出0，输出文件以新文件方式保存。原始checkpoint和训练回执未修改。
