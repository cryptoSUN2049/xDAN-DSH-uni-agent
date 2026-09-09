# 短课程到多文件课程：warm-start 只读审计

2026-09-09。本轮仅检查本地固定源码并写此文档，未修改实现、未启动 GPU、未验证新的训练作业。结论是**底层具备 adapter 初始化能力，但当前准备器没有可审计的跨课程入口，不能称已可执行**。

## 目标与现状

`work-state-short-fact-v1` 已完成真实更新、checkpoint 和独立 reload，证明阶段一工程与学习信号链路；原 `work-state-v1` 的 WS01/WS03/WS05/WS06 r4 仍是零任务梯度、零参数更新。二者保持独立实验身份。

最短延伸是在既有多文件任务上验证短课程策略是否迁移，再决定有界继续训练。不能重复短课程、仅换事实值或降低原任务评分门，借此宣称完整记忆/context 能力通过。长期目标仍包含 goal/tasks/handoff/memory、索引、offload、真实 compact 和长任务恢复；跨课程成功也只增加 C1 证据。

## 代码证据

以下路径相对仓库根；行号为本次审计时位置。

| 代码 | 实际行为与含义 |
| --- | --- |
| `examples/dsh/capabilities/prepare_memory_training.py:249–265` | `resume_from`、`mother_run` 仅允许 `mode=reload`；train 传入会直接拒绝。 |
| 同文件 `:59–60` | 母实验 course 必须等于目标 course；short checkpoint 不能直接作为原四族 reload 母实验。此保护应保留。 |
| 同文件 `:294–310` | 只有 reload 构造 checkpoint origin；没有独立初始化谱系。 |
| 同文件 `:361–362,460–466` | origin 映射到 `resume_path`，并强制 val-only，加载 model/optimizer/extra。 |
| 同文件 `:607–640` | check 重验母工件、同 course 和 reload-only 参数；不是可以靠改一处 mode 开启的训练能力。 |
| 同文件 `:408` | checkpoint identity 在无 origin 时退回 base revision；新增初始化必须绑定真实父 adapter 身份。 |
| 同文件 `:703–709` | CLI 只有 course/mode/resume/mother/evaluation task 等参数，没有 init-adapter 参数。 |
| `examples/dsh/train_qwen3_4b_online_rl.sh:115–117` | 真实入口使用 VERL v1 trainer。 |
| `verl/verl/workers/engine/fsdp/transformer_impl.py:323–333` | 存在 `model.lora_adapter_path` 时调用 `PeftModel.from_pretrained(..., is_trainable=True)`，是真正加载已有 LoRA 的底层路径。 |
| `verl/verl/workers/engine/fsdp/transformer_impl.py:143` | LoRA 使用条件依赖正的 lora_rank；新入口须保持 rank/alpha/目标模块与父 adapter 一致。 |
| `verl/verl/trainer/ppo/v1/trainer_base.py:793–839` | resume 除加载 actor 外还恢复 global step 和 dataloader state；load_contents 改成 model-only 也不会自动清除这些状态。 |
| `verl/verl/model_merger/base_model_merger.py:311–398` | 可从 checkpoint state_dict 导出 `lora_adapter/adapter_config.json` 与 `adapter_model.safetensors`；从 lora_train_meta 取 rank/alpha。缺 alpha 时回落到 0 并警告，必须拒绝这种导出结果。 |

## 初始化与 resume 的边界

跨课程 warm-start 应是：原锁定 base + 短课程已训练 adapter → 新 run、新课程数据、新 optimizer、新 scheduler、global step 从 0 开始、新 dataloader；`trainer.resume_mode=disable`。父实验只提供策略参数和可追溯来源。原 short optimizer/动量、随机数状态、样本消费游标不能默默进入新课程。

resume 则是继续原实验状态。当前 reload 为独立验证完整母 checkpoint 而使用 resume，符合已有合同。不能将 `resume_path + load_contents=[model]` 当作上述 warm-start，也不能删除同 course 保护或手改生成 manifest 来绕过校验。

## 最小后续设计

1. 为 prepare/check 新增独立初始化参数及版本化 `initialization-origin`。明确 source course 与 target course 分开；固定父 run、step、集成源码、有效 VERL、base revision、runtime、父工件摘要及导出 adapter 摘要。原 checkpoint-origin/reload 合同保持不变。
2. 在新目录导出 adapter，父 checkpoint 全量摘要前后相同；验证 504 个 LoRA tensor 的键归一、shape、dtype、逐项数值相等及 finite，rank=16、alpha=16、目标模块和 base 身份匹配。不得只看文件存在或 LoRA_B 非零。
3. 将 `actor_rollout_ref.model.lora_adapter_path` 写入可校验 command；保持 resume disable、初始 step=0、fresh optimizer/dataloader，并将实际初始策略身份写入 framework/operator 谱系。
4. 同一初始化合同支持独立 val 与 train，才能先评估迁移再训练。评估应对原四族逐题隔离，保留 WS06 max-tokens 等原始拒绝结果；不可拿 short 的 901/902 成功替代原多文件恢复任务。
5. 训练仍用现有独立评估、有界步数、完整同策略 n4、原奖励和严格消费审计；本课程新增任务非零优势→有限梯度→实际参数更新独立验收。父 adapter 已非零本身不是本课程学习证据。

## 验证要求与迁移实验

- CPU 合同测试：train/val 初始化参数可用；init 与 resume 互斥；跨 course 只经初始化；错误父身份、缺文件、symlink、摘要漂移、rank/alpha 不匹配、输出覆盖父工件均拒绝；旧 reload 和无初始化训练回归。
- 配置检查：实际 resolved config 含指定 adapter、resume disable；从父 step8 初始化仍从新 step0 开始，optimizer 无历史 moments，dataloader 从目标数据开始。
- 首次真实加载：actor 初始 LoRA 与导出逐项相等；在首次采样前确认 rollout 同步的是该策略，Gateway 版本/回执/消费身份匹配。日志声称加载不能代替参数证据。
- 预先固定目标题、种子、预算和评分版本，用同一当前执行器比较 base 与 short-adapter 的原四族表现。历史 r4 可用于诊断背景；如果执行器/预算/采样不同，不能充当严格匹配对照。公开 dev 可作迁移诊断，不能叫封存泛化。
- 首轮报告每族合法低分、拒绝、索引读取、事实恢复、配置/计划成功和总成本。若全部组同分，不能机械重复 r4 八步；根据失败的真实阶段设计新版递进多文件课程，例如逐项增加文件数/索引选择/更新冲突，保留原四族作为目标评估，且不改旧结果。
- 迁移诊断与有界继续训练后，重新 checkpoint、独立 fresh reload，并对照训练前目标任务表现；这才回答“short 是否帮助更复杂恢复”，而非只证明又跑了一次链路。

## 已有底层命令与缺失的最终入口

源码提供的导出命令如下，**本轮未执行；需在固定环境核验 metadata 和产物，且会另外保存一份 HF base，占用磁盘与 CPU 内存**：

```bash
"$PYTHON_BIN" -m verl.model_merger merge \
  --backend fsdp \
  --local_dir /workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_8/actor \
  --target_dir /workspace/uni-agent-g1/exports/ws-short-step8-transfer-r1
```

底层配置键为 `actor_rollout_ref.model.lora_adapter_path=/workspace/uni-agent-g1/exports/ws-short-step8-transfer-r1/lora_adapter`，配合 `trainer.resume_mode=disable`。这只是已有能力定位，**不是已完成的项目训练命令**。目前没有合法的 `prepare_memory_training prepare --mode train` 参数组合能同时绑定这个 adapter、父谱系和目标 course。新增入口、审计与测试完成前，不应手工直启 GPU 或宣称跨课程训练已准备好。

## 远程现有工件核实（2026-09-09）

实际检查 `/workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_8/actor`：存在 `lora_train_meta.json`，内容为 `r=16`、`lora_alpha=16`、`task_type=CAUSAL_LM`；`fsdp_config.json` 声明 FSDP_version=1、world_size=1。模型 shard 为 8,889,735,011 字节，optimizer 为 132,552,363 字节。当前目录没有现成 `adapter_model.safetensors` 或 `adapter_config.json`；不能把 actor 目录直接当作 PEFT adapter 路径。此次仅查看文件清单和两个非凭据元数据，没有转换权重或改写母 checkpoint。元数据存在消除了本工件缺失 alpha 的疑问，但不替代未来导出与逐 tensor 等同性验收。
