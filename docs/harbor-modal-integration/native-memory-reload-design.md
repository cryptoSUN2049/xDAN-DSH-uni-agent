# Native memory 独立 reload：最短工程路径

状态：最小实现已落本地，准备器+NativeMemoryFramework+credit 合计89项CPU回归通过（34.65秒），未启动 GPU。母实验目标是 `memory-resident-train-r2`，尚不能预先认定其会产生有效更新或可加载 checkpoint。先等待真实训练退出、消费和保存审计，再准备独立 reload。

## 目标与边界

用新的 run/data/chains/Gateway/DSH sessions，从母实验真实 checkpoint 加载 model、optimizer、extra，运行同族 fresh A→freeze→B val。保持原训练目录、回执、checkpoint 不变。复用现有单卡 DSH ops、VERL sync、NativeMemoryFramework 与 owned supervisor；无需导出 HF、独立 vLLM API 服务或新 trainer。

最短路径是在 `prepare_memory_training.py` 增加 `mode=reload` 与 `resume_from`，内部仍走相同 ops launcher，通过已有 `RESUME_MODE=resume_path`、`RESUME_FROM_PATH`、`VAL_ONLY=True` 接口。已有 `ops/reload_qwen3_4b_checkpoint.sh` 也可用，但会增加一层参数默认覆盖；直接原 launcher 的已有 resume 接口更短，且保持 manifest 的固定 argv 可审计。

不修改已经生成的 train-r2 manifest/environment，也不手工补尾参数给旧清单。新功能提交后，建立新的干净固定 checkout，重新 prepare reload。记录母训练源码与 reload 源码差异；VERL、DSH、模型结构、任务 verifier/StageSpec 相关源码必须不变或明确独立回归，不能只拿分支名充当 pin。

## 三种身份必须分开

| 身份 | 用途 |
|---|---|
| Base model revision `1cfa9a…` | 创建相同 Qwen3-4B 与 LoRA16 模型结构、tokenizer；继续等部署锁 |
| 实际 checkpoint identity | 母 run、完成 step、精确 checkpoint 文件内容摘要；传给 `memory_operator.checkpoint_identity`，写入 A/B fixture/链回执 |
| 调度 step / Gateway policy version | 检查真实 generation 版本；不能代替 checkpoint 文件身份或实际 load 日志 |

当前准备器把 operator checkpoint identity 设为 base revision；reload 必须改为 checkpoint manifest 的规范 JSON SHA，例如 `sha256:<digest>`。新增 `checkpoint-origin.json` 包含母 run、母 source HEAD、来源路径、step、文件大小及 streaming SHA256。该 identity 不包含新 reload run 名，避免同一产物换 run 就变身份。路径与身份都写入准备 manifest，但 canonical identity 使用明确固定字段，不依赖目录遍历顺序。

文件至少覆盖单卡 actor 的 `model_world_size_1_rank_0.pt`、`optim_world_size_1_rank_0.pt`、`extra_state_world_size_1_rank_0.pt`，以及存在并将被 VERL 读取的 `data.pt`；保存器产生的其他配置/权重元数据也列入清单。执行前依据母实验真实文件名确认 `extra_state` 命名，不把目录存在等同完整 checkpoint。分块读 SHA，不能对数 GB 权重 `read_bytes()` 一次入内存；不复制大文件，也不为摘要执行不必要的 `torch.load`。

## 配置合同

- `--mode reload` 必须有绝对 `--resume-from .../global_step_N`，N为非负整数，路径为已完成母实验产物；train/val 禁止附带 resume 参数。第一批预计母 train-r2 是 step1，按实际保存为准。
- 同一基座、LoRA rank/alpha、全模型 checkpoint 保存格式和 load contents；显式 `['model','optimizer','extra']`，`del_local_ckpt_after_load=False`。
- `VAL_ONLY=True`、`trainer.val_before_train=True`、sync、ROLLOUT_N=4/VAL_ROLLOUT_N=1 保持框架合同。val-only 只调度一条 val 链，不是把全局 ROLLOUT_N 改成1。
- `TOTAL_TRAINING_STEPS=1` 可沿用：固定 `trainer_base.fit` 在验证后遇 val_only 直接 return，发生在训练 step 递增和 update 前。不能靠 total steps 小于 checkpoint step 防止更新。
- 新 CKPTS_DIR 仅是独立输出根；不可设为母 checkpoint 目录。新 prepare/check 拒已存在 run/outputs/Ray；source/输入/runtime/model/完整 checkpoint 摘要在 launch 前重验。
- 新 `checkpoint-origin.json` 及其摘要写入 `manifest.files`，并把完整 checkpoint map 写入 manifest，由 check 逐项核实，防止 origin JSON 自洽但真实权重已被换掉。
- 固定 family 与母实验一致，仍标 `fixed-diagnostic-not-heldout`。奖励规则不变，不要求数值与母实验验证逐字节相同。

## 固定 VERL 的加载/版本依据

`verl/verl/trainer/ppo/v1/trainer_base.py:_load_checkpoint` 从 `global_step_N` 设 `self.global_steps=N`，调用 actor `load_checkpoint`，并在存在时恢复 `data.pt`。`trainer_sync.py:on_init_end` 在恢复后执行 `update_weights(self.global_steps)`，把 N 发布到 Gateway backend。`fit` 的 initial validation 在任何训练 step 递增之前执行，val_only 立即返回。

所以 reload val 的 stage context/global_steps=N，实际全部 generation 的 min/max policy version 必须为 N，且 generation_count 完整。NativeMemoryFramework 已有 `expected_sync_policy_version(N,'val')=N`；无需改这个映射。训练 k→weight k-1 的规则仍只适用于 train。不得为缺失实际版本补 N。

固定 FSDP checkpoint manager 实际 load model/optimizer，并从 extra 恢复 RNG/lr_scheduler。验收需保存这些实际 load 日志，不能仅引用 manifest 的 resume 字段。`data.pt` 的训练 dataloader 状态即使恢复也不应产生 train 采样；新调度表保持与母实验一条 train 的兼容形状，val-only 不消费它。

## 文件变更与测试

| 文件 | 最小改动 |
|---|---|
| `examples/dsh/capabilities/prepare_memory_training.py` | mode=reload/resume-from，streaming checkpoint摘要/来源身份，check重验，固定val-only/load参数 |
| `tests/uni_agent/examples/test_prepare_memory_training.py` | reload真shell→Hydra→from_config与文件/路径反例 |
| `docs/harbor-modal-integration/native-memory-recipe-runbook.md` | 新prepare/check/launch/audit命令，区分base和checkpoint身份 |
| 本设计及独立真实结果报告 | 记录实际保存/加载、fresh消费、无更新、能力边界 |

先 red 测试，再最小实现；现有 train/val 默认行为不变。测试包括：

1. 使用临时小文件模拟完整 actor checkpoint，准备 reload 后 config 的 resume/val_only/load contents/delete=False 正确，operator identity 是 checkpoint digest 而非 base revision；真实 NativeMemoryFramework.from_config 通过。
2. source step路径非法、missing model/optim/extra、resume参数与mode冲突、母/新输出重叠、checkpoint被篡改/替换、newrun复用均在 GPU 前拒绝。
3. 真实固定源码加载/发布/val-only时序测试：执行可分离 sync hooks，验证 N 发布、val version=N；AST核 val_only return 在训练增量/step之前。必要时以小 fake trainer 执行分离的控制流，不能 mock成预定通过。
4. 原 train/val6项+memory框架回归继续通过。CPU文件不是有效torch checkpoint，不能据此宣称实际load成功；真实load必须GPU确认。

## GPU 验收与证据

先 CPU 保存母 checkpoint 文件摘要，再启动全新独立进程 reload；无须持有母训练进程。完成后至少确认：

- supervisor exit0；日志实际恢复目标 step，并 load 对应 model/optimizer/RNG/lr_scheduler。
- 新 A/B Gateway与DSH session，独立 freeze，B 只见问题与冻结记忆；新 stage receipt/trace/NPZ 与 chain crosswalk。
- 一条 val sibling（A+B 可包含多条 trajectories，不硬编码只有2条TQ key），真实版本均N。复用 `python -m examples.dsh.capabilities.audit_memory_training <run> --memory-root <run>/chains --run-id <id> --output <new-json>`，核实际 val 消费、未知/重复/未准入消费为空。
- 额外确认 train partition 消费为空、没有 optimizer update 指标和新 model checkpoint；仅 auditor passed 不足以证明“未更新”。
- 完成后母 checkpoint 摘要不变、未被删除；报告新 CKPTS_DIR 是否为空/仅创建目录，不能把目录存在当权重写入。

完整原始清单、supervisor、load日志、stage/chain证据、消费审计与checkpoint前后摘要归档到 `/workspace/reports`，记录归档 SHA；大 checkpoint 原地保留于 `/workspace/uni-agent-g1/checkpoint`。

若母训练 n4 全同分/梯度零，即使 checkpoint 能独立加载，也只能说明保存恢复和真实评估工程成立，不能声称记忆学习提分。reload得分允许随机波动，单族一次成功不代表泛化，更不是精确随机过程复现。

## 本批实际接口与证据

`prepare` 新增 keyword-only `resume_from=None, mother_run=None`。CLI 为原全部必需参数加 `--mode reload --resume-from /workspace/uni-agent-g1/checkpoint/<mother>/global_step_N --mother-run /root/runs/<mother>`；其余 `check <manifest>` / `launch <manifest>` 入口不变。母身份不接受口头 `--mother-sha`：读取母 `run-manifest.json`（必须 completed/exit0）、`memory-launch-plan.json` 和 run-manifest 绑定的原 dataset manifest，要求原始内容/文件摘要相符，HEAD、VERL、基座、runtime、family、RUN_ROOT、CKPTS_DIR 均相互一致。对原 checkpoint 和母 run 的新目录重叠也在 prepare 前拒绝。

`checkpoint-origin.json` 保存母 source HEAD、母 run、checkpoint路径/step、三份母证据摘要和所有 checkpoint 文件 streaming SHA/size。canonical identity 包含这些稳定母产物字段，剔除新 run/data 名；对同一母产物新建两套 reload 的测试证明 identity 不变。check 对真实 checkpoint 全量重测并与 origin/manifest 双对照；缺失或替换、源证据改动、val-only/delete配置篡改均拒绝。原摘要 `digest()` 已改为1MiB分块，不一次读入权重。

新增尾参数显式 `trainer.val_only=True`、`trainer.val_before_train=True`、`trainer.del_local_ckpt_after_load=False`、load `[model,optimizer,extra]`。check 验证它们最后生效值和 operator checkpoint identity；mode与resume/mother参数冲突拒绝。原 train/val 模式不允许附带resume参数。

测试先RED：旧准备器拒绝未知 resume_from。随后真实shell执行分支（仅最终Python记录argv）→固定Hydra→NativeMemoryFramework.from_config 的 reload测试通过，原train/val也保持通过；新增母证据缺失/状态/源码不符、checkpoint缺文件/篡改、identity稳定性、输出重叠、val-only/delete覆盖反例。固定 VERL AST验证 val_only return 位于训练 step递增前。临时checkpoint只用于CPU文件/配置检查，不能宣称实际torch权重已加载。
