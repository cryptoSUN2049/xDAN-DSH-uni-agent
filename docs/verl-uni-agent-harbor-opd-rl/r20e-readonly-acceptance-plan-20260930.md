# R20e 只读联合验收准备

当前范围是准备验收和观察；启动、停止、controller/key 清理由 root 决定。未执行 GPU、训练、Modal allocation/termination、W&B 写入或 Git 操作。

## 已确认的运行合同

- Run：`mimo9b-002549-r20e`；W&B：`mimo9b002549r20e`。
- Project：`xDAN-Verl-Uni-agent-Harbor-rl-opd`。
- 当前运行目录：`/workspace/mimo-dsh-rl-20260928/runs/r20e/rl-training`。
- Source：`/workspace/mimo-dsh-rl-20260928/run-src-r20`；commit `1ccc1640c0f34ba5f515d3613fac6a278bd38f4c`。
- Source manifest：`/workspace/mimo-dsh-rl-20260928/integration-check/source-r20-manifest.json`；SHA256 `99ac03f55d4eaeebc63d2ba466452fef2af7a51af289fc135d5051dadca0591f`。
- World2、FSDP1、n4、sessions2；独立 R19 C4 恢复到新 R20e C5。
- 固定 deadline `1790759992`；不得沿用 helper 的历史默认 deadline。
- 以上是 root 明确的计划身份；当前实际 spec SHA、launch SHA、PID、开始和完成时间必须从 R20e 实物读取。

## 已核实的最短调用路径

1. 真实终态：读取 R20e operator 输出及该 launch_root 的 `supervisor-result.json`；分别保留程序 exit code、目标 step5、原生 C4 恢复日志、C5 marker/文件清单。目录或文件缺失只记 pending。
2. 实际消费：冻结源码 `examples/harbor/audit_m2_training.py` 的 `audit_training`，绑定当前 launch、agent_log_dir、rollout_data_dir，`async_training=True/no_validation=True/train_n=4`。要求唯一四条 TQ key 在 training step5 消费；prefetch 和未消费任务另列。该 helper 只证明 batch correspondence。
3. 参数和优化器更新：冻结源码 `deployment/checks/sharded_checkpoint_delta.py`，输入独立 R19 C4 actor 与 R20e C5 actor；云 CPU、CUDA_VISIBLE_DEVICES 为空、OMP/MKL 两线程。现有 rank 子进程严格 CPU 校验，保留两 rank 完整输入 SHA 和 optimizer step4→5。只在终态后由 root 授权调用，当前没有启动此计算。
4. 汇总门：`docs/verl-uni-agent-harbor-opd-rl/mimo_world2_acceptance.py::audit`，明确 expected_run、实际 expected_spec、step5 和独立 C4 resume_manifest+SHA。必须有 reward 差异、正负 advantages、非零 grad，以及 LoRA delta>0/base unchanged。该门的异步版本检查仅要求 policy max<5；R20e 另须用当前 gateway/token 实证所有消费样本 policy4，不能把这个上界替代 exact4。
5. W&B：root 作为唯一 API reader，精确新 run 的真实 finished 状态、原生 step5 history 与 console/batch 数值匹配。禁止 finish/summary/history 补写；网络或原生 finish 未完成记 unknown/failed。
6. Insight/Prom：`mimo_observability.metric_query`/`verify_ack` 已核实支持显式 run/project/step/start/deadline；实际原生 `observability-ack.json` 另核 SHA。后端 `http://127.0.0.1:9090/api/v1/query` 用 exact project/experiment selector 的 range-vector，在实际 finish time 查询本轮时间窗。保留真实 scrape timestamps；query_range 重复求值不是多次真实 scrape。
7. Tempo：`http://127.0.0.1:3200/api/search`，exact project 与 experiment_name 两 tag、真实 R20e start/finish、bounded limit1000。区分 gateway_generation、agent_task、agent_session；每类型至少一个 trace payload 回读其 tags。limit hit 或窗口缺失如实标边界。
8. Modal 资源终态：只从当前 consumed/prefetch job 的明确 primary/verifier manifest 取实际 sandbox IDs。ledger succeeded 不能替代 API termination。只读 fresh from_id/poll 收集 returncode；运行中仍活跃资源属于正常状态。终态清理另由 root 明确授权，绝不自动操作 controller、key、Pod 或其他 run。

## 当前实测与边界

云 CPU observed_unix `1790752020.9517803`（2026-09-30 07:07 UTC）读取当前明确目录：R20e `rl-training` 尚不存在。本记录是准备阶段快照，不是启动失败或训练结论。

旧 R19 报告仅用于核对 helper 调用方式和字段结构；不复用其 PID、spec SHA、时间窗、trace IDs、scalar values、资源清单或验收结果。联合验收分别报告实际 restore、有效更新、原生可观测性与资源终态，不能据这些工程证据承诺模型能力提升。
