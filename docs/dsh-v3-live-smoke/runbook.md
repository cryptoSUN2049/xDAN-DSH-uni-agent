# v3 八类 smoke 操作入口

本页针对 `worktree-dsh-v3-live-smoke`。当前交付为 CPU 实现及测试；没有真实模型
成绩，没有本轮 GPU 部署。GPU 决策与剩余条件见 [progress.md](progress.md)。

## CPU 准备和命令检查

在此 worktree 根目录、已安装项目 CPU 依赖的 Python 环境执行。`BUNDLE` 指向
既有 `evolution_v3_live.py` 生成的 live-contract bundle；`RUN_ROOT` 必须尚不存在。
代码不改写源 bundle 的 blocked 状态。

```sh
python -m examples.dsh.ops.run_v3_live_smoke prepare \
  --bundle-dir /absolute/path/to/live-contract-bundle \
  --run-root /absolute/path/to/new-smoke-run

python -m examples.dsh.ops.run_v3_live_smoke run \
  --run-root /absolute/path/to/new-smoke-run \
  --model-path /absolute/path/to/Qwen3-4B \
  --timeout-seconds 1800 --dry-run
```

prepare 核验 canonical bundle、八类顺序、scenario/fixture/verifier/patch 字节，
生成八行 `smoke.parquet`、`task-config.yaml`、`episode-files.json` 和
`run-manifest.json`。dry-run 只返回固定 argv，不探测 CUDA、不启动模型，
也不消耗 prepared 状态；其成功不能替代部署预检。

运行固定为 8 rows、n=1、并发=1、单 engine/Gateway/GPU、TP=1、Hermes、
max-model-len=8192、GPU utilization=0.5，以及 reward ACK 和严格 DSH admission。
沿用任务配置的每轮和 episode token 设置，不将 max-model-len 误称实际总生成预算。

## 后续 GPU 环境的执行入口

此命令只在另行批准且通过环境与停机检查的新 Linux x64 部署中使用：

```sh
python -m examples.dsh.ops.run_v3_live_smoke run \
  --run-root /absolute/path/to/new-smoke-run \
  --model-path /absolute/path/to/Qwen3-4B \
  --runtime-manifest /absolute/path/to/linux-runtime.json \
  --timeout-seconds 1800
```

runtime manifest 是可信部署端冻结的身份清单，不能由候选 policy 编写。
schema 为 `dsh.evolution.live-smoke-runtime.v1`，必须包含：

| 字段 | 合同 |
| --- | --- |
| `environment_digest` | 与输入 bundle 相同的冻结环境标识 |
| `uni_agent_commit` | 当前部署分支实际 commit；import 范围 tracked clean，无 untracked Python |
| `verl_commit` | `483b8a009ba3a97563edee3a19887e4862b8094a` |
| `model` | 绝对 `path`、`repo_id=Qwen/Qwen3-4B`、revision `1cfa9a7208912126459214e8b04321603b3df60c`，以及覆盖模型目录全部文件的 `files` |
| `dsh` | 绝对 `source_root`、source commit `3b8fad1e32fd9d62acdfdb3ccbd8c8074c22d2ea`、覆盖 tracked 文件的 `source_files`、`mode=node/exe`、绝对 `runtime_root`、完整 `runtime_files`、`launch_args` 和同顺序 `launch_files` |
| `versions` | Python 实际版本、torch 2.10.0、vLLM 0.18.1、transformers 4.57.6、Ray 2.58.0、tensordict 0.10.0，以及实际 transfer-queue distribution 版本 |

文件条目格式为 `{ "path": "relative/path", "sha256": "sha256:<64 hex>" }`。
`launch_files` 的 path 则必须为实际 argv 中的绝对路径；node 两项、exe 一项。
probe 逐项核对实际版本、SDK 实际选择的 carrier、CUDA≥12.8 和一个可用设备。
旧 DSH pin 当前不可取得，因此真实预检仍会拒绝；不可填假 commit/hash 绕过。

此清单绑定已部署字节，尚不证明可复现构建或 Hugging Face 远端文件来源。
TransferQueue 源 commit 的外部部署核对仍须遵循历史 runbook；本入口仅核对其
实测 distribution 版本，不能用这个字段代替源 commit 验证。

## 目录、证据和退出码

每个真实 Gateway session 只创建一次 `artifacts/workspaces/<session_id>`，复制
清单内的 16 个可信小文件。Task 结束后、reward POST 前检查源文件与副本；
离线审计再次检查所有历史 workspace。新目录和 hash 检查不构成同 UID 权限
隔离，也不能发现运行中修改后还原。P6 containment 仍待单独实现和验证。

推理启动前持久化 UID/sample/metadata；TQ 真实读取后才保存 `readback`。
审计复用 Task/verifier/token 合同，并额外核对时间窗口、session/receipt 唯一性、
完整 token chain、TQ 最终 chain key 和评分、冻结 registry 与重算 observation。

```sh
python -m examples.dsh.ops.audit_v3_live_smoke \
  /absolute/path/to/new-smoke-run --repository-root /absolute/path/to/repository
```

| 退出码 | 含义 |
| --- | --- |
| 0 | 八类完整证据、TQ 读回与 contract 全通过 |
| 1 | 证据和 TQ 读回完整，存在 eligible 策略失败 |
| 2 | 预检、进程、输入完整性或审计失败/缺失 |

`completed` 仅表示推理子进程 exit=0。验收另看 `process_evidence_complete`、
`inference_readback_verified`、`live_contract_passed`；`training_eligible` 始终 false。

正常及失败收尾保留 `run.log`、manifest、`smoke-report.json` 和已产生的原始
trace/envelope/receipt/token artifacts。`artifact-sha256.json` 使用
`dsh.evolution.live-smoke-artifacts.v1`，含相对 run root 的文件清单；在最终
manifest 写入后封存，自身不参与 hash。独立 auditor 将报告输出到 stdout；
运行 wrapper 负责保存报告和清单。

运行只允许尝试一次；失败后新 prepare 到新目录，不能原地覆盖旧证据。
审计依赖 manifest 记录的原 repository/bundle/run 路径；导出到不同机器后
先按相对 artifact 清单复验字节，不能通过改写 manifest 假装原位运行。

## 超时与资源释放边界

`timeout-seconds` 在 (0,7200] 内，监督推理进程组，TERM 后最多 5 秒再 KILL，
保留 timeout/exit/PID/时间和完整性状态。不控制 RunPod，也不保证远端进程
脱离进程组后的回收。独立可信控制端的 Pod 停机/删除、导出截止及费用限制
仍是购买前条件；不要将这里的进程 deadline 当作 GPU 停费机制。

导出以完整 run root 加冻结 bundle/source/runtime 清单为单位。传输中断或
超时不能延长已批准的 GPU/存储截止时间；未导出的运行据实记为未完成。
