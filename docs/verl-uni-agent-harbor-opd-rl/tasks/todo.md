# Todo：上游 Harbor 内置 agent 路线（2026-09-16 用户拍板）

决策：先走上游 Uni-Agent `uni_agent/tasks/harbor` adapter + Harbor CLI + `harbor_env: modal` + 内置 agent（terminus-2），在 Terminal-Bench 2.1 上打通 Gateway rollout → Harbor verifier reward → VERL 更新。DSH-in-sandbox 路线（自建 Controller / Cloudflare ingress / registry 镜像）暂停，待训练通路证明后再把 agent 换回 DSH。

为什么不需要 tunnel：Harbor CLI 和 terminus-2 跑在 GPU 宿主机的 Harbor 进程里，只把 shell 命令送进 Modal 沙箱；LLM 调用从宿主机发往本机 Gateway（`LLM_BASE_URL` 等环境变量注入）。

## 阶段 A：环境（177，lane ws1）
- [x] `harbor[modal]>=0.16.1,<0.17` 装入 lane，`uv pip check` 通过，freeze 回写仓库快照 `deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt` 并更新 uv-runbook lane 表
- [x] Modal token 放 `/root/.modal.toml`（pod 重建后需重拷；不进 /workspace、不进仓库），`modal profile current` 在 lane 内可用
- [x] `harbor --version` 与 `python -c "import harbor, modal"` 在 lane 内通过

## 阶段 B：数据与 oracle（不占 GPU）
- [x] `python -m uni_agent.tasks.harbor.preprocess --dataset-ref terminal-bench/terminal-bench-2-1 --local-save-dir /workspace/verl-uni-agent-harbor-opd-rl/data --max-instances 5`
- [x] `parallel_infer_api.py` + `task_config_oracle.yaml` 跑 2 个实例（2026-09-16：2/2 resolved，reward 1.0，avg 67.8s，证据 `tb21-oracle-r1.json`），确认 Modal 沙箱创建、verifier 打分、`harbor/result.json` 有 reward，沙箱清理
- 证据：`runs/tb21-oracle-r1/`

## 阶段 C：Gateway rollout（单卡）
- [x] r3（2026-09-16）：`parallel_infer_verl.py --engine vllm --served-model-name hosted_vllm/Qwen3-4B-1cfa9a7 --task-config examples/harbor_opd_rl/tb21_terminus2_smoke.yaml --max-model-len 36864 --limit 2` → 2/2 session 成功，无异常，wall 299s，证据 `tb21-gateway-r3.json`。r1 因 max-model-len 不够失败，r2（16k）按用户要求中止改 32k。
- [x] `trajectory.json` + `trajectory.npz` 有 token 级轨迹；`harbor/result.json` 有 verifier reward（两题都 0.0，4B 未解出；session-1 跑了 28 步 / 207k 输入 token，session-0 只 3 步）。reward 非恒定还未出现，训练 smoke 只能证明机制
- 已定：`--served-model-name hosted_vllm/<name>`，litellm 剥前缀后走 `HOSTED_VLLM_BASE_URL`；Gateway 不校验 model 字段
- 证据：`runs/tb21-gateway-r1/`

## 阶段 D：RL 一步更新
- [x] r1 失败：`require_verifier_reward` 是 DSH 专属字段，Harbor session 全部被判失败并反复重采；现场 `runs/tb21-rl-r1-failed-require-verifier-reward/`
- [x] r2（2026-09-16 09:23–09:45）：**机制闭环跑通**。8/8 session 成功、0 失败；`timing_s/gen` 878s，`update_actor` 175s；`global_step_1` checkpoint 8.7 GB（model/optim/extra/lora meta）。但 reward 全 0 → `critic/score/mean=0`、`actor/grad_norm=0`、`pg_loss=0`，即零梯度更新。wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/33i5tfan；指标快照 `tb21-rl-r2-step1-metrics.txt`
- [x] **梯度非零首次出现（2026-09-16 12:09，pipe-r1 train attempt1，pass_ratio）**：step1 `critic/score/mean=0.208 max=0.667 min=0`、`actor/grad_norm=0.0131`、`pg_loss=0.142`；step2 `score/mean=0.406 max=0.75 min=0.25`、`grad_norm=0.0156`、`pg_loss=-0.0115`。wandb run `7ojulum1`。证据 `pipe-r1-train-attempt1-metrics.txt`
- [x] **pipe-r1 attempt5 train 通过（colocate_async，3 步，48 min）**：step1 score 0.333/0.667/0.25，grad_norm 0.020；wandb `ohz52n9r`
- [x] **delta 通过**：504/504 LoRA adapter 张量变化，399/399 base 张量不变（`checkpoint_delta.py`）
- [x] **resume 通过**：新进程从 global_step_3 加载 model/optimizer/rng/lr_scheduler，续训到 step 4（wandb `6iwtnfu6`）
- [x] **acceptance = PASS（2026-09-16 16:47 UTC）**：hard{mechanics, all_finite, resume_continued} 与 soft{learning_signal, reward_variance, wandb_ok, adapter_changed, base_unchanged} 全 true；证据 `docs/verl-uni-agent-harbor-opd-rl/pipe-r1/`
- 证据：`runs/tb21-rl-r1/`

## 总路线（用户 2026-09-16 明确顺序）
1. **terminus-2 训练完整打通**：阶段 A–D，加 wandb（project `xDAN-Verl-Uni-agent-Harbor-rl-opd`，entity `xdan-ai`），多步训练、checkpoint reload、held-out 评估。
2. **DAPO + OPD 联合更新（tinker 方案）**：把 tinker-cookbook 里的 RL/OPD/hybrid 逐 token Teacher 评分接到 harbor task 的轨迹上；本分支已有的 `examples/harbor_opd_rl/{opd,hybrid}.yaml` 与 Teacher→TQ→loss 接线复用；DAPO 侧用 VERL 原生 clip-higher / dynamic sampling / token-mean。
3. **DSH harness 接入沙箱**：把 agent 从 terminus-2 换回 DSH，届时才需要沙箱回连 Gateway（ingress / tunnel），复用本分支已写好的 Controller + Modal ingress 代码。

## 阶段 E：路线 1 收尾
用户要求（2026-09-16）："现在不关注结构，但要确保全流程完整打通"，且"全流程跑通应通过脚本化驱动"。驱动脚本：`examples/harbor_opd_rl/run_tb21_pipeline.sh`（env → data → oracle → rollout → train → delta → resume → summary，每阶段 `PASSED` 标记 + `pipeline-summary.jsonl`，可 `FROM_STAGE=` 续跑），最终 `summary/verdict.json` 给出 `full_pipeline_mechanically_closed` 与 `learning_signal_observed` 两个布尔。
- [x] pipe-r1 **PASS**（attempt5）。历史：attempt1 在 train 第 2 步后因 `total_epochs=1` 提前结束（已修）；attempt2（12:12）在第 1 步被 **Modal spend limit** 拒绝创建沙箱（`Workspace ac-uYbgBZtZlQfKIarWj1fZxk has exceeded its spend limit`），现场 `train-attempt2-modal-spend-limit/`。Modal 额度已恢复；attempt3 因 pod 重建中断（新端口 12063）；attempt4 一条 trial 卡在 Modal API 30+ 分钟（现场 `train-attempt4-modal-hang/`），已加 `trial_timeout_sec=2400` + `FAIL_ON_ROLLOUT_ERROR=0`；**attempt5 14:37 起**：colocate_async、max_turns 50、CONCURRENCY 8、n 4
验收口径（用户 2026-09-16）：按 wandb 面板实际曲线分析，不只看日志。关注 `critic/score/mean`（reward 均值）、`critic/score/std` 或组内 0/1 混合比例（advantage 是否非零）、`actor/pg_loss`、`actor/grad_norm`（非零且有限）、`response_length/mean`、`timing_s/gen` 与 `timing_s/update_actor`、`val/test_score`（held-out）。
- [ ] wandb 接入（脚本已改：`trainer.logger=['console','file','wandb']`，凭据在 177 `/root/.netrc`），下一次训练起跑验证面板有 reward / grad_norm 曲线
- [ ] 多步训练（≥5 步）+ checkpoint reload + 固定 held-out 子集评估；训练题与评测题隔离
- [ ] r3：TB 2.1 仅 4 题标 easy（fix-git / cobol-modernization / prove-plus-comm / overfull-hbox），已做成 `data/easy/harbor_tb21-easy-tasks.parquet`；n=4、3 步，看 `critic/score/std` 是否离开 0

- [ ] 下一轮（pipe-r2）：`max_turns` 30 → 50（attempt1 16 条轨迹 13 条撞上限，只有 2 条 completed），看 completed 占比与 reward 方差；本地已改 `tb21_terminus2_smoke.yaml`，**pipe-r1 跑完后再同步到 177**（trial 启动时重读配置）
- [ ] 同轮切 `TRAINER_MODE=colocate_async`（用户 2026-09-16 拍板，脚本默认已改）+ `CONCURRENCY=16` + `ROLLOUT_N=8`，观察 GPU 利用率、`timing_s/gen`、`actor/ppo_kl`（陈旧度）
- [ ] **pipe-r2 已起（2026-09-17，`runs/pipe-r2`）**：`DATASET=stage1 STAGE1_SLICE=20 STAGE1_SOURCES=terminal-lego-15k TRAIN_STEPS=6 ROLLOUT_N=8 CONCURRENCY=16 VAL_BEFORE_TRAIN=True TEST_FREQ=6 GPU_MEMORY_UTILIZATION=0.45`，prefix caching + CUDA graph 默认开；held-out 来自 validation 5 题，训练前后各评一次；之后 41 → 100+

## 阶段 F：路线 2 DAPO + OPD
- [x] 2 卡 pod 接入（2026-09-17 00:42，端口 11965，host dbcea07805e9，同一共享卷）：`gpu-pod-restore.sh` 恢复凭据、模型拷本地 NVMe、lane 重证通过；源码同步到 6b7f362
- [x] **pipe-r3 路线 ② 接线打通（2026-09-17 01:5x）**：`TEACHER=1`（4B 自评）在 GPU1 起 Teacher vLLM（79 GB），step1/2 更新成功，wandb `0jz8wq6h` 出现 `actor/distillation/{loss,abs_loss,loss_max,loss_min,ppo_kl}`；自评 Teacher 下 loss≈0（-0.0001，abs 0.0016，max 1.04 / min -1.91）符合预期（student≡teacher）。原任务：：`TEACHER=1`（4B 自评 Teacher 先打通接线）+ stage1 20 题 + 6 步 colocate_async + n 8 + 并发 16 + held-out 前后评估。GPU0 = actor + rollout vLLM 0.45，GPU1 = Teacher vLLM 0.8
- [x] 下载完成：`/workspace/models/Qwen3.8-27B`（52 GB，18 shards）、`/workspace/models/Qwen3.5-9B`（19 GB）
- [x] 4B TB 2.1 基线跑了两次（03:15–03:58）：n=1 `runs/eval-tb21-4b-base-n1` 89 题 0 通过（有效 54 条：20 ImageBuildError、13 NotFound）；n=3 `runs/eval-tb21-4b-base-n3` 267 条 0 通过（有效 62 条：129 ResourceExhausted、60 ImageBuildError="external shut-down"）。**结论：有效样本上 4B ≈ 0%，但因 Modal 额度中途触顶，基线不完整，需在额度恢复后重跑 n=1 作为正式基线**
- [x] **pipe-r2 验收 PASS（2026-09-17 07:46，`docs/…/pipe-r2/acceptance.json`）**：6 步训练 + resume 到 step 7，7/7 步 grad_norm 非零、7/7 步与 wandb 对账一致，504/504 adapter 变、399/399 base 不变；held-out 5 题 n=1：训练前 0.328 → step 6 0.497 → resume 起点 0.56 → step 7 0.458（5 题噪声 ±0.2，不能作为提升证据）；summary/acceptance 两个假 FAIL 已修（NUL 撕裂行、空指标行、TRAIN_STEPS 默认值）
- [x] **pipe-r3 train + delta PASS（08:30/08:32）**，6 步 Teacher 蒸馏指标齐全；resume 在 step 7 保存后被 Modal 第三次触顶打断（09:10），已布置 `modal-quota-wait.sh` 自动续跑链
- [x] **4B TB 2.1 正式基线 n=1：0/66 有效通过**（23 题因镜像/额度未完成）。`docs/…/tb21-4b-baseline-n1/`
- [x] 换 Modal 工作区 profile `l98348740`（2026-09-17 10:34），本机与两台 pod 均已激活；pipe-r3 续跑链 10:45 自动放行
- [x] resume 继承 train 冻结参数（1ec1b22），pipe-r3 resume 11:08 按 20/5 口径重跑
- [x] **pipe-r3 验收 PASS**（12:10 UTC）：Teacher + resume 连续，7/7 步梯度非零，wandb 对账一致；`docs/…/pipe-r3/`
- [ ] **pipe-r4：9B Student + 27B Teacher**（双卡，12:16 重起；审计混合集 40/7、batch 4、并发 32、6 步 + resume，`docs/…/pipe-r4/chain.sh`）：看 rollout 阶段 9B 推理、actor 是否 OOM、`distillation/loss` 是否离开 0、Teacher 每步耗时
- [x] ~~pipe-r5：4B + DAPO~~：12:06 停止，改用 GRPO（V1 下 DAPO 逐批补采、步长约翻倍，开关原本接错参数，469b09b 已修）
- [ ] **pipe-r6：4B GRPO，40/7 审计混合集，batch 4、并发 32、20 步**（单卡，12:08 起）：看训练集 reward 曲线，并在第 0/10/20 步评 held-out 7 题
- [ ] 明天：从 Full 抽 100 道（按 SWE 审计状态 50 道 + Terminal-Lego 前 104 道审计通过的 50 道）；数据阶段要支持 tar.gz 解包，并合并 audit-status.jsonl
- [x] SWE-rebench 25 题 verifier `--ctrf` 不可用 → 根因是 `docker_image` 跳过 Dockerfile，5fa9d6a 修复，oracle 复验 3/3 通过；下一轮起 `STAGE1_SLICE=0` 混合 41 题
- [ ] Full 数据集（15397 题，未审计）：`10_data.sh` 支持 `runtime-v1.tar.gz` 解包 + 按审计结果过滤；先切 100 题（审计通过的 SWE + 自审的 Terminal-Lego 抽样），再 500–1000 题
- [x] 04:00 Modal 触顶 → 06:46 用户加了 $10（≈300 条 trial）。已按价值顺序脱离会话重启：pipe-r2 resume 重做（旧 pod，≈$0.7）、pipe-r3 带 Teacher 重训（新 pod，≈$4）；基线重跑与 pipe-r4 等额度
- [ ] 有效 TB 2.1 基线需要：Modal 额度 ≥ 500 沙箱/天；建议 Docker Hub 登录（Harbor `registry_secret`，适配器需透传）避免匿名拉取限流
- [x] ~~pipe-r4 用 4B Student + 27B Teacher~~：词表不同（151936 vs 248320）不可行，改为 9B Student（见上）
- [ ] `report.py` / `80_acceptance.sh` 增加 OPD 三行与 Teacher 检查（teacher logprobs 非空、distillation loss 非零）
- [ ] 复核 tinker-cookbook-opd-rl 的 harbor_opd_rl.py 评分合同，对齐到 harbor task 轨迹（token ids / action mask 来自 Gateway npz）
- [ ] 27B Teacher 服务化（独立 GPU 角色）；单卡先用 4B 自评做接线冒烟
- [ ] hybrid loss（RL + OPD 加权）在 harbor 轨迹上非零梯度证据

## 阶段 G：路线 3 DSH 进沙箱
- [ ] 重启 ingress 路线：专用 hostname / tunnel / registry 镜像；agent 切 DSH，其余训练链路不变

## 约束
- 每步只留一份证据目录，失败现场不覆盖
- GPU 启动前 `nvidia-smi` 确认空闲，不停别人的进程
- 每次 push 过 Ruff 双门
