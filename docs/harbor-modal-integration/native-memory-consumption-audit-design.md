# Native memory trainer consumption audit

状态：已授权独立 CPU 实施；不修改 framework、recipe 或训练回执。

API：`audit_memory_training(run_root, *, memory_root, expected_run_id) -> dict`。
CLI：`python -m examples.dsh.capabilities.audit_memory_training RUN_ROOT --memory-root OPERATOR_ROOT --run-id ID --output REPORT`。

输入：operator 根下 `groups/*/crosswalk.json`、原始 stage JSON/NPZ/receipt/trace/frozen 文件、相邻 `submission.json`、trainer `rollouts/*.jsonl` 和 `validation/*.jsonl`、运行 `run-manifest.json`。显式 run ID 禁止跨运行混用。报告不含模型生成内容/token。

检查：先调用现有 crosswalk 检查器（它必须仍返回 consumption_verified=false）；再次由原 `_load_dump_trajectory` 和 `validate_trajectory` 检查真实 trace 与 result lineage。stage result 路径采用已实现 StageSpec 的 `run/results/<artifact>/verifier-receipt.json`、对应 `run/traces`，不重建 token。完整 train 四 sibling / val 一 sibling，每条 A 后 B 的连续 TQ keys、真实同版本、frozen hash/链身份均由已有校验复用。

submission 只证明批量写返回，须绑定 crosswalk SHA 和完整 keys；仅独立 trainer JSONL `(partition, step, uid)` 单次出现并且 score 对应原 stage reward 才算消费。Pinned VERL `_log_rollout_data` 从 TQ `batch.keys` 导出 uid，score 为当前 stage rm_scores 之和；不是终态 B 广播之后的 GRPO advantage。按 stage score 校验，不能把 A 原 reward 改成 B。

报告区分证据非法、已准备未提交、提交后未消费、完整消费。遗漏、重复、未知/拒绝组消费、跨 partition/step、score 不符都不通过；整组消费须完整 n4/n1。无组不能 vacuous pass。运行 completed 单列且为整体 passed 必要条件；此报告不证明 optimizer 更新或效果提升。不写回 crosswalk/旧回执。

测试：复用 NativeMemoryFramework CPU wired fixture，执行真实 StageSpec / Task / verifier 与真实 token fixture，独立写模拟 trainer JSONL。先缺模块 RED；覆盖 train n4/val n1 正例、仅 TQ、缺 A/B、重复/未知/错步/错分区/错奖励、失效提交、失败 TQ、NPZ/trace/frozen/version/chain 损坏与不完整组、非 completed/no groups。CPU 合成消费文件仅证明审计逻辑，不能冒充真实 GPU 消费。

## 实现与固定 VERL 实证

新增 `examples/dsh/capabilities/audit_memory_training.py` 和 `tests/uni_agent/examples/test_audit_memory_training.py`。RED 为模块不存在；GREEN 使用真实 CPU StageSpec/Task/verifier/冻结产物及合成 token，未启动 GPU。

实际版本与 trainer step 分离：crosswalk 明确 `expected_policy_version`，由现固定 sync 规则校验 train=`global_steps-1`、val=`global_steps`；本审计只用 trainer `global_steps` 关联消费 JSONL，不把调度步数补造成生成版本。版本证据来自 framework 对真实生成段的 crosswalk 测量，stage dump 本身未重复保存版本计数；本报告没有宣称额外审计原始 backend 请求日志。

Pinned VERL `trainer_base.py:1220` 的 `_log_rollout_data` 读取实际 `rm_scores`，1231 对它求和写 score；`_compute_advantage` 的写回字段为 `advantages`、`returns`，可选 KL reward/IS mask，未覆盖 rm_scores。`v1/utils.py` 的终态 B 优势广播也只改 advantages/returns。测试抽取并实际执行这份固定源码的 `_log_rollout_data` 与 `_write_generations`，以真实 framework CPU TQ 字段产生 JSONL，A=1/B=0 的结果保持 `[1,0]`，审计通过。

报告的 `consumption_verified` 与 `run_completed` 分开：完成所有消费但运行仍未终态时前者可以 true，整体 `passed` 仍 false。`submission_verified` 仅表示写入返回标记绑定完备，绝不表示已消费。crosswalk 的原始 `prepared-not-consumed` 状态及现检查器返回的 false 保持不变。

不能从缺失的 crosswalk 凭空统计预准入失败：尚未创建 crosswalk 就失败的 A/B 尝试需由运行日志/监督补充；本审计能阻止这些未知 keys 出现在消费结果，但不能列出根本没落盘的任务。它也不证明 optimizer 更新、恢复、任务效果或 GPU 实跑。

最终验证：新审计 27 项，加现 NativeMemoryFramework 和 memory credit，组合 **93 passed**；Ruff check/format 均通过。固定命令：

```bash
PYTHONPATH=.:verl /private/tmp/uni-agent-cpu-20260907/bin/python -m pytest -q \
  tests/uni_agent/examples/test_audit_memory_training.py \
  tests/uni_agent/framework/test_native_memory_framework.py \
  tests/uni_agent/examples/test_memory_credit.py
```
