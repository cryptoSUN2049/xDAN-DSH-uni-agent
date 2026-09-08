# T2：真实 DSH 示范 → LoRA SFT → 现有 GRPO

状态：设计，未实现本页新增文件，未运行 SFT。核查基于 Uni-Agent `da24cfaecc772d551c44c7386a8772f786d2a55f`、仓内 VERL `fefb080262e1c015a0ea05f958822a6a512dc795`、DSH `b2369692ea530007075ebcd18d39fdba0bbd3982` / `0.1.3a2`。新增业务 prompt 采集字段须按采集时实际源码 SHA 另行锁定。

## 目标与架构

当 T1/T2 学生基线缺少成功探索时，先让固定 Qwen3-4B 学习经真实 DSH 执行、严格 verifier 通过的人工脚本示范，再独立测量任务成功率；取得成功探索后回到当前 GRPO。脚本产生 assistant 决策，DSH 产生工具执行和观测；这是人工行为策略的离线 SFT，不能登记为学生 on-policy 数据、教师概率蒸馏或 RL 成功。

首批沿用单张 GPU、固定 Qwen3-4B revision `1cfa9a7208912126459214e8b04321603b3df60c`、LoRA rank/alpha `16/16`、`all-linear`。训练与现有 GPU baseline 串行，不同时启动 rollout 引擎。此配置是待验证候选，未证明这批序列的峰值显存。

```mermaid
flowchart LR
  A[业务 prompt + public train fixture] --> B[ScriptedPolicy 驱动真实 DSH]
  B --> C[requests.json + events.jsonl + report]
  C --> D[身份与 verifier 核验]
  D --> E[逐 request decision Parquet]
  E --> F[目标 assistant mask + 固定 Qwen3 tokenizer]
  F --> G[原生 VERL SFT / FSDP / LoRA]
  G --> H[原生 model_merger 导出 adapter]
  H --> I[原基座 + adapter 新建 GRPO run]
  I --> J[先独立 eval 再 GRPO / 原生 RL checkpoint reload]
```

## 已有入口与新增文件

已有：`deployment/checks/dsh_log_tool_smoke.py` 保存真实请求和 SDK events，`examples/dsh/capability_tasks/log_tool/verifier.py` 判断公开业务与生命周期，`oracle.py` 计算独立业务答案；现有 task bundle 和 GRPO launcher 保留。

| 拟新增文件 | 最小职责 |
|---|---|
| `examples/dsh/capability_tasks/log_tool/prepare_sft_dataset.py` | 验收真实示范 artifacts，关联逐请求目标，发布不覆盖的 train/dev Parquet 与 provenance manifest |
| `examples/dsh/capability_tasks/log_tool/sft_dataset.py` | `DshDecisionSFTDataset`：固定 tokenizer 渲染、严格 prefix/EOS 校验、仅目标 assistant loss mask |
| `examples/dsh/ops/train_t2_lora_sft.sh` | 固定版本和单卡参数检查，调用原生 VERL SFT，记录解析后的配置及退出码 |
| 对应 `tests/uni_agent/examples/test_log_tool_sft_*.py` | 来源、逐步 schema、目标关联、split、token/mask 合同负例 |

现有采集器的显式业务 prompt / hash 增量由独立批次负责。adapter 接入现有 GRPO 可先使用 CLI override，无需第二套 trainer。默认不修改 VERL 子模块、DSH 源码或引入 ms-swift。

## 示范准入与目标关联

1. 重新真实采集带业务要求和输入来源的 prompt。历史 `Execute the scripted-policy integration smoke...` 轨迹仍是工程 smoke；不能事后替换其 prompt，再称原始业务示范。新采集须核对 `initial_prompt` 原文及 hash。
2. 每个 case 验证完整 Session 的 `completed`、严格 verifier `passed=true`、同一 session/runtime/fixture/tool-code 身份、原始 events/request/report 字节 hash；在发布 manifest 记录采集器源码 SHA、固定 wheel hashes、verifier/oracle bundle、初始 prompt hash。现有报告未提供的可信部署身份由已锁定部署 manifest 绑定，缺失时拒绝发布，不填猜测值。
3. `requests.json[k]` 是 DSH 在第 k 次调用前实际发送的 `messages` 和 `tools`。每条 row 必须保留当次工具 schema。注册后出现候选、撤销后消失；不能用全局最后一份 schema 覆盖整个 Session。
4. 目标只能来自真实 `assistant/message`，用 Session turn/step/seq、顺序、tool-call IDs/arguments 与请求历史交叉核对。下一 request 中新追加的 assistant 是可交叉核验视图；最后响应从完整 events 获取。不得调用 `ScriptedPolicy.respond()` 或重放源代码生成 target。
5. 请求不是响应，不能将 `requests[k+1]` 整体作为第 k 条 target。核对下一历史保留当前历史，并包含同一 assistant/tool-result 关联；有额外 steering、重试或上下文编辑时，按已有 Session v2 消费逻辑证明对应关系，无法唯一关联则拒绝。
6. SDK v2 `tool/result` 是 user-role `tool-result` 块，具有 `source.callId` 与 `toolCallId`；目标在 `assistant/message`，不可把工具输出转成 assistant。来源事件唯一、有序且 hash 完整；成功目标限定完整 stop/tool-calls 响应，无失败 attempt、max-tokens 或 abort。完整任务通过仍不能替代逐目标结构核验。
7. HTTP provider 表示与 SFT 表示分开：原始请求不改；转换器保留 system/user/assistant/tool 语义，按现有 adapter 的无损规范整理 `tool_calls.function.arguments` 的 JSON 表示。仅支持首轮 text/tool-call；不静默丢弃图像或未支持块。

固定 DSH 已有 `scripts/trace-training/export.ts` / `converter.ts`，后者的 `requestBefore()` 与 `sftRecords()` 可参考/复用真实 request-before-response 语义；其 `dsh.sft.v1` 指定 `lossScope=assistant-message`。但 CLI `parseLogicalSession()` 要求带 Session 格式 header 的原生持久化文件，当前 SDK helper 的 `events.jsonl` 是逻辑事件列表，不能直接喂进去或伪造 header。首批优先真实 `requests.json` 加既有 v2 消费器，不引入额外 DSH Node 构建依赖。

## Decision row 与数据类合同

Parquet 每条 row 为一次决策，建议最小字段如下；嵌套 JSON 可用确定性 JSON 字符串存储，避免混合 tool arguments 引起 Arrow 类型推断改变语义。

```text
schema = "dsh.t2-sft-decision.v1"
sample_id, case_id, split, session_id, request_index
request_json = {messages: [...], tools: [...] | null}
target_json = {role: "assistant", content: ..., tool_calls?: [...]}
enable_thinking = false
provenance_json = {
  trace_sha256, requests_sha256, report_sha256, fixture_sha256,
  assistant_event_seq, turn, step, tool_call_ids,
  initial_prompt_sha256, runtime_identity, collector_commit,
  verifier_bundle_sha256, tokenizer_revision
}
```

`request_json` / `target_json` 为已验证规范视图，manifest 同时绑定未修改的原始 artifacts。route 中原有 `deepseek-v4-pro` 是脚本服务器沿用的协议标签，不是教师模型调用，也不是 learner 模型；学习 tokenizer 始终是固定 Qwen3-4B。

```python
class DshDecisionSFTDataset:
    def __init__(self, parquet_files, tokenizer, config,
                 processor=None, max_samples=-1): ...
    def __len__(self): ...
    def __getitem__(self, index):
        # 均为一维 torch.long，N 为完整未截断序列长度。
        return {
            "input_ids": tensor_of_length_N,
            "position_ids": torch.arange(N, dtype=torch.long),
            "loss_mask": target_only_mask_of_length_N,
        }
```

使用 `data.pad_mode=no_padding`，交给已有 `SFTTensorCollator` 组成 jagged NestedTensor。文本首批 `processor` 必须为 None，不添加自定义 attention mask 或另写 loss。`verl.trainer.sft_trainer.create_sft_dataset()` 接受以上构造参数，并通过 `data.custom_cls.path/name` 装载；这是已有扩展点。

渲染和 mask 必须满足：

- P = 同一 tokenizer/template 对当次 `messages + tools` 的 `add_generation_prompt=True` 序列；F = 同一请求追加唯一目标 assistant，以 `add_generation_prompt=False` 渲染的完整序列。显式 `enable_thinking=False`，与当前 GRPO `++data.apply_chat_template_kwargs.enable_thinking=False` 一致。
- `F[:len(P)] == P` 必须在 token IDs 层严格成立，同时检查渲染文本边界。`input_ids=F`，`loss_mask=[0]*len(P)+[1]*(len(F)-len(P))`。所有历史 assistant、system/user、工具结果和工具 schema 为 0；唯一当前 assistant 的正文/调用 JSON 为 1。
- 使用固定 tokenizer 的 chat template 与已有 VERL wrapper，按真实模板保留本条 assistant 的终止 token，包括工具调用的结束标记。不手拼 `<tool_call>`、不额外追加 EOS，不把工具结果标为 EOS 或监督目标。检查 target suffix 非空、包含模板预期的终止边界、token 不超 vocab。
- code.host 中正则的反斜杠必须经真实结构化 arguments 的 JSON 序列化保留，例如源码的 `\w` 在 JSON 字符串中需转义；目标要能按当前 Qwen3 tool parser 解析并还原同一 arguments。学生失败输出里的裸 `<tool_call>` 文本和非法 JSON 不能冒充成功 target，也不能靠抽取其中源码绕过工具调用错误。
- Qwen3 的 thinking 标记和 BPE 边界可能使 P/F 不匹配。遇到 mismatch 必须停止并诊断；不能以 `ignore_input_ids_mismatch=True` 越过。先验明普通文本、tool-call、tool-result 后续决策及 schema 变化四类实际样本的边界，再冻结实现。
- `loss_mask` 在 token 所在位置置 1，不预先 shift；原生 `sft_loss()` 已 `torch.roll(..., shifts=-1)` 对齐 next-token logprob。需测第一目标 token 和最后终止 token 均被正确监督，跨样本无泄漏。
- 超过 `config.max_length` 拒绝样本/发布，禁止裁掉清理动作、tool JSON 或 EOS 后继续称完整示范。先 CPU 统计最大序列，再设置经显存预检的 `max_length` 与 `max_token_len_per_gpu`。
- 同时对照现有 `MessageCodec.encode_full()` 的相同输入确认 prompt render 一致。脚本没有 Qwen3 采样 token/logprob，转换后的 learner token IDs 不能声称是行为策略原始 token IDs；这不影响离线 SFT，但禁止当 on-policy RL 轨迹。

默认 `MultiTurnSFTDataset` 不满足本批严格要求：一条 row 只接受一份 tools（读入行167–171、使用行308），并监督该 row 中所有 assistant（行234–239）。把逐请求 prefix 直接交它，会重复监督历史动作；将整 Session 合成一条 row，会丢失动态工具视图。

## 数据划分与学习验收

- 按 case/fixture 原始身份分组后再展开 decision rows：公开 `train-01..04` 仅训练，`dev-01..02` 仅验证。同一 Session 或同源 prefix 不跨 split。不能对 decision rows 随机切分来伪造留出。
- 6 个已通过 smoke / 每 case 3 组业务输入仅证明可执行候选。新业务 prompt 重采集后需重新验证、生成独立 artifacts。T1 失败轨迹不能作为成功 SFT；若纳入 T1，先有对应真实成功示范和独立身份。
- dev 为公开开发集，非最终隐藏集；固定训练前后权重、prompt、预算、DSH/runtime/verifier，重新执行学生独立 eval。脚本输出和人工源码不得混入学生 eval 的提示。
- SFT loss 降低或一个 optimizer step 不是任务提升；需要非零更新、独立加载后的同条件任务结果。若新学生仍无法成功，报告缺口并按失败类型补示范，不立即重复全零奖励 GRPO。

## 原生训练、导出与返回 GRPO

下面是接口模板，新增数据类与数据发布完成并通过 CPU 门后才可运行。环境变量指向新目录；使用已安装固定环境，不执行依赖升级。首个 GPU 工程门 `SFT_STEPS=1`；学习批次步数另经小样本验证选择，不把 1 step 称作已暖启动。

```bash
# 在固定 Uni-Agent checkout；MODEL_PATH 为已验 Qwen3-4B snapshot。
"$PYTHON_BIN" -m torch.distributed.run --standalone --nnodes=1 --nproc_per_node=1 \
  -m verl.trainer.sft_trainer \
  data.train_files="$SFT_TRAIN" data.val_files="$SFT_DEV" \
  data.custom_cls.path=pkg://examples.dsh.capability_tasks.log_tool.sft_dataset \
  data.custom_cls.name=DshDecisionSFTDataset \
  data.pad_mode=no_padding data.truncation=error \
  data.max_length="$SFT_MAX_LENGTH" \
  data.max_token_len_per_gpu="$SFT_MAX_LENGTH" \
  data.train_batch_size=1 data.micro_batch_size_per_gpu=1 \
  data.use_dynamic_bsz=True data.num_workers=0 \
  ++data.apply_chat_template_kwargs.enable_thinking=False \
  model.path="$MODEL_PATH" model.tokenizer_path="$MODEL_PATH" \
  model.lora_rank=16 model.lora_alpha=16 model.target_modules=all-linear \
  model.enable_gradient_checkpointing=True model.use_remove_padding=True \
  engine=fsdp engine.strategy=fsdp engine.ulysses_sequence_parallel_size=1 \
  engine.model_dtype=bfloat16 engine.dtype=bfloat16 engine.use_torch_compile=False \
  optim.lr=1e-4 \
  checkpoint.save_contents='[model,optimizer,extra]' \
  ++checkpoint.save_lora_only=False \
  trainer.default_local_dir="$SFT_RUN" trainer.resume_mode=disable \
  trainer.logger='[console]' trainer.save_freq=1 trainer.test_freq=1 \
  trainer.total_training_steps="$SFT_STEPS"

"$PYTHON_BIN" -m verl.model_merger merge --backend fsdp \
  --local_dir "$SFT_RUN/global_step_$SFT_STEPS" --target_dir "$SFT_EXPORT"
```

`SFT_MAX_LENGTH` 必须来自真实数据统计及单卡预检；上述 lr 是候选值。保持 tokenizer/config/模板 hashes 与固定模型一致。首批保存完整 model checkpoint 是为了走现成 merger 并核验冻结基座；不是全参数训练。`hf_model` 直接保存分支不是本计划的 PEFT 导出入口。

原生 merger 会写 `SFT_EXPORT/lora_adapter/{adapter_config.json,adapter_model.safetensors}`，从 `lora_train_meta.json` 获取 rank/alpha。必须核验 `16/16`、target_modules、权重非空且有实际非零更新。merger 根目录的模型不自动包含已应用的 adapter；只将 MODEL_PATH 改成该根目录会丢失 LoRA 效果。该 merger 会将收集的权重转换为 bfloat16，应验证导出/重载的数值容差，不能假定不同 dtype 下逐字节相等。

另有必须实测的 adapter 加载边界：固定 FSDP engine `_build_lora_module()` 在新建 adapter 分支显式把可训练参数转成 base dtype（`:351–362`），而 `PeftModel.from_pretrained` 分支（`:323–337`）没有同样转换。如果实际 PEFT 加载后提升 adapter dtype，会与 bfloat16 base 形成混合 dtype；现有源码不能证明该配置已兼容 FSDP 包装。先用实际安装版本核对每个参数 dtype、包装与加载数值；若失败再以最小配置/加载修复解决，禁止把“已有 adapter_path API”写成已验证重载成功。

接回当前 GRPO 使用原基座 + `actor_rollout_ref.model.lora_adapter_path="$SFT_EXPORT/lora_adapter"`，仍显式 rank/alpha `16/16`，`RESUME_MODE=disable`、新 RUN_ROOT；先 `VAL_ONLY=True` 独立评估，再新建训练 run。`examples/dsh/train_qwen3_4b_online_rl.sh` 已转发尾部 Hydra overrides。operator launcher 若传额外 override，当前应使用 `--foreground`：后台 supervisor 分支没有转发尾部 `"$@"`，不能默认为 adapter 路径已生效。正式接线必须把解析后的 `lora_adapter_path` 和 hash 写入运行 manifest，启动前验证参数实际到达 trainer。

不能把 SFT `global_step_N` 直接交 `reload_qwen3_4b_checkpoint.sh`：SFT 权重在根目录，PPO v1 resume 在其下找 `actor/`，且会恢复 PPO global step、dataloader/队列。SFT→GRPO 应只继承 adapter 权重、重置优化器/调度器/步数。新 GRPO 保存出自己的 `global_step_N/actor` 后，独立 reload 才复用已有脚本；不以拷贝目录伪造 PPO checkpoint。

## 测试门与源码依据

1. CPU 来源测试：原始 hash、prompt、fixture、case split、runtime身份不匹配拒绝；失败/截断/孤立/重复目标拒绝；requests 与真实事件关联成立。最终 assistant 无下一 request 仍可正确绑定。
2. CPU mask 测试：固定真实 tokenizer，覆盖注册前/后、撤销后 tools 不同；当前目标每 token 受监督、全部历史/tool tokens 为 0；JSON 参数/null、EOS、thinking=False、prefix mismatch、超长、空目标负例；确保批次 padding 与 loss shift 正确。
3. 1-step GPU 门：复用固定 SFT trainer，记录 loss/grad/optimizer step，检查 LoRA 改变且基座冻结、checkpoint 可读、导出后 adapter rank/alpha/keys/数值一致；不同时启动现有 vLLM baseline。
4. 独立新进程加载同 base+adapter，实际 T1/T2 dev eval，确认 rollout 同步后的模型确实使用 adapter。随后只对有成功探索的配置运行 GRPO；GRPO 新 checkpoint 再走原 reload 并核验任务、receipt、轨迹和权重身份。

主要依据（均为固定 VERL 子模块中的相对路径）：

- `verl/trainer/sft_trainer.py:159` 复用 TrainingWorker；`:468` custom dataset seam；`verl/trainer/config/sft_trainer_engine.yaml` 单卡 SFT 配置。
- `verl/utils/dataset/multiturn_sft_dataset.py:234,308,425` 现有 mask / schema / token sanity check；`verl/utils/dataset/dataset_utils.py:32` 既有 collator。
- `verl/workers/utils/losses.py:28` 原生 SFT loss；`verl/workers/engine/fsdp/transformer_impl.py:323` PEFT adapter 加载。
- `verl/utils/checkpoint/checkpoint_handler.py:95` SFT checkpoint 布局；`verl/model_merger/base_model_merger.py:311` LoRA adapter 导出；`verl/trainer/ppo/v1/trainer_base.py:793` PPO resume 布局和状态。
- DSH `scripts/trace-training/converter.ts:298,424,455` 原生持久化恢复与目标投影。当前 Python 逻辑 events 与原生 session 文件须区分。

本页验证范围仅为源码与接口只读核查；没有运行新增 converter、数据类、SFT、merger 或 adapter→GRPO 实验。

## G1 注册决策补课（筛选原数据，不合成）

目标：针对实际注册失败，从已验证 `dsh.t2-sft-dataset.v1` 中只保留 target structured tool_calls 唯一调用 `cordis_define` 的 4 条 train 决策（每个固定公开 train case 恰好一条），原 28 条公开 dev 原字节保留。不得改 target、sample ID、request、provenance；不标成新数据或隐藏测试。

新增 `examples/dsh/capability_tasks/log_tool/prepare_sft_curriculum.py` 和对应 CPU tests。API `prepare(manifest_path, manifest_sha256, output)`；CLI `--manifest --manifest-sha256 --output-dir`。外部 hash 固定原 manifest，原 manifest 的 hash/rows 固定两份 parquet；严格验证 row schema、case/split/session/sample 唯一性，拒来源缺失/重复、未知 case、hash 错误及覆盖。课程 train 用 Arrow take 保留原 schema/值和原顺序；dev 原 bytes 复制。输出 owned 0700 新目录，sidecar 记录原 manifest 全体与 hash、输入/输出 hash、筛选 source IDs、目的 `registration-curriculum-not-new-data`；所有输入验证通过才创建输出。

测试：精确 4 原 rows/28 原 dev bytes，重复/缺失定义，错 split/schema/hash，目录权限/覆盖，确定性产物与原目标不变。后续训练计划是原 SFT step56 adapter warmstart、新 optimizer、lr 5e-5、16 epochs（4×16=64 steps）、1800 秒；复用 native 尾参 `model.lora_adapter_path` 与 `trainer.total_epochs=16`，不改 launcher 的 64-step cap。此入口不启动训练，也不证明补课有效。
