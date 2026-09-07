# 2026-09-07：审批前预检补充

核查基线：`55ed21f9b001908ec395c1d1e069cefe214cc6a1`；只读核查，不修改实现，
不创建资源。设计、手工 worktree 替代方式和 GPU 预算尚未收到明确批准。

## CI 终态

- [Python CI run 34044515382](https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/actions/runs/34044515382)：
  Python 3.11 job `101517068388` failure，3 failed / 565 passed / 1 skipped；
  Python 3.12 job `101517068549` cancelled。
- 三项失败均为 `test_rlinsight_adapter.py` 的 fixture 在缺少 `trace_span` 的
  `RLInsightLogger` 上使用默认要求属性存在的 monkeypatch。冻结 VERL 类源码
  只有 `trace_state` 等方法；产品适配器已对缺可选 API 提供 warning 降级。
- [pre-commit run 34044515346](https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/actions/runs/34044515346)：
  `test_host_runtime.py` 有一项 I001；ruff-format、mypy、compileall passed。
  docs、secrets-scan、metadata 通过。本次没有新类型的失败。
- 原始日志仅在本机临时目录，不提交完整 CI 日志：
  `/private/tmp/uni-agent-55ed21f-python311.log`，SHA-256
  `fbaf7e23f7b0031cbaeefbb05fe3d5d77f42c62f5d8ee1f8eec6d1b85c5dccfa`；
  `/private/tmp/uni-agent-55ed21f-precommit.log`，SHA-256
  `69f800807028dcd46cef67555535642f5383b70a9d4dc777daef5fa77e844048`。

## Runtime 与历史证据可恢复性

- DSH 本机共享 Git 对象库找不到历史 pin
  `3b8fad1e32fd9d62acdfdb3ccbd8c8074c22d2ea`。GitHub REST 查询自有
  `cryptoSUN2049/xDAN-DSH-Exp` 和官方 `deepseek-ai/deepseek-harness` 的该 commit
  均返回 HTTP 422 / No commit found；未 fetch、改动 sibling 或全盘搜索。
- 限定检查 DSH 根目录、official-training worktree、Uni-Agent 的相关 dist、
  runtime payload、models、runs/backups/artifacts 目录，未找到 Linux runtime 部署包。
- capability-sft worktree 有 macOS ARM64 executable、辅助二进制与 node closure。
  当前 exe SHA-256 为 `736809737626d30750dbaae5c9045b1bbf0e342bb020f7f9a4a68f185f6e2e25`，
  只证明该文件当前内容，未发现它与历史 pin 的构建来源关联。
- 历史 runbook 要求 Node 24.8.0、pnpm 11.7.0；构建入口为
  `pnpm exec tsx scripts/build-exe-for-python-sdk.ts --targets=node24-linux-x64`。
  当前构建脚本要求目标平台/架构与宿主匹配；可在 Linux x64 CPU 主机预构建，
  不能据此声称已验证缺失的历史版本或完成 macOS ARM64 交叉构建。
- runbook 虽构建 exe，实际还设置 `DSH_RUNTIME_MODE=node`；node 模式执行完整
  `runtime/node/` closure。新 run 须明确实际载体并记录对应入口、依赖与 hash，
  仅记录未执行的 exe hash 不足以证明 runtime identity。
- `tasks/dsh-official-training/p4-global-step-4-sha256.txt` 只有历史远端 hash；
  runbook 的 `/workspace/backups/` 是 Pod 内备份示例。检查范围内没有本机副本、
  导出回执或明确备份目的地；不能据此断言数据永久丢失，也不能声称可以立即 reload。

## 停费机制

- 现有 `examples/dsh/ops/teardown_qwen3_4b_online_rl.sh` 仅杀 PID、可选停止 Ray、
  更新 manifest；不会调用 RunPod stop/delete，不停止 GPU 计费。
- 本机 runpodctl 2.12.0 create/update help 无到期参数；
  [官方 v2 OpenAPI](https://api.runpod.io/v2/openapi.json) 的 Pod create/update schema
  没有 expiry/deadline/stopAfter/terminateAfter，公开 paths 未提供 Pod 定时任务。
- [官方 Manage Pods](https://docs.runpod.io/pods/manage-pods) 的两小时停止示例
  使用客户端 sleep 后调用 stop；它依赖客户端在线，未证明平台独立定时停止能力。
- stop 释放计算、保留收费磁盘；delete 释放 Pod 及附属磁盘。仅进程退出不等于停费。
- 本机未发现现成独立 watchdog。可信常驻控制器可以持久化 Pod ID/费用与时间截止，
  调用并确认 stop/delete、重试暂时故障，且不向模型 Pod 暴露控制面凭据；
  目前未选择、部署或验证此控制器。不得把本机 sleep 当作已满足原设计的硬上限。

## 下一步

1. 获批后先做 M0；保持冻结 VERL 与旧 API 降级测试。
2. 恢复历史 source/runtime，或明确冻结一个可重建的新 DSH baseline 并单独验收，
   不将新版本冒充历史运行来源；明确 node/exe 与实际 Linux 构建载体。
3. 完成 CPU smoke 准备和停止机制验证，再进入授权额度内的单卡推理。
4. 历史 P4 证据与新运行保持分开；备份实体缺失不能被 hash 清单替代。

## CPU 阶段继续：基线 `eb7f040`

用户在进度对比后回复“好的 看看怎么继续”；本轮按该回复推进 CPU 阶段，GPU 另行确认。
唯一仍需明确的工作区例外是手工 `git worktree add`，异步问题已发出且尚未收到答案。
没有修改产品/测试代码；依赖安装只进入临时 venv，不改全局 Python 或项目依赖文件。

- venv：`/private/tmp/uni-agent-cpu-20260907`；Python 3.12.12，torch 2.10.0、Ray 2.58.0、
  TensorDict 0.10.0、Transformers 4.57.6；以 `PYTHONPATH=.:verl` 使用仓库内固定 VERL。
- 依赖冻结：`/private/tmp/uni-agent-cpu-20260907-requirements.txt`，SHA-256
  `2388272f24b5c77c3a2f6b6593334bc1ec2a702fa1debe8f090478c8ea5efe8b`。
- RLInsight 现有四项测试：3 failed / 1 passed，准确复现 CI 的可选 trace_span fixture 问题。
  JUnit `/private/tmp/uni-agent-m0-baseline.xml`，SHA-256
  `03c796628535644d2e151b5e248a9fcd5c11836282bb3d2b0d9bba60786496e9`。
- Ruff 0.12.2 对 `tests/uni_agent/deployment/test_host_runtime.py` 报 I001；其 format check 通过。
- 两个此前无法 collection 的文件 `test_dsh_trajectory_audit.py`、`test_dsh_ops_audit.py`
  现为 20 passed / 1 Ray 弃用警告；JUnit `/private/tmp/uni-agent-audit-baseline.xml`，SHA-256
  `f122b1084b9b7bc2b90b961b9f9bea79b7ed72290112e73f7b415b095a8498b1`。
  初次补包后仍缺 codetiming，已补齐并重跑通过；没有通过跳过测试绕过依赖。

复用的实际证据链：Framework log_dir/GatewaySession 下写 trajectory.json/npz；DSH
trace_root/sha256(GatewaySession)[:24] 下写 session.jsonl/result.json；Task
result_root/sha256(DSHSession+NUL+traceDigest)[:24] 下写 envelope/receipt。
inference 没有 step_* 子目录，global_steps=null；TQ session_id 是整数，非 Gateway ID。
新 CLI 需预登记 UID/family，透传现有严格审计配置，保留实际 final TQ keys 与读回分数；
auditor 补 run 时间窗口与 receipt 唯一性，并从真实 trace 重算 observation。
不把 inference 读回记录冒充 optimizer 消费证据，不让 GPU 条件阻塞 CPU 实现。
