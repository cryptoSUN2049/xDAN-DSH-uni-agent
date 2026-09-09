# Resident memory validation r1：构造失败，未进入 A/B

真实运行固定代码 `4168b628f3a2ff4c301dcffb60f016f8ecb770f2`，checkout `/workspace/rebuild/uni-agent-memory-resident-r1`，run `/root/runs/memory-resident-val-r1`。本报告为只读调查与终态后 CPU 审计，不修改远程代码或重启 GPU。

## 实际终态

监督 child `185194`，exit `-15`，540.012 秒。父线程针对已证实失败停止本 run 拥有的进程组；审计时 GPU compute-apps 为空。旧 run-manifest 仍为 `running`（外部终止未执行 launcher 最终状态更新），保留原件，不能据此称运行成功或继续活跃。

A/B stage dump **0**、crosswalk **0**。专用 `audit_memory_training` 在固定远程 checkout、既有 venv、CUDA_VISIBLE_DEVICES 为空条件下执行，exit `1`，`passed=false`、`consumption_verified=false`，消费组和行均为 **0**。无学生表现与实际 A/B policy version 可评价。

## 根因与准确奖励路径

`AgentFrameworkWorker pid=189569` 经 `entry.build_agent_framework → NativeMemoryFramework.from_config → GatewayAgentFramework.from_config → NativeMemoryFramework.__init__` 构造失败：`Memory terminal credit cannot use reward workers`。因此没有执行 DSH stage。

真实配置显示 `reward.custom_reward_function.path=None`、`reward.num_workers=8`。固定 VERL `main_ppo.py:130` 将 `trainer.get_reward_handles()` 无条件传入 manager；`trainer_base.py:385` 返回 reward loop 默认 handles。新 Native 构造器把 handles 非空当作实际外部奖励替换，从而提前拒绝。

实际 Gateway 奖励分支在 `_execute_gateway_stage`，并不存在名为 `_apply_verifier_reward` 的独立方法：

- `framework.py:1076` 严格要求 TaskResult.verifier_reward 存在；1079 拒绝 handles 与 custom reward 同时启用的替换。
- 1120 只有 handles 且 custom reward 配置同时存在，才优先调用 reward worker。
- 1127 TaskResult.reward 非空时走 `agent_runner`；随后才是缺失 runner reward 的 worker fallback。

所以“收到默认 handles”和“实际走 reward worker”是不同条件；本次错误属于 Native 工程构造适配，不能归因于模型、任务难度、DSH 策略或 GPU 安装。

## 最小修复建议

Native 专属入口继续拒绝 custom reward 配置；对上游默认 handles 显式忽略或清除，保证 Native 无 worker fallback。保持 require_verifier_reward、原训练 verifier、严格冻结与 credit 门不变。补真实 factory 的非空默认 handles 正例、custom reward 反例、verifier 缺失仍拒绝；重新启动必须新 run identity。修复实现由父线程分配，本报告不改变任何门限。

完整监督、原始日志哈希、选取日志行与专用消费结果见 [JSON 证据](memory-resident-val-r1-failure.json)。远端另保留 `consumption-audit.json` 和 `failure-summary.json`。
