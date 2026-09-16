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
- [ ] 核梯度非零（r2 为 0，待 r3 easy 题）、checkpoint 可独立 reload
- 证据：`runs/tb21-rl-r1/`

## 总路线（用户 2026-09-16 明确顺序）
1. **terminus-2 训练完整打通**：阶段 A–D，加 wandb（project `xDAN-Verl-Uni-agent-Harbor-rl-opd`，entity `xdan-ai`），多步训练、checkpoint reload、held-out 评估。
2. **DAPO + OPD 联合更新（tinker 方案）**：把 tinker-cookbook 里的 RL/OPD/hybrid 逐 token Teacher 评分接到 harbor task 的轨迹上；本分支已有的 `examples/harbor_opd_rl/{opd,hybrid}.yaml` 与 Teacher→TQ→loss 接线复用；DAPO 侧用 VERL 原生 clip-higher / dynamic sampling / token-mean。
3. **DSH harness 接入沙箱**：把 agent 从 terminus-2 换回 DSH，届时才需要沙箱回连 Gateway（ingress / tunnel），复用本分支已写好的 Controller + Modal ingress 代码。

## 阶段 E：路线 1 收尾
用户要求（2026-09-16）："现在不关注结构，但要确保全流程完整打通"，且"全流程跑通应通过脚本化驱动"。驱动脚本：`examples/harbor_opd_rl/run_tb21_pipeline.sh`（env → data → oracle → rollout → train → delta → resume → summary，每阶段 `PASSED` 标记 + `pipeline-summary.jsonl`，可 `FROM_STAGE=` 续跑），最终 `summary/verdict.json` 给出 `full_pipeline_mechanically_closed` 与 `learning_signal_observed` 两个布尔。
- [ ] r3 结束后：`PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r1 bash examples/harbor_opd_rl/run_tb21_pipeline.sh` 一条命令跑完，verdict 两个布尔都为 true
验收口径（用户 2026-09-16）：按 wandb 面板实际曲线分析，不只看日志。关注 `critic/score/mean`（reward 均值）、`critic/score/std` 或组内 0/1 混合比例（advantage 是否非零）、`actor/pg_loss`、`actor/grad_norm`（非零且有限）、`response_length/mean`、`timing_s/gen` 与 `timing_s/update_actor`、`val/test_score`（held-out）。
- [ ] wandb 接入（脚本已改：`trainer.logger=['console','file','wandb']`，凭据在 177 `/root/.netrc`），下一次训练起跑验证面板有 reward / grad_norm 曲线
- [ ] 多步训练（≥5 步）+ checkpoint reload + 固定 held-out 子集评估；训练题与评测题隔离
- [ ] r3：TB 2.1 仅 4 题标 easy（fix-git / cobol-modernization / prove-plus-comm / overfull-hbox），已做成 `data/easy/harbor_tb21-easy-tasks.parquet`；n=4、3 步，看 `critic/score/std` 是否离开 0

## 阶段 F：路线 2 DAPO + OPD
- [ ] 复核 tinker-cookbook-opd-rl 的 harbor_opd_rl.py 评分合同，对齐到 harbor task 轨迹（token ids / action mask 来自 Gateway npz）
- [ ] 27B Teacher 服务化（独立 GPU 角色）；单卡先用 4B 自评做接线冒烟
- [ ] hybrid loss（RL + OPD 加权）在 harbor 轨迹上非零梯度证据

## 阶段 G：路线 3 DSH 进沙箱
- [ ] 重启 ingress 路线：专用 hostname / tunnel / registry 镜像；agent 切 DSH，其余训练链路不变

## 约束
- 每步只留一份证据目录，失败现场不覆盖
- GPU 启动前 `nvidia-smi` 确认空闲，不停别人的进程
- 每次 push 过 Ruff 双门
