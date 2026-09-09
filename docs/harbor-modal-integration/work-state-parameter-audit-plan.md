# Work-state 8步训练：参数、optimizer与独立reload证据

只读设计与现成脚本推荐，未启动GPU、未执行训练/审计。以下以计划中的 `work-state-train-r2` 为例，实际run名字不同只改RUN_ID；必须等待真实checkpoint保存且训练结束再读取，避免审计仍在写入的文件。

## 直接复用现有CPU脚本

`deployment/checks/checkpoint_delta.py` 是通用的本项目单卡LoRA完整state-dict比较器，不绑定context/M1任务。`deployment/checks/optimizer_delta.py` 是本项目已验证单卡AdamW状态审计器。当前recipe相同Qwen3-4B、LoRA16、save_lora_only=False，预计504个LoRA张量+399个base张量；计数仍应实测，变化需查架构/保存格式，不硬改报告凑数。

```bash
set -euo pipefail
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
export CUDA_VISIBLE_DEVICES=''
RUN_ID=work-state-train-r2
RUN=/root/runs/$RUN_ID
MANIFEST=/root/runs/$RUN_ID-data/manifest.json
PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
REPO="$($PYTHON_BIN -c 'import json,sys;print(json.load(open(sys.argv[1]))["repository_root"])' "$MANIFEST")"
CK=/workspace/uni-agent-g1/checkpoint/$RUN_ID
AUD=$RUN/parameter-audit-4-8
mkdir -m 700 "$AUD"
cd "$REPO"
export PYTHONPATH="$REPO:$REPO/verl"
export CUDA_VISIBLE_DEVICES=''
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF

$PYTHON_BIN deployment/checks/checkpoint_delta.py \
 "$CK/global_step_4/actor/model_world_size_1_rank_0.pt" \
 "$CK/global_step_8/actor/model_world_size_1_rank_0.pt" \
 --output "$AUD/checkpoint-delta-4-8.json"

$PYTHON_BIN deployment/checks/optimizer_delta.py \
 "$CK/global_step_4/actor/optim_world_size_1_rank_0.pt" \
 "$CK/global_step_8/actor/optim_world_size_1_rank_0.pt" \
 --output "$AUD/optimizer-delta-4-8.json"

$PYTHON_BIN -m examples.dsh.capabilities.audit_memory_training "$RUN" \
 --memory-root "$RUN/chains" --run-id "$RUN_ID" \
 --output "$AUD/memory-consumption.json"
```

`AUD`必须新目录；上述两delta脚本用exclusive输出，不覆盖原报告。只读取自己训练生成的可信checkpoint，`map_location=cpu/weights_only=True`；不对未知权重文件放宽pickle加载。消费审计器当前output可覆盖，所以目录的新建要求也保护它。脚本退出非0时保存原结果并查原因，不能改passed。

## 必须联合解释的证据

| 证据 | 位置/字段 | 能证明什么 |
|---|---|---|
| 实际运行配置 | `<run>/memory-launch-plan.json`、`run-manifest.json`、`supervision/train.log` | 实际source/参数/状态；固定脚本actor lr=1e-5、use_kl_loss=False、entropy_coeff=0、algorithm.use_kl_in_reward=False，仍核真实配置无override |
| 真实消费 | `<run>/rollouts/**/*.jsonl`、`validation/**/*.jsonl`及memory-consumption.json | n4同任务完整组、A后B真实TQ keys、没有重复/未知/未准入消费；不能只数session目录 |
| 奖励与优势 | `<repo>/dsh-work-state/<EXP_NAME>.jsonl`和上述消费/chain receipts | 各训练step终态B四个奖励、GRPO advantage范围/分布、实际组UID/任务ID |
| 梯度 | 同一metrics JSONL的actor grad_norm与pg_loss、advantage指标 | 有限非零梯度配合同step真实任务优势，才是新任务学习信号；pg_loss标量可以为0但梯度非0，不硬要求pg_loss!=0 |
| 模型差异 | checkpoint-delta-4-8.json | 4→8至少一个adapter变化、base不变、全数值finite；before/after各文件路径与SHA |
| optimizer | optimizer-delta-4-8.json | step推进、状态拓扑/形状/数值合法、非零moment及changed_moment_tensors；并非独立新学习证明 |
| 保存物 | global_step_4/8 的model、optim、extra_state及data.pt | 可供恢复的文件；存在不等于已独立加载 |

特别注意optimizer审计现有`passed`不要求changed_moment_tensors>0，也不识别梯度由何种loss产生。应原样保留passed并单独报告该计数及梯度证据。不能把optimizer step推进直接称为能力提升。

默认AdamW weight_decay=0.01。即使当前组全同分→优势/新任务梯度为0，已有exp_avg/exp_avg_sq会继续衰减并驱动权重变化；旧context两步实验已观察到零梯度step的moment恰好按0.9/0.999衰减。该旧JSON是反例证据，不是本课程新结果；不复制它作为新审计。4→8跨四次更新，仅末态差异无法唯一反推出每步梯度，BF16下也不能简单用一次beta^4计算声称精确证明。

本课程**有效更新**的短判据：5–8区间至少一实际完整n4组具有真实终态B奖励方差、非零任务优势、有限非零actor梯度；同期4→8模型adapter变且base不变、optimizer合法推进。原始阶段reward保持原样，必须按固定VERL最后B奖励做判断，不把A的质量分或两stage分数混算成n4方差。

源码依据：固定VERL `fefb080262e1c015a0ea05f958822a6a512dc795` 的 `verl/verl/trainer/ppo/v1/utils.py:148`，`compute_advantage_for_multi_trajectories` 对同uid/session sibling取最后index的B轨迹计算GRPO，再向该链A/B广播。A原reward=0、B=1不构成两个独立采样的奖励差异，也不需要改写A的原receipt/reward；有效方差必须来自同一任务四条链的四个终态B奖励之间。

## 是否需要step0

当前save4/8足以验证5–8区间，不必先加新trainer保存step0才能启动工程验证。基座HF文件与FSDP+LoRA checkpoint键/初始化状态不同，不能直接把它们传给checkpoint_delta当step0对照，也不能重新随机初始化LoRA后冒充原始参数。

若真实非零学习信号只在1–4，而5–8全零，分别报告“早段有任务梯度”和“后段参数变化可能含动量/衰减”。现有4→8对比无法单独量化1–4的参数净变化；不要补造step0证据。下一独立run可在批准且记录的新recipe中提高保存频率，或补真实初始化快照，但不修改已完成母实验。全8步零优势则不能宣称有效任务学习，即使有checkpoint或weight变化。

## 独立reload最短证据

训练完成/审计后，用已有准备器 `--family work-state-v1 --mode reload --resume-from "$CK/global_step_8" --mother-run "$RUN"`，其余原必需参数相同，新run/data独立；随后原 `check`/`launch`。完整参数格式见 [reload设计](native-memory-reload-design.md)。reload清单的checkpoint-origin streaming SHA记录母source、母run和实际checkpoint身份，不能继续只标base revision。

保存实际load日志：Resuming step8、model/optimizer/RNG/lr_scheduler对应真实文件。sync初始化发布weight8；4个fresh dev链的真实generation版本应为8，不是train step8采样的weight7。使用新run上的同一个memory消费审计命令；确认4个val sibling1、无train消费、无update指标/新model checkpoint；母checkpoint前后SHA不变。

报告fresh dev四题每题reward/严格成功率与总成本，和母训练step8 dev对照。数值波动允许，不能将“独立重新执行”误称逐token完全复现；公开variant1 dev已用于课程开发，不是封存泛化验证。以上原始证据连同8/4实际任务覆盖归档`/workspace/reports/`并记录SHA，checkpoint留在`/workspace/uni-agent-g1/checkpoint/`。

## r3 补充：学习信号仅出现在1–4步时如何验收

2026-09-09只读核实，未修改运行中的r3。**不用为了覆盖5–8区间重新制造非零梯度，也不必先补存step0才能证明本课程有参数更新。** 当前4→8模型差分只能证明后半段权重变化；配合1–4真实消费组的B奖励方差/非零优势/有限非零梯度、成功optimizer step，可以报告“本课程存在任务梯度和实际参数更新”。不能据此说5–8有新学习，或已量化1–4净增量。

更强且成本很低的现有证据是**确定为零的LoRA B初始化**（此B指LoRA矩阵，不是reader阶段）：

- 固定VERL `workers/engine/fsdp/transformer_impl.py:322–349` 区分加载已有adapter与新建分支；新建 `LoraConfig` 没有覆盖`init_lora_weights`。
- 已通过只读SSH直接读取既有venv源码，无模型导入。实际PEFT版本`0.19.1`与固定uv.lock一致；`peft/tuners/lora/config.py:513–523` 默认`init_lora_weights=True`；`layer.py:263–274` 在线性LoRA上执行随机初始化A、严格置零B。embedding分支相反，不能套用该结论；本课程需核checkpoint键确为目标linear层`lora_B.*.weight`。
- 两文件SHA256：config `a9f95e1a143b8320cf2e0a3139f29c807d937876591f5fc1ce24fc4fd7833b59`；layer `444bba0e5dbc5c55ed51a288a8366c18aa7ebe533d081312a19347eb48b215b6`。实际读取路径均在`/workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/`下。

最短补证：课程结束后，CPU读取原step4/8完整state dict，记录每个linear LoRA B的有限性、非零元素数/范数和checkpoint SHA；同时核实际run `resume_mode=disable`、`lora_adapter_path=null`、没有另外加载adapter/optimizer或覆盖初始化。**零初始化B+fresh零优化器状态，仅靠AdamW weight decay或零梯度动量不可能从0变非0。** 因而step4已非零B可证明前半段确有梯度驱动参数改变；step8仍非零B则证明最终保存了非零adapter参数。不需要重建随机A或伪造step0。

若要求“非零有效基座权重增量”而不只参数变化，可另在CPU核`(alpha/r)·BA`非零；B非零本身不在数学上保证BA非零。能力提升仍需fresh评估，不能从矩阵范数推断。

还需同run的可核验训练日志：实际被消费的完整n4链与末B奖励、非零advantages、有限非零actor/grad_norm、非零学习率、无跳过更新；本recipe显式`use_kl_loss=False`和`entropy_coeff=0`，应以resolved配置确认，避免把正则项梯度说成任务学习。FSDP `optimizer_step():797–803` 非有限梯度会跳过，单条grad_norm日志不能单独证明step被执行。

现脚本的证据边界保持不变：`checkpoint_delta.py`只判adapter差异+base不变+有限；`optimizer_delta.py`只判step推进、状态合法、已有moments非零，**不要求changed_moment_tensors>0，也不区分新梯度与旧moment衰减**。报告应另读取实际param_groups的lr/betas/weight_decay，不用默认值冒充run参数。5–8若原始指标全零，即使4→8差分或moment变化通过，也只记“optimizer继续推进及历史动量/衰减可解释变化”。

若B在4/8均为0、初始化/续训来源无法确认、或非零梯度缺乏实际消费与optimizer证据，就保留结论缺口；最小后续是在**新run**增加一次真实初始或更早checkpoint，不改旧run、不延伸成新框架。当前只是补充验收方法，不声称r3已经产出上述成功证据。
