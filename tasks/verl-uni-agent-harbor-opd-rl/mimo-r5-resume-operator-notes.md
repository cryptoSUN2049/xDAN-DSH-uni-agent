# r4 C2 → 独立 r5 step 3：只读 operator 核验

核验时间：2026-09-28 12:35 UTC。本笔记没有执行准备、停止、部署、训练或 GPU 探针；没有输出凭据值。

## 当前状态与时间门

- 只读看到 r4 operator `running`，supervisor PID 996，启动 Unix 时间 `1790597979.560554`，wall budget 2400 秒。当时 `/workspace/mimo-dsh-rl-20260928/runs/r4/rl-training/checkpoints` 尚不存在。不能预设 C2 已保存。
- GPU 硬截止为 13:26:54 UTC。prepare-r4 将 controller deadline 设置为 lease 减 180 秒；driver 再扣 180 秒。因此沿用该预留，r5 有效运行必须在 **13:20:54 UTC** 前结束。
- 当前至有效截止约 45 分钟，须覆盖 r4 完成、清理、r5 完整模型初始化、C2 restore、一个完整 4-rollout GRPO group、更新和保存。当前 r4 尚在首次 vLLM 初始化，剩余耗时未知，不能承诺本窗口可完成。
- 现有 driver 的 `wall >= 600` 只是不启动过短尝试的下限，不是完成恢复验收的证据。应在 C2 完整落盘后，以本次真实初始化耗时加 group/保存时间重新判断；不足则保全网络卷 checkpoint，另开受限计算窗口，不放宽 lease。

## 最短路径：复用冻结软件和同一存活 Pod，更新运行身份

无需新 uv 环境、新模型下载或复制整份源码。沿用已冻结 `run-src-r4`、同一模型 revision、LoRA 配置、单卡 world size、任务内容和固定软件依赖。r5 是新的运行身份，不要求源码目录也叫 r5。

必须更新：

| 字段/产物 | r5 建议 |
|---|---|
| `run_id` / `controller_id` / `worker_id` | `mimo9b-001661-r5` / `mimo-controller-r5` / `mimo-worker-r5` |
| controller `root` | `/root/mimo-private/controller-r5`，须不存在 |
| RunSpec 文件 | `/root/mimo-private/run-spec-r5.json`，重新 `RunSpec.model_validate` 后 canonical digest |
| registration / worker token | 独立生成两份不同随机值，新 r5 路径，0600；CPU/GPU 私有副本一致 |
| prepared launch / task config / artifact / registration roots | `/root/mimo-private/launch-r5/*`；重新调用现有 `prepare_training`，不可复制旧 receipt |
| `environment.RUN_ROOT` | `/workspace/mimo-dsh-rl-20260928/runs/r5` |
| supervisor manifest / logs / Ray 临时目录 | 新 r5 文件及 `/root/mimo-private/ray-r5`，保留 `O_EXCL` |
| `policy_template.tunnel_alias` | `mimo-cloud-r5` |

端口不是身份本身，彻底释放后技术上可复用；建议新用 `38640/38641/38642` 分别作为 control/worker/model，remote control/worker 为 `38640/38641`，Modal ingress `38643`，启动前核占用。

在同一 Pod 和未到期 lease 内，SSH host/port、Gateway 节点 IP、SSH key/known-hosts、HTTPS origin、Cloudflare named-tunnel ID/凭据、GHCR registry secret、逻辑 model name 均可保持。重新核 discovery 与 lease 的 Pod ID 一致，deadline 仍不得超过当前 lease。HTTPS origin 不改可保持已冻结任务 hostname allowlist；两个 named-tunnel connector 不应并存，先确认旧 ingress 退出。

`task_dir` 可指向既有只读冻结任务；若为 r5 重建到新目录，应运行 `task_digest` 并核 CPU/GPU 内容一致，不人为修改 hash。任务相同允许 TaskRef digest 不变；run-spec digest、route registration 与 session 身份必须更新。

## Operator 顺序

1. 等 r4 supervisor 正常终态，核实际 C2 目录和同步保存完成，不仅检查目录名。保留 r4 原始日志、参数变化/奖励/轨迹证据。
2. 确認 r4 trainer 及其拥有的 Ray/GPU 子进程已退出，再向旧 controller 的已核 PID 发送 SIGINT。核 `controller-r4/controller-stop.json` 的 `cleanup_errors=[]`；核旧 worker/ingress/SSH forwards 和 Modal 沙箱真实退出。不要全局 `pkill`/`ray stop`。
3. 以 prepare-r4 的同一合同准备 r5，但使用上述新身份和文件名。注册/worker token 从新私有文件传入，不打印。`prepare_training(..., mimo_binding=..., max_concurrent_sessions=1, train_count=1, heldout_count=1)`；数据仍是同题工程 smoke，不称独立 heldout。
4. `RUN_ROOT` 指向持久卷 `runs/r5`。新样本 UID 会由 r5 run_id 派生；`data.pt` 恢复依赖数据行数/顺序一致，因此保持相同单题、shuffle=false、seed=42 和 group n=4。
5. 启动新的 CPU controller，先核认证 health 的 r5 `run_id/controller_id/run_spec_sha256`、`unregistered`、`healthy=true`。trainer 启动后 Gateway 才生成新的 registration receipt；绝不能复用 r4 receipt。
6. 在 GPU 主机先以隐藏 CUDA 的 CPU preflight 验证相同命令（添加 `--preflight-only`），随后通过原 supervisor 执行恢复。使用当前已冻结解释器与 `PYTHONPATH=run-src-r4:run-src-r4/verl`。

准确的 native launcher 恢复参数：

```text
--mode rl
--launch /root/mimo-private/launch-r5/launch.json
--recipe-config /workspace/mimo-dsh-rl-20260928/run-src-r4/examples/mimo_dsh_rl/mimo-9b-smoke.yaml
--resume-from-path /workspace/mimo-dsh-rl-20260928/runs/r4/rl-training/checkpoints/global_step_2
--total-training-steps 3
--save-freq 1
```

`total-training-steps=3` 是绝对终点，不是再跑三步。`preflight_training` 会据一行数据把 `total_epochs` 调整到 3；原生 trainer 从 global step 2 加一后执行 step 3。

## 已发现的 wrapper 接线缺口

当前 `/workspace/mimo-dsh-rl-20260928/audit-code/mimo-supervised-native.py` 的 `native_training_command()` 只生成 `--mode/--launch/--recipe-config`；现有 supervisor manifest 不自动传递 resume 字段。仅修改 manifest 或向 launch-r4-driver 追加 CLI 参数不会触发恢复。

r5 需要一份独立、冻结并验证过的 operator wrapper：继续调用 `harbor_training_supervisor.main/supervise`，只让 `native_training_command` 在现有 command 后附上上述三组恢复参数。不要修改 r4 正在使用的 wrapper、共享源码或 supervisor。冻结新 wrapper/hash，并用命令构造/真实 compose 证明恢复路径及绝对 step target 已进入 trainer 参数。

审查草稿已提供：`docs/verl-uni-agent-harbor-opd-rl/mimo-r5-resume-wrapper.py`。它保留旧 wrapper 的 legacy adapter 拒绝和 frozen recipe cwd 检查，仅增加固定 C2/target3/save1 参数。该草稿尚未部署或启动。

CPU command contract 验证：`tests/uni_agent/examples/test_mimo_resume_wrapper.py`，先 3 failed（文件尚未创建），后 **3 passed / 0.23s**；Ruff check/format --check 通过。测试以 fake supervisor、实际 argparse 和 `runpy` 执行 main 接线并核完整 argv，没有导入 CUDA 栈。wrapper SHA256 为 `5ab3f44f8facd254556a996e1bf8f25f21645ea02cf3041fcb5d83857f35a5b5`；远端 raw log `/workspace/mimo-dsh-rl-20260928/integration-check/mimo-r5-wrapper-green.log`，SHA256 `f7da7f86cbf89957a3d2994d522437ec98ca4c257402418f86bbcbd223cc7b9e`。该测试未代替真实 C2 生成后的 native resume preflight。

## C2 完整性与恢复证据

单卡 C2 至少应有：

```text
global_step_2/data.pt
global_step_2/actor/model_world_size_1_rank_0.pt
global_step_2/actor/optim_world_size_1_rank_0.pt
global_step_2/actor/extra_state_world_size_1_rank_0.pt
```

现有 base recipe 的 save/load contents 都是 `[model, optimizer, extra]`。`extra_state` 包含 RNG 和 scheduler。原生 `FSDPCheckpointManager.load_checkpoint` 会分别记录 model（或 LoRA-only）、optimizer、rng、lr_scheduler 加载；trainer 记录 `Resuming from ...global_step_2, setting global step to 2` 并加载 `data.pt`。

验收必须在 r5 `train.log` 中收齐上述实际加载记录，并证明 step 3 有完整新会话、可信奖励、非零有效更新，随后在 `runs/r5/rl-training/checkpoints/global_step_3` 形成完整保存。`training-preflight.json` 只能证明参数/数据准入，不证明权重已恢复。不能只凭 `Loaded model` 宣称 optimizer/RNG 恢复。

TransferQueue 当前安装版本源文件为 `0.1.9.dev0`，`__init__.py` 不导出 save/load checkpoint；固定 VERL 的 `_tq_supports_checkpoint()` 要求版本 `>=0.1.9` 且两个 API 可调用。因此当前不会保存/恢复 TQ 流水线状态。C2 后 r5 使用新 run/session 重新采样；可以验收模型+optimizer+RNG+dataloader 恢复，**不能称异步 in-flight rollout 精确连续恢复**，也不要为本次验证临时升级共享 TQ。

## 只读来源

- 远端 `/root/mimo-private/prepare-r4.py`（凭据相关字符串脱敏读取）。
- 远端 `audit-code/launch-r4-driver.py` 与 `audit-code/mimo-supervised-native.py`。
- `deployment/services/harbor_run_controller.py`、`harbor_training_supervisor.py`、`harbor_modal_ingress.py`。
- `examples/harbor/prepare_m2_training.py`、`examples/harbor_opd_rl/launch.py`。
- `verl/verl/trainer/ppo/v1/trainer_base.py` 与 `verl/verl/utils/checkpoint/fsdp_checkpoint_manager.py`。

## 当前 FlashInfer warning 的只读定位

固定环境 `flashinfer/compilation_context.py:56/81` 发出 `Failed to get device capability: SM 12.x requires CUDA >= 12.9`。自动设备探测的异常在 `CompilationContext.__init__` 中被捕获并记录 warning，因此该条消息本身不终止初始化。代价是 `TARGET_CUDA_ARCHS` 可能为空；后续若使用该 context 的 `get_nvcc_flags_list`，会抛 `No supported CUDA architectures`。

`flashinfer/jit/cpp_ext.py:68–91` 的版本检查优先执行 `CUDA_HOME/bin/nvcc --version`；只有 nvcc 不存在或执行失败才回退 `torch.version.cuda`。因此系统 toolkit 12.8 与 Torch cu130 并存时，JIT 检查仍得到 12.8。当前没有修改环境，也没有运行 CUDA 探针；是否触发该 JIT 路径需以本次后续日志为准，不能把当前 warning 冒称最终失败或已验证安全。
