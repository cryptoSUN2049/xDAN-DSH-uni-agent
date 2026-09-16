# Handoff：verl-uni-agent-harbor-opd-rl

更新：2026-09-16 11:00 UTC。

## 0. 当天路线变更（先读）

用户拍板走**上游 Harbor 内置 agent 路线**：`uni_agent/tasks/harbor` + Harbor CLI + `harbor_env: modal` + terminus-2，在 Terminal-Bench 2.1 上打通 Gateway rollout → verifier reward → VERL LoRA GRPO。DSH-in-sandbox（Controller / Cloudflare ingress / registry 镜像）暂停。三步路线：① terminus-2 训练打通 → ② DAPO + OPD 联合更新 → ③ DSH 进沙箱。验收看 wandb（project `xDAN-Verl-Uni-agent-Harbor-rl-opd`，entity `xdan-ai`）。

已证明：oracle 2/2；Gateway rollout 2/2 带 token 轨迹；训练 r2/r3 机制闭环（rollout → 更新 → `global_step_N` checkpoint）但 22 条 rollout reward 全 0 → 零梯度。原因是 4B 在 30 轮内解不出 TB 题。对策：`HARBOR_REWARD_MODE=pass_ratio`（verifier CTRF 部分得分，opt-in，5 单测）。

**全流程脚本化驱动已跑通并验收 PASS（2026-09-16 16:47 UTC）**：`examples/harbor_opd_rl/run_tb21_pipeline.sh` + `stages/00_env … 80_acceptance.sh`（README 在同目录）。pipe-r1 证据在 `docs/verl-uni-agent-harbor-opd-rl/pipe-r1/`（acceptance.json / verdict.json / delta.json / report-tables.md）。关键数字：3 步 colocate_async 训练 + 1 步 resume；grad_norm 0.020 / 0 / 0.015 / 0；504/504 adapter 变、399/399 base 不变；wandb 与日志逐步一致。路线 ① 机制层完成，下一步是 pipe-r2：stage1 数据 20 题、并发 16、n 8、held-out 开启，然后 DAPO，再路线 ②。

冷启动：读 `tasks/todo.md`（含验收口径与三步路线）→ `tasks/memory.md` 末节 → `examples/harbor_opd_rl/README.md` → 177 上 `ls runs/`。历史逐轮记录保留在同目录 `handoff-history.md`；持久决策在 `memory.md`；探针过程在 `notes.md`。

## 1. TL;DR

- 分支/worktree：`verl-uni-agent-harbor-opd-rl`，HEAD `0115008`，已推送 origin 同名分支，领先 main 235 提交、落后 0，工作区干净。
- 状态：代码层与单卡组件层验证闭环（Teacher 接线、Modal 生命周期、4B LoRA 真实更新/导出、native checkpoint 独立恢复），**端到端 Harbor RL / OPD 正式训练一次都没有跑起来**。
- 远端 GPU 机 2026-09-16 07:21 UTC 观测：GPU 空闲（0 MiB / 97887 MiB，无 compute-app），SSH 可连。其他项目的 vLLM 推理作业已结束。
- 远端源码快照是 `89ebca9`，比 HEAD 少约 10 个提交（含 b02deb8 入口修复、ingress/preflight 测试、environment_backend 15 行改动），启动训练前必须同步。
- **GPU venv 已丢失**：之前的环境建在 pod 本地 `/tmp`，pod 重建后没了；`/workspace/.../envs/ua-verl-py312-vllm023` 只是 6.8M 空壳。已把 245 包 freeze 收进仓库 `deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt`，并继承 MetaRSI 的 uv 管理办法写成 `docs/verl-uni-agent-harbor-opd-rl/uv-runbook.md` + `deployment/bootstrap/uv-lane-bootstrap.sh`。
- 下一步唯一目标：让一次真实 Harbor RL 跑通并留日志。顺序见第 5 节。

## 2. 本轮交付物（累计，路径为准）

代码：
- `uni_agent/framework/{entry,framework,memory_chain}.py`：Teacher client 传递、逐 token 评分、TQ 消费合同。
- `uni_agent/tasks/harbor_dsh/{environment_backend,modal_environment,executor,isolated_trial,worker,worker_http}.py`：Modal 可选后端、隔离 Trial、资源清理确认。
- `deployment/services/harbor_modal_ingress.py`、`harbor_run_controller.py`：Controller 公网入口与任务准备。
- `deployment/checks/fsdp_lora_merged_export.py`、`harbor_modal_cleanup_smoke.py`：真实 GPU / Modal 组件探针。
- `examples/harbor_opd_rl/{base,rl,opd,hybrid}.yaml` + `launch.py`：原生训练 recipe 与入口。
- `verl` 子模块固定 `a9f2985`；Uni-Agent 上游 `91618ea`。

文档与证据（`docs/verl-uni-agent-harbor-opd-rl/`）：
- `acceptance-status.md`：验收矩阵，每行区分"已有证据 / 未完成"。
- `modal-blocker-audit.md`：撤回"Modal 域名是卡点"归因的证据表。
- `integration-design.md`、`training-recipes.md`、`teacher-bridge-review.md`、`modal-backend-design.md`、`modal-ingress-design.md`、`incremental-lora-sync-design.md`、`async-lora-validation.md`。
- JSON 证据：`gpu-preflight.json`、`modal-provider-smoke-r2.json`、`fsdp-lora-export-r{1,2}.json`、`fsdp-lora-save-r3.json`、`fsdp-lora-resume-r4.json`。

## 3. 设计约束（铁律）

- Uni-Agent owns Agent/Task/Gateway/trajectory admission/TQ；VERL owns optimizer 与同步；Harbor owns verifier；Modal 只做任务 sandbox。不切换 Tinker trainer，不引入第二套 agent loop。
- Teacher 概率不是任务成功判定。Teacher 整组失败不得提交部分 trajectory。生成版本、行为 logprobs、工具 mask 必须保留。失败清理确认不得制造 reward。
- 所有修改留在本 worktree；不覆盖其他工作树或 SkyRL / metarsi 环境；不停止别的项目进程。
- 每次 push 前全库 `ruff check .` 与 `ruff format --check .` 双门。
- 组件通过、测试通过、进程启动都不能计为训练闭环；只有日志明确显示失败阶段，才能报告该阶段为卡点。

## 4. 已踩坑 / 已发现的真实行为

环境与远端：
- **SSH 端口已变**：现为 `ssh root@157.157.221.177 -p 12063 -i ~/.ssh/id_ed25519`（2026-09-16 13:10 pod 再次重建，历史端口 12524 → 30284 → 12063；重建后 `/root` 下 Modal/wandb 凭据需重拷，新 host key 用 `StrictHostKeyChecking=accept-new`）。RunPod pod 重建后端口会变，每次先核。历史上直连偶发 banner timeout，可用 ssh master socket 复用连接；观测失败不等于作业终止。
- 远端独立根 `/workspace/verl-uni-agent-harbor-opd-rl/{src,envs,cache,runs}`。`src/uni-agent` 是 rsync 副本，**不是 git 仓库**，版本以 `runs/source-manifest-<sha>.json` 为准；目前是 89ebca9。
- 远端 venv `envs/ua-verl-py312-vllm023`（**当前为空壳，需按 uv-runbook 重建到新目录**）：uv 0.9.0 建，Python 3.12.3（`/usr/bin`），Torch 2.11.0 / vLLM 0.23.0 / Transformers 5.8.0 / Ray 2.54.1 / peft 0.18.1。这是 UA 测试 lane，与 VERL uv.lock（vLLM 0.24 / Transformers 5.9）和 MetaRSI 训练 lane（py311 / Torch 2.10 / vLLM 0.18.1 / Transformers 4.57.6）都不同，不能混称统一锁。完整训练前须单独验锁。
- 远端 FUSE 不支持 chown，rsync 用 `-rltz`。`/workspace` 是 RunPod Network Volume，df 显示底层共享容量（2.1P）不是购买容量。
- 模型只有 `/workspace/models/Qwen3-4B-1cfa9a7`；9B Student / 27B Teacher 未下载。
- uv 管理办法已继承到本项目 `docs/verl-uni-agent-harbor-opd-rl/uv-runbook.md`（来源 MetaRSI `docs/main/uv-runbook.md` 与 `uv-training-design.md`）。核心规则：`UV_CACHE_DIR=/workspace/.cache/uv`；先校验 `sys.prefix`、CUDA 运算和关键 import 再用；venv 失效时新建恢复目录，不覆盖旧环境；`uv pip` 显式版本可能被 `tool.uv.override-dependencies` 覆盖，lock 外 overlay 用 `--no-config` 隔离并实际 `pip check`。

代码：
- 原生 Teacher 返回全序列 [S,K] 且已 left-shift；首 response 用 prompt_len-1 行，末 dummy 不能再 shift。
- Teacher TQ 用 ragged_idx=1；缺列不得被 shared_keys 静默丢弃。
- 非 naive checkpoint path 未传 adapter metadata，未 merge 时可能只导出 base；recipe 已显式 merge=true。当前是 merged 完整权重同步，不是高性能增量 adapter 同步。
- FSDP 探针 `use_orig_params=True` 与 recipe 默认 False 不一致会前向断言失败；r1 失败 JSON 保留。
- separate_async 训练与推理分卡；Teacher 必须独立池：纯 separate RL 至少 2 GPU 角色，separate+OPD 至少 3。单卡只能做 colocated 组件验证。
- 历史 Controller preflight JSON 里 `actual_gateway_used=false`、`mock_ssh_returncode=0`，不是真实 Gateway 连通证据。
- `deployment/versions/harbor-execution-image.json` 为 `registry_published=false`；本地 image ID 不能当 registry manifest digest。

## 5. 下一里程碑任务清单（按顺序，每步只留一份证据）

**2026-09-16 端到端前置条件核查**（两条路径都需要操作者提供资产，代码侧无法自行补齐）：
- Docker 路径（Harbor 容器跑在 Mac，GPU 通过 SSH 反向端口连 controller）：本机有 Docker Desktop 但 daemon 未启动；177 上没有 docker。
- Modal 路径：需要本项目专用公网 HTTPS Gateway hostname + Cloudflare named tunnel 凭据（本机已有 8 条其他项目 tunnel，按约束不复用）+ 发布到 registry 的 DSH 镜像（`registry_published=false`）。本机 modal profile `shootime007` 可用。
- 两条路径都需要：RunSpec（2 小时 deadline、端口、token 文件）、`prepare_t2_task` 冻结任务、`prepare_m2_training` 生成 launch.json。流程模板见 `docs/harbor-modal-integration/harbor-m2-manual-runbook.md`。


- [x] 同步远端源码到 `68b45f3`，`runs/source-manifest-68b45f3.json` 已写。
- [x] lane 重建到 `envs/ua-verl-py312-vllm023-ws1`：激活证明通过，freeze sha256 与快照及历史 gpu-preflight 完全一致（`uv-lane-ws1-manifest.json`）。
- [x] GPU smoke 通过（`gpu-smoke-ws1.json`）：CUDA 反向、vLLM/ray/transformers/TQ/verl/uni_agent/peft import。原 `gpu_smoke.py` 要求的 flash_attn 不在快照里、历史验证也未用，已排除并在证据里注明。
- [ ] 发布 DSH 执行镜像并回填 `harbor-execution-image.json` 的 image@digest（不依赖 GPU，先做）。
- [ ] 用 `prepare_t2_task → 冻结 RunSpec/policy → prepare_m2_training` 生成真实 launch.json / train.parquet。
- [ ] 用真实 4B 模型跑合并后入口的 `--preflight-only`，核有效 rows 与绝对 step/epoch。
- [ ] 从真实 Modal sandbox 发起受控 Gateway 请求，保留 DNS/TLS/HTTP/session 路由结果。
- [ ] 跑完整 Trial + verifier，拿到真实 reward。
- [ ] 单卡 colocated 跑 2 步真实 Harbor RL，留 group/receipt/TQ/梯度/最终 checkpoint。
- [ ] 以上通过后再排双卡 separate_async 和三角色 OPD 验收；9B 复验另立节点。

## 6. 分支 / 部署状态

| 项 | 值 |
|---|---|
| 本地 worktree | `.Codex/worktrees/verl-uni-agent-harbor-opd-rl` |
| HEAD | `0115008`，origin 同步，无 PR |
| 相对 main | +235 / -0，merge-base `d723b5f` |
| 远端 | `root@157.157.221.177:12063`，RTX PRO 6000 Blackwell 96GB，2026-09-16 空闲 |
| 远端源码 | 68b45f3（与 push 同步） |
| 远端 venv | `envs/ua-verl-py312-vllm023-ws1`，2026-09-16 重建并通过激活证明 |
| 最近 GPU 证据 | resume-r4 passed，scope=single_gpu_native_export_component |
| 正式训练日志 | 无 |

## 7. 冷启动 checklist

1. 读本文件 → `memory.md` → `acceptance-status.md` → `modal-blocker-audit.md`。
2. `git status && git log -3 --oneline && git rev-list --count origin/verl-uni-agent-harbor-opd-rl..HEAD`，核 HEAD 与 push 状态。
3. SSH 远端：`nvidia-smi`、`ps -eo pid,cmd | grep -E "python|ray"`、`ls -lt runs | head`。先查有没有在跑的进程和新证据，再动手；不重复启动、不停别人的进程。
4. 核远端 `runs/source-manifest-*.json` 最新 sha 与 HEAD 是否一致，不一致先同步。
5. 读本目录上级 `uv-runbook.md` 再激活环境；空壳 venv 先重建。
6. 从第 5 节第一个未勾选项开始。用户已授权实施、GPU 验证和按节点 commit/push，勿重复询问。
