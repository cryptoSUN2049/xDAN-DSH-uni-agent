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
- [x] **pipe-r4 验收 PASS（20:07）**：9B + 27B Teacher 全流程闭环，无 OOM，蒸馏 loss 0.10–0.13，长度未暴涨；held-out 7 题 0.988 → 0.914（饱和且样本太少，需在 100 题评估集复核）
- [x] pipe-r4 第一次训练：13:41 时 9B 推理引擎 OOM（每步 36864 个 token）→ 13:47 改成每步 8192 个 token 后从训练阶段重起
- [x] pipe-r4 第二、三次训练 OOM（14:41、15:4x）：最初误判为学生引擎显存增长，15:45 查实三次都是 27B Teacher 显存比例 0.85 放不下 prompt logprobs 缓冲 → 15:48 改为 Teacher 0.70 / 4096 后重起（第 4 次）
- [x] 16:00 按用户要求 Teacher 再保守：单批 2048、同时 4 条序列、显存比例 0.70 → pipe-r4 第 5 次训练
- [ ] 下一轮两边同步把学生侧恢复为 prefix caching 开、单批 8192、显存比例 0.45（当前的保守设置是误判后加上的），Teacher 保持 0.70 / 4096
- [x] ~~pipe-r5：4B + DAPO~~：12:06 停止，改用 GRPO（V1 下 DAPO 逐批补采、步长约翻倍，开关原本接错参数，469b09b 已修）
- [x] ~~pipe-r6：4B GRPO 20 步~~：14:00 跑完第 1 步后停止，单卡改作对照组
- [ ] **pipe-r7：9B 纯 RL 对照组**（单卡，14:02 起）：与 pipe-r4 完全镜像，只是 `TEACHER=0`；明早与 pipe-r4 对比 reward、held-out、步长
- [ ] **单卡 pod 失联（15:52 起）**：用户在 RunPod 控制台重启 → 必要时跑 `gpu-pod-restore.sh` → 停掉旧 pipe-r7 会话 → 把 `runs/pipe-r7/chain.sh.v2` 复制为 chain.sh → 从训练阶段重起（设置 v2）
- [x] 设置 v2（用户决定，16:05）：Teacher 单批 4096；学生侧 prefix caching 开 / 8192 / 0.45；pipe-r4 于 16:09 重起（第 6 次）
- [ ] **部署 f81ae2c + e50b110（基础设施故障剔除、agent 失败记 0）**：pipe-r4 和 pipe-r7 都结束后，把 `uni_agent/tasks/harbor/{reward,task}.py` 同步到共享卷，再起下一轮。不能在 run 进行中同步，否则同一个 run 里会混用两种计分规则
- [x] 数据阶段支持 Full 仓库（e50b110 / 9d6a11d）：合并审计 sidecar、按来源限额选题、held-out 用审计通过但没进训练的 train 题补足、只解压选中的题、按来源交错排序。实测 100 道训练 / 40 道 held-out，无重叠
- [x] 固化脚本：`examples/harbor_opd_rl/run_opd_round.sh`（a5bb9c8），一条命令起一轮，默认值即 pipe-r4 验证过的配置，含 `--smoke`
- [x] 部署适配器修复（基础设施故障剔除）到共享盘，已校验一致
- [x] 数据阶段加难度筛选 `STAGE1_DIFFICULTY`（默认 medium hard）
- [ ] **Modal 额度恢复后**：`runs/pipe-r8-smoke` 会自动开跑（已排队）；冒烟通过后起正式轮次（20 步以上、held-out 换成 100 道共享评估集）
- [ ] 单卡 pod 恢复后起 9B 纯 RL 对照组（同一份数据与步数，`TEACHER=0`）
- [ ] **选题要按难度筛**：pipe-r4 第 1 步训练集得分 0.916、held-out 0.988，说明审计通过的题对 9B 太简单。下一轮训练题应挑基座 9B 时对时错的题（与 eval-set-v1 同一筛法），或至少限定 medium/hard
- [ ] **跟踪长度偏置**：逐步记录 `response_length/mean` 与 `num_turns/mean`；若长度升而得分不升，按 Tinker 线 r4 的退步案例处理
- [x] 核对 `num_turns` 口径：`_count_chat_turns`（`uni_agent/gateway/session/session.py:958`）= user + assistant 消息数 + 1，工具返回算 user 消息。62.9 约等于 31 次模型动作，未越过 `max_turns=50`；每次动作约 796 token
- [x] 数据阶段默认剔除 eval-set-v1 保留集（仓库 / 题目），在 Full 上实测与保留集重叠 0
- [ ] 收到 Tinker 线的 eval-set-v1 manifest（100 道，明天上午）后，数据阶段支持用 manifest 指定 held-out，替换当前"顺延 20 道"的规则
- [x] SWE-rebench 25 题 verifier `--ctrf` 不可用 → 根因是 `docker_image` 跳过 Dockerfile，5fa9d6a 修复，oracle 复验 3/3 通过；下一轮起 `STAGE1_SLICE=0` 混合 41 题
- [ ] Full 数据集（15397 题，未审计）：`10_data.sh` 支持 `runtime-v1.tar.gz` 解包 + 按审计结果过滤；先切 100 题（审计通过的 SWE + 自审的 Terminal-Lego 抽样），再 500–1000 题
- [x] 04:00 Modal 触顶 → 06:46 用户加了 $10（≈300 条 trial）。已按价值顺序脱离会话重启：pipe-r2 resume 重做（旧 pod，≈$0.7）、pipe-r3 带 Teacher 重训（新 pod，≈$4）；基线重跑与 pipe-r4 等额度
- [ ] 有效 TB 2.1 基线需要：Modal 额度 ≥ 500 沙箱/天；建议 Docker Hub 登录（Harbor `registry_secret`，适配器需透传）避免匿名拉取限流
- [x] ~~pipe-r4 用 4B Student + 27B Teacher~~：词表不同（151936 vs 248320）不可行，改为 9B Student（见上）
- [ ] `report.py` / `80_acceptance.sh` 增加 OPD 三行与 Teacher 检查（teacher logprobs 非空、distillation loss 非零）
- [ ] 复核 tinker-cookbook-opd-rl 的 harbor_opd_rl.py 评分合同，对齐到 harbor task 轨迹（token ids / action mask 来自 Gateway npz）
- [ ] 27B Teacher 服务化（独立 GPU 角色）；单卡先用 4B 自评做接线冒烟
- [ ] hybrid loss（RL + OPD 加权）在 harbor 轨迹上非零梯度证据

## 阶段 H：2026-09-18 数据与训练计划

### H1 数据计划（题从哪来、怎么筛、怎么留出）
- [x] **题源改为官方训练切片**（数据线 5e 会话发布，5712381 接入）：`gump2049/xDAN-Harbor-Stage1-Tasks` 的 `slices/stage1-swe150-tl50-v1`（200 训练 / 8 验证）与 `stage1-swe300-tl200-v1`（500 / 8）。审计通过、已剔除评估集、对 23 个评测（含 Terminal-Bench 2.0/2.1、SWE-bench Verified/Pro）做过防污染。参数 `STAGE1_SLICE_NAME`
- [x] 备用题源：Full 仓库的合并索引 `audits/passing-tasks.jsonl`（无防污染保证，只在切片不够用时使用）
- [x] 在切片上叠加 medium/hard 筛选：stage1-swe150-tl50-v1 的 208 道 → 148 道（Terminal-Lego 50，SWE 91），按来源各取 50 道训练
- [x] 选题规则：每来源按索引顺序取 N 道训练，再往后取 M 道做 held-out，两者不重叠；目录加序号前缀保证两来源交替（否则每个 epoch 会先跑完一个来源）
- [x] 每条 run 独立 `DATA_DIR`（两台 pod 共享 `/workspace`）
- [ ] 收到 eval-set-v1 的 100 道 manifest 后，held-out 换成它，两条线用同一把尺子；数据阶段加 `STAGE1_VAL_MANIFEST`
- [ ] Terminal-Lego 可训练池扩到约 320 道后（Tinker 线在补审），把每来源配额从 50 提到 100

### H2 训练计划（本轮 pipe-r9）
- [ ] **前置门 1**：`pipe-r8-smoke` 验收 PASS 且成本核验通过（泄漏 0、计费/实际 ≤1.5、每条 ≤0.05 美元）
- [ ] **pipe-r9 正式轮次**：Qwen3.5-9B Student + Qwen3.8-27B Teacher，数据 `STAGE1_SLICE_NAME=stage1-swe150-tl50-v1` + medium/hard，各 50 道共 100 道，20 步（2 epoch），每步 4 题 × 8 条，并发 16，预计 7–9 小时、约 700 条 trial、12–15 美元；held-out 先用切片的 7 道验证题，eval-set-v1 清单到位后复测
- [ ] **pipe-r10 对照组**（单卡 pod 恢复后）：同数据、同步数、`TEACHER=0`，用于分离 Teacher 的贡献与开销
- [ ] 用 eval-set-v1 复测 pipe-r4 的 checkpoint，确认 held-out 0.988 → 0.914 是噪声还是退步

### H2b pipe-r9 结局（2026-09-18）
- [x] 03:27 启动，数据实际用 `stage1-swe50e-tl50m-v1`（SWE easy 50 + Terminal-Lego medium 50，验证 4 + 4，切片上不再叠加难度筛选）
- [x] 06:07 在第 4/20 步停止：`pass_ratio` 奖励在 SWE 上"什么都不做"的下限中位数 0.936（证据 `pipe-r9/reward-floor-finding.md`）
- [x] 停止时成本核验：171 条 trial、29.25 小时、5.26 美元、计费/实用 1.0、每条 0.031 美元、残留沙箱 0（`runs/pipe-r9/cost-at-stop.json`）；第 1–4 步 checkpoint 保留

### H5 pipe-r11（2026-09-18 06:09 UTC 启动，替代 pipe-r9）
- **目标**：在同一份 100 道题上，用干净的二值奖励重跑 pipe-r9，验证四件事：成本纪律、训练机制、真实的学习信号（按二值解决率）、长度副作用。
- **与 pipe-r9 的唯一训练差异**：`HARBOR_REWARD_MODE=binary`（判分脚本的官方结论：修复前失败的测试全部修好且原有测试全部通过才记 1）。另外两处不影响训练：oracle 阶段改用 `tb21_oracle.yaml`（沙箱生命周期与 `verl-harbor` 应用），cost 阶段已修复。
- **数据**：`gump2049/xDAN-Harbor-Stage1-Tasks` 切片 `stage1-swe50e-tl50m-v1`。训练 100 道（SWE easy 50、Terminal-Lego medium 50，两来源交替），验证 8 道（各 4）。全部 nop/oracle 审计通过，已剔除 eval-set-v1，对 23 个评测做过防污染。base 9B 的分桶解决率：SWE easy 约 33%，Terminal-Lego medium 约 52%。
- **配置**：Qwen3.5-9B 学生（LoRA r32，GPU0）+ Qwen3.8-27B Teacher（整卡 GPU1，显存比例 0.70、单批 4096）；GRPO + OPD 蒸馏（k1，同时用任务奖励）；20 步，每步 4 题 × 8 条，共 80 道题、不足 1 个 epoch，没有题重复出现；并发 16；最多 50 轮、单条 trial 1800 秒；训练前、第 10 步、第 20 步各验证一次；保留最新 10 个 checkpoint。
- **预计**：每步约 24 分钟，全部阶段约 15:30–16:00 UTC 结束；约 700 条 trial，Modal 约 20 美元。
- **命令**：`launch-detached.sh runs/pipe-r11/driver.log "ROUND=pipe-r11 TEACHER=1 TRAIN_STEPS=20 HARBOR_REWARD_MODE=binary bash examples/harbor_opd_rl/run_opd_round.sh"`，代码 b12bd2f（rsync）。
- **判据**（跑完按四条下结论）：
  - [x] 成本：残留 0、计费/实用 ≤ 1.5、每条 ≤ 0.05 美元（`90_cost.sh`）——通过：26.83 美元、1.02、0.032、0
  - [x] 机制：验收 PASS——通过
  - [ ] 学习信号（两层）：
    - 趋势（弱证据）：第 11–20 步的二值解决率高于第 1–10 步。20 步 × 4 题只覆盖 100 道中的 80 道、没有题出现两次，两半是不同的题，差异会被题目难度淹没，只能看方向。
    - 同题前后对比（强证据，训练后补做）：用最终 checkpoint 在第 1–5 步的 20 道题上各重跑 8 条（约 160 条 trial、约 5 美元），与训练时这些题的解决率比较。
    - 另记录每步"组内有对有错"的题数。
  - [ ] 副作用：平均回复长度与轮数不随步数单调上升（pipe-r9 前 3 步 1.54 万 → 2.11 万 token，需确认是抽题造成还是趋势）
- **结果（18:23 UTC）**：验收 PASS、成本通过；学习信号在训练集和 8 道验证题上看不出提升（0.553 → 0.544；3/8 → 5/8 → 3/8）；长度无副作用（2.05 万 → 2.00 万）。详见 `../pipe-r11/report.md`。
- **已知风险**：二值奖励下组内全对或全错的题没有 RL 梯度（pipe-r9 第 1 步按二值算是 0/4）。若前 5 步有信号的题比例 < 25%，下一轮先按难度筛题或加大每步题数，不退回部分分。
- **下一轮待改（本轮不动，保持单变量）**：智能体时限改为任务声明值 × 倍数并让整条 trial 时限覆盖判分；轮数上限 50 → 30 的对比；单卡 pod 恢复后跑 pipe-r10（同配置、`TEACHER=0`）分离 OPD 的贡献。
- **扩规模前的显存评估**：pipe-r11 第 3 步权重更新时 GPU0 学生训练进程占 90 GB（上限 97.9 GB，余量约 8 GB）。更新阶段显存受 `ppo_max_token_len_per_gpu=36864`、梯度检查点、参数与优化器卸载约束，最长轨迹的情况第 1 步已经出现过，本轮安全。但加大每步题数、调高回复长度上限或每批 token 上限之前，要先评估显存；可选办法是降低每批 token 上限，或设置 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 减少碎片。

### H6 轨迹失败的处理：最大限度保留有效工作（用户 2026-09-18 确认）
规则（每组 8 条）：有效 ≥ 4 条照常训练，只在有效轨迹之间比较（GRPO 本就按组内实有样本算均值与标准差，不补假分数）；有效 ≤ 3 条整组废弃、补一道新题；一步里失败比例过高则熔断停训。
- [x] VERL 占位样本缺陷：`padding_utils.construct_minimal_padding_template` 也重建 `teacher_logprobs`/`teacher_ids`（按占位长度补零，损失掩码本为 0）。以补丁文件放在 `patches/verl/`，同步代码后在 pod 上幂等打上，不改上游子模块；CPU 测试复现崩溃路径
- [x] Uni-Agent：`drop_incomplete_groups` 换成 `min_valid_sessions_per_group`（有效数低于它才整组废弃；至少为 2，因为单条样本的组会把原始分数直接当优势）；训练脚本默认取 `ROLLOUT_N` 的一半（8 → 4）
- [ ] 熔断：**未实现**。框架里抛错传不到训练器（`AgentFrameworkRolloutAdapter.generate_sequences` 是 fire-and-forget，`.remote()` 的结果没人取），写了也不会停训。可行方案：框架写停止标记文件，由 `40_train.sh` 轮询后结束训练并记录原因。目前大面积故障的表现是日志里连续出现 "rollout group dropped"，由监控发现
- [ ] 题目隔离（推迟）：20 步不足一个 epoch，每道题本轮只抽一次；先在汇总里按题记录基础设施故障次数
- [ ] 部署时机：pipe-r11 跑完再同步（它的续训阶段会重新导入代码，中途替换会让同一轮前后行为不一致）；测试在 pod 的独立目录里跑，不碰运行中的源码

### H7 S1 期间发现、待修
- [ ] VERL 文件记录器写到 `src/uni-agent/<project>/<experiment>.jsonl`，且以覆盖方式打开；实验名都是 `pipe-train`，每一轮会覆盖上一轮（pipe-r11 的逐步指标文件已被 S1 覆盖，wandb 与训练日志里仍有）。修法：训练脚本把 `VERL_FILE_LOGGER_PATH` 设到 `${RUN_ROOT}/metrics.jsonl`。S1 跑完再改，避免中途改动。
- [ ] 训练日志里不再出现每步 `step:N - ...` 汇总行（控制台输出被缓冲），监控改读上面的逐步指标文件。

### H3 本轮的判据（跑完按这四条下结论，缺一不可）
- [ ] 成本：泄漏沙箱 0、计费与实际时长之比 ≤1.5、每条 trial ≤0.05 美元（`90_cost.sh` 自动核验）
- [ ] 机制：验收 PASS（阶段全过、指标有限、续训连续、adapter 变而 base 不变）
- [ ] 学习信号：训练集 reward 在同来源的第 2 epoch 高于第 1 epoch（比较第 11–15 步与第 1–5 步、第 16–20 步与第 6–10 步）
- [ ] 副作用：轨迹长度不随步数单调上升（Tinker 线出现过训练后暴涨 7 倍导致退步）

### H4 明确不追求的
- [ ] Terminal-Bench 2.1 分数提升：需要 500 题以上、200 步以上，本轮做不到
- [ ] held-out 绝对分数的结论：现有 7 道题训练前已 0.988（饱和），要等共享评估集

## 阶段 G：路线 3 DSH 进沙箱
- [ ] 重启 ingress 路线：专用 hostname / tunnel / registry 镜像；agent 切 DSH，其余训练链路不变

## 约束
- 每步只留一份证据目录，失败现场不覆盖
- GPU 启动前 `nvidia-smi` 确认空闲，不停别人的进程
- 每次 push 过 Ruff 双门
