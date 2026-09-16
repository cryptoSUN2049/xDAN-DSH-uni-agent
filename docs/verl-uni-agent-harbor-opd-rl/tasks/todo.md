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
- [ ] `examples/harbor_opd_rl/train_tb21_lora_smoke.sh`（单机不用 ray job submit，Modal 凭据走 /root/.modal.toml）跑 1 步 GRPO/LoRA，r1 运行中 `runs/tb21-rl-r1/`
- [ ] 核梯度非零、checkpoint 可独立 reload
- 证据：`runs/tb21-rl-r1/`

## 阶段 E：接回本分支目标
- [ ] Teacher OPD 接线换到 harbor task（原生 hybrid recipe）
- [ ] 评估口径：固定 TB 2.1 子集 held-out，训练题与评测题隔离

## 约束
- 每步只留一份证据目录，失败现场不覆盖
- GPU 启动前 `nvidia-smi` 确认空闲，不停别人的进程
- 每次 push 过 Ruff 双门
