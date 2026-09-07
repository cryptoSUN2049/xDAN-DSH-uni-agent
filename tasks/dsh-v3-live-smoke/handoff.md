# dsh-v3-live-smoke 交接

## 1. TL;DR

- 工作区 `.Codex/worktrees/dsh-v3-live-smoke`；分支 `worktree-dsh-v3-live-smoke`。
- M0 `a197ead` 已整合并推送 dsh-adapter，PR #1 五项 CI 成功。
- M1 CPU 实现提交 `27f7efa`、`3220216`；208 项聚焦测试通过，覆盖率 87%–99%。
- 真实 smoke **0/8**，训练更新 **0**；现在不购买 GPU。
- 下一步：Linux 完整依赖验证、恢复 DSH source/runtime、独立停机方案，然后确认短时 GPU。

新增学习与调研入口：[Harbor 与 Agent RL 专题 HTML](../../docs/dsh-v3-live-smoke/harbor-agent-rl-guide.html)。
包含官方新闻、教程和开源桥接核查；仅文档交付，DSH × Harbor × VERL 尚未实跑。
整体方案入口：[Uni-Agent 系统架构与 Modal / Harbor 集成](../../docs/dsh-v3-live-smoke/uni-agent-system-plan.html)。
原总体 Pipeline HTML 位于 DSH sibling docs/master，本页已保留来源与旧规划边界。

## 2. 本轮交付物

| 文件 | 行数 | 说明 |
| --- | ---: | --- |
| `README.md` | 120 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/design.md` | 229 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/uni-agent-system-plan.html` | 62 | 当前整体入口；两种环境路径、Modal/Harbor接线、接口与H0–H4验收提案 |
| `docs/dsh-v3-live-smoke/harbor-agent-rl-guide.html` | 184 | Agent RL 科普、长流程、5 篇官方新闻、开源集成证据与接入提案 |
| `docs/dsh-v3-live-smoke/progress.md` | 70 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/runbook.md` | 108 | 交接、验证或操作文档 |
| `docs/dsh-v3-live-smoke/verification.json` | 77 | 交接、验证或操作文档 |
| `examples/dsh/ops/README.md` | 113 | 交接、验证或操作文档 |
| `examples/dsh/ops/audit_v3_live_smoke.py` | 299 | 八类证据与 TQ 读回审计 |
| `examples/dsh/ops/run_v3_live_smoke.py` | 777 | prepare/runtime预检/监督/封存 |
| `examples/inference/parallel_infer_verl.py` | 621 | 严格 flags、UID 预登记及实际读回 |
| `pyproject.toml` | 114 | 固定 Ruff first-party 分类 |
| `tasks/dsh-v3-live-smoke/handoff.md` | 125 | 交接、验证或操作文档 |
| `tasks/dsh-v3-live-smoke/notes.md` | 62 | 交接、验证或操作文档 |
| `tasks/todo.md` | 110 | 交接、验证或操作文档 |
| `tasks/lessons.md` | 42 | 补充本地适配与生态能力、任务格式与训练连接的区分 |
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
- Harbor 上游当前 Task 与本地一致，仍是 eval-only；Gateway 教程未端到端验收。
  但生态存在训练代码：VERL #6444 closed/unmerged，rLLM 有可组合 VERL 连接，
  官方推荐的 Tinker recipe 有完整训练循环。它们不构成本项目训练实跑证据。
- Harbor 多步骤默认共享环境但开启新对话，resume 需要 Agent capability；
  rLLM Harbor 0.3.0 与多步骤首次要求 ≥0.5.0 存在版本差异，不能直接套用。
- HarborTask 绕过 Uni-Agent Agent registry；agent.name=dsh 不会自动接入 DshAgent。
  现有 dsh-strict-audit 只接受 dsh_architecture，须设计 bridge 与审计合同适配。
- HarborTask 的 sandbox=None；Harbor 路线通过 harbor_env: modal 管理环境，不能
  再叠加 Uni-Agent ModalSandbox。DSH bridge 应只包装已有环境 exec/file 能力。
- endpoint 环境变量不建立网络通路；Modal 内 DSH 必须实际访问带 session 路由的
  Gateway。现有严格 episode staging 限定 local，不能直接切 provider 追认为 v3 已验收。

## 5. 下一里程碑任务清单

- [x] M0 旧 VERL/Ruff 修复与 CI。
- [x] 八条冻结输入、命令 dry-run、独立目录、严格推理证据。
- [x] 运行监督、输入复验、离线审计及产物 SHA 封存。
- [x] 208 项聚焦测试、独立 review 修复、四模块 coverage≥80%。
- [x] 推送同名新分支并创建 Draft PR #2：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/2 。
- [x] Harbor 入门与集成专题 HTML、新闻阅读、上游代码核查及交接入口。
- [x] 当前整体方案 HTML 与 README / progress / 专题互链；Modal + Harbor 仍为设计提案。
- [ ] 若推进 Harbor 实现：固定版本、选单 CPU 任务验证 oracle；呈现 DSH bridge
  具体设计后，依据实现范围取得批准。当前 HTML 请求只授权调研与文档。
- [ ] 完整 Linux 依赖 CI；本机未安装 vLLM，不能声称全仓绿。
- [ ] 恢复旧 DSH source/Linux carrier，或明确批准冻结可复建新 baseline。
- [ ] 核准模型/TransferQueue 来源，验证独立 Pod 截止停机/存储删除。
- [ ] 再确认 GPU 预算，执行八类真实 smoke；之后才扩充/校准/训练/paired holdout。

## 6. 分支 / 部署状态

实现提交截至 `3220216`；当前 HEAD 另查 git log。M1 两实现提交和文档已推送同名远端，本任务不合并 main。
父分支 PR #1：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/1 。
新 Draft PR #2：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/2 ，base=dsh-adapter；CI backend 只对 main PR 自动触发，
故不能将父分支 M0 的 CI 成功当作 M1 验证。

CPU venv `/private/tmp/uni-agent-cpu-20260907`，Python 3.12.12。
聚焦回归 208 passed；本机全仓尝试 744 passed / 7 failed / 2 skipped。
6 个缺 vLLM/Pillow 失败在未改动 a197ead 基线复现；另一次 localhost 502 去代理后
基线通过。原始测试日志经脱敏，仅留临时目录；仓库只提交摘要与报告 hash。
没有部署、GPU 创建、模型调用或本轮 optimizer update。

Harbor 专题以独立本地文档提交交付，本轮未推送；具体提交查 git log/status。
HTML 已核查桌面 1440×1000、手机 390×844，无页面横向溢出；
内部锚点与本地来源路径通过检查，独立内容审阅的 3 项问题已修正。
整体方案为另一独立本地文档提交，本轮同样未推送。8 章节、9 锚点、24 本地路径
已验证，桌面/手机预览与目录跳转通过；独立审阅确认沙箱归属与 bridge 接线。

## 7. 冷启动 checklist

1. 读本文件、progress.md、runbook.md、notes.md、tasks/todo.md。
   先看整体方案 HTML 定位职责；Harbor 相关再读专题，核实动态 PR 状态和依赖。
2. 核对 git status / HEAD / worktree / submodule，检查实际 PR 与 CI，保护在途文件。
3. 使用临时 CPU venv、`PYTHONPATH=.:verl`、HF_HUB_OFFLINE=1；pytest 使用 --tb=short。
4. 用 verification.json 中五个文件重跑聚焦范围；coverage 按目录配置。
5. 若跑网络型本地测试，为 localhost 禁用代理；失败日志不要暴露整个进程环境。
6. 按第5节推进 Linux/runtime/watchdog，不重复数据造表，不把合成证据当真实 smoke。
7. 每次 push 前执行 ruff check . 和 ruff format --check .；保持 Draft直到实际验收。
