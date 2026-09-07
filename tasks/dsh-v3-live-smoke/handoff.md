# dsh-v3-live-smoke 交接

## 1. TL;DR

- 工作区 `.Codex/worktrees/dsh-v3-live-smoke`；分支 `worktree-dsh-v3-live-smoke`。
- M0 `a197ead` 已整合并推送 dsh-adapter，PR #1 五项 CI 成功。
- M1 CPU 实现提交 `27f7efa`、`3220216`；208 项聚焦测试通过，覆盖率 87%–99%。
- 真实 smoke **0/8**，训练更新 **0**；现在不购买 GPU。
- 下一步：Linux 完整依赖验证、恢复 DSH source/runtime、独立停机方案，然后确认短时 GPU。

## 2. 本轮交付物

| 文件 | 行数 | 说明 |
| --- | ---: | --- |
| `README.md` | 117 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/design.md` | 229 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/progress.md` | 63 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/runbook.md` | 108 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/verification.json` | 77 | 交接、验证或操作文档 |
| `examples/dsh/ops/README.md` | 113 | 交接、验证或操作文档 |
| `examples/dsh/ops/audit_v3_live_smoke.py` | 299 | 八类证据与 TQ 读回审计 |
| `examples/dsh/ops/run_v3_live_smoke.py` | 777 | prepare/runtime预检/监督/封存 |
| `examples/inference/parallel_infer_verl.py` | 621 | 严格 flags、UID 预登记及实际读回 |
| `pyproject.toml` | 114 | 固定 Ruff first-party 分类 |
| `tasks/dsh-v3-live-smoke/handoff.md` | 95 | 交接、验证或操作文档 |
| `tasks/dsh-v3-live-smoke/notes.md` | 62 | 交接、验证或操作文档 |
| `tasks/todo.md` | 72 | 交接、验证或操作文档 |
| `tests/uni_agent/deployment/test_host_runtime.py` | 133 | CI import 分类 |
| `tests/uni_agent/framework/test_dsh_episode_workspace.py` | 168 | CPU 回归测试 |
| `tests/uni_agent/tasks/test_dsh_v3_live_smoke_audit.py` | 515 | CPU 回归测试 |
| `tests/uni_agent/tasks/test_dsh_v3_live_smoke_ops.py` | 789 | CPU 回归测试 |
| `tests/uni_agent/tasks/test_parallel_infer_verl_evidence.py` | 451 | CPU 回归测试 |
| `tests/uni_agent/test_rlinsight_adapter.py` | 131 | 旧 VERL fixture 兼容 |
| `uni_agent/framework/task_runner.py` | 331 | episode 新目录与可信文件复验 |

操作见 `docs/dsh-v3-live-smoke/runbook.md`，精确测试范围与 hash 见
`docs/dsh-v3-live-smoke/verification.json`。旧跨仓记录来源和全局 P0–P6 限制
仍由 `docs/dsh-adapter/project-status.md` 保留，不把旧训练追认为新结果。

## 3. 设计约束

- 用户已批准 CPU 实现及手工 worktree；不得重新询问相同许可。
- 代码只在本 worktree 修改；主目录 dsh-adapter、main 未合并本轮 M1。
- 固定 VERL `483b8a009ba3a97563edee3a19887e4862b8094a`；不升级绕过旧 API。
- 使用真实 Gateway/Task/verifier/token/TQ；不伪造 session、fresh receipt 或 trainer consumption。
- source bundle 保持 blocked；M1 `training_eligible` 始终 false，eligible/reward=0 不算通过。
- episode 新目录和 hash 检查不是同 UID containment；不能宣称已完成 P6。
- GPU/模型付费独立确认；进程组 timeout 不是 Pod 停费。Pod 不放 RunPod/GitHub key。

## 4. 已踩坑 / 已发现的真实行为

- Task metadata 不能覆盖 workdir，须在 operator-owned task_runner seam 设置。
- inference global_steps=null；TQ session_id 是 rollout index，真实 Gateway ID在dump header。
- 多 chain 共享最终 receipt，读回取最大 chain index；新 auditor 逐条验证 token dtype/shape/值。
- receipt 的 fresh bool 不代表属于本轮；审计额外核对 issued_at、身份和唯一性。
- admission 拒绝可能早于 token dump，必须记 incomplete，不能放松准入。
- `load_live_scenarios` 直接打开 path，显式 repository_root 不会替相对 registry 解引用。
- coverage dotted module source 导致 Torch/NumPy 二次初始化；使用目录 source，详见 notes.md。
- 运行包 metadata 名是 `TransferQueue`，manifest 键 `transfer-queue` 仅为合同字段。
- 旧 DSH pin 仍不可取得；新 runtime manifest 没有自动生成可信来源或可复现构建证明。

## 5. 下一里程碑任务清单

- [x] M0 旧 VERL/Ruff 修复与 CI。
- [x] 八条冻结输入、命令 dry-run、独立目录、严格推理证据。
- [x] 运行监督、输入复验、离线审计及产物 SHA 封存。
- [x] 208 项聚焦测试、独立 review 修复、四模块 coverage≥80%。
- [ ] 推送同名新分支并创建 scoped Draft PR，回填实际 URL。
- [ ] 完整 Linux 依赖 CI；本机未安装 vLLM，不能声称全仓绿。
- [ ] 恢复旧 DSH source/Linux carrier，或明确批准冻结可复建新 baseline。
- [ ] 核准模型/TransferQueue 来源，验证独立 Pod 截止停机/存储删除。
- [ ] 再确认 GPU 预算，执行八类真实 smoke；之后才扩充/校准/训练/paired holdout。

## 6. 分支 / 部署状态

实现提交截至 `3220216`；当前 HEAD 另查 git log。M1 两实现提交尚待同名远端 push，本任务不合并 main。
父分支 PR #1：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/1 。
新 PR 拟以 dsh-adapter 为 base，保持可审查范围；CI backend 只对 main PR 自动触发，
故不能将父分支 M0 的 CI 成功当作 M1 验证。

CPU venv `/private/tmp/uni-agent-cpu-20260907`，Python 3.12.12。
聚焦回归 208 passed；本机全仓尝试 744 passed / 7 failed / 2 skipped。
6 个缺 vLLM/Pillow 失败在未改动 a197ead 基线复现；另一次 localhost 502 去代理后
基线通过。原始测试日志经脱敏，仅留临时目录；仓库只提交摘要与报告 hash。
没有部署、GPU 创建、模型调用或本轮 optimizer update。

## 7. 冷启动 checklist

1. 读本文件、progress.md、runbook.md、notes.md、tasks/todo.md。
2. 核对 git status / HEAD / worktree / submodule，检查实际 PR 与 CI，保护在途文件。
3. 使用临时 CPU venv、`PYTHONPATH=.:verl`、HF_HUB_OFFLINE=1；pytest 使用 --tb=short。
4. 用 verification.json 中五个文件重跑聚焦范围；coverage 按目录配置。
5. 若跑网络型本地测试，为 localhost 禁用代理；失败日志不要暴露整个进程环境。
6. 按第5节推进 Linux/runtime/watchdog，不重复数据造表，不把合成证据当真实 smoke。
7. 每次 push 前执行 ruff check . 和 ruff format --check .；保持 Draft直到实际验收。
