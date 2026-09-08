# Harbor evolution v1：四种真实 Docker 路径通过

2026-09-08。使用提交 `2df91d7de31b9ecacefeaad1c54dbea80028eead` 的原生打包器和 scripted smoke，进程退出码 **0**。这是一个公开 `redact-train-01` 场景的 DSH/Harbor 工程验证；策略由本机脚本提供，没有学生模型、Gateway token 消费、训练或独立留出评估。

| Mode | 真实请求 / DSH 事件 | 独立 verifier 结果 | 清理核验 |
|---|---:|---|---|
| positive | 8 / 48 | reward **1.0**，七组件全部 1 | 通过 |
| partial | 7 / 43 | reward **0.25**；实际省略 candidate 调用，完成 define/run/stop/undefine | 通过 |
| missing_define | 3 / 21 | 原 v1 hard-veto 拒绝，无 reward | 通过 |
| tamper | 8 / 48 | trace/status/session 哈希身份不匹配，上传前拒绝，无 reward | 通过 |

四例 DSH 均真实结束，`finish_reason=completed`，脚本服务器错误列表为空。`missing_define` 的 verifier stdout 明确为 `Evolution hard-veto evidence is not eligible for training`，Harbor 对外异常为 `RewardFileNotFoundError`；不能把该异常误当普通得分 0。tamper 在 verifier 输入上传前被桥接器拒绝。

## 固定身份与准备过程

- GPU checkout HEAD 为上述提交且 tracked clean；在原 checkout 只运行 CPU `prepare_evolution_task`，没有改源码、venv 或正在运行的 M1 v2 GPU 任务。
- 原 16/8 数据：`/workspace/data/dsh-evolution-v2-b236969`，manifest `sha256:1e22ec154e30d1d3394c394b837be6cddcb5067da32ab895058d5347298854d7`。
- TaskRef：`evolution-redact-train-01 / v1 / sha256:c1863007130a2894bc064356d89771acced9dfdd54e8d8832c62718a51d28609`。
- 固定 DSH SDK/runtime：`0.1.3a2`；runtime binary `sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。四例 `setup.json` 实测 SDK/runtime 版本匹配。
- agent 父镜像：`uni-agent-dsh:t2-log-tool-r1`，构建前实际 inspect 匹配 `sha256:b016c85140a58f7d842eadb0238925ee1c347143cc7bede5b9b35bfa38747dca`，linux/amd64。
- 新 agent 镜像：`uni-agent-dsh:evolution-redact-v1-r1`，`sha256:93db845150fccdd2b5cc34714087138056045f50f09fdb1ab6d48e92a856b3bf`。
- 新 verifier 镜像：`uni-agent-dsh:evolution-verifier-v1-r1`，`sha256:30f0fa534c18e82843a76fa93bf2affb98b15fbd9117307b1acbdd2f2fc7c726`。
- 两镜像均 `docker build --platform linux/amd64 --pull=false --network=none`，无下载或安装。ID 是本地镜像内容 ID，不是已发布的 registry manifest digest。
- 先用父镜像 ID 生成准备包取得 contexts，构建后再在 GPU 原路径生成双 ID 固定的最终包；每次都用新目录，最终 23 个文件哈希全部通过，environment/tests contexts 与用于构建的准备包逐字节一致。

## 可复建入口与路径

GPU 上的最终生成命令（复跑必须换全新 `--output`）：

```sh
cd /workspace/rebuild/uni-agent-g1-v2
test "$(git rev-parse HEAD)" = 2df91d7de31b9ecacefeaad1c54dbea80028eead
test -z "$(git status --porcelain --untracked-files=no)"
PYTHONDONTWRITEBYTECODE=1 /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m examples.harbor.prepare_evolution_task \
  --root /workspace/rebuild/uni-agent-g1-v2 \
  --source-dir /workspace/data/dsh-evolution-v2-b236969 \
  --source-manifest-sha256 sha256:1e22ec154e30d1d3394c394b837be6cddcb5067da32ab895058d5347298854d7 \
  --output /root/runs/harbor-evolution-v1-package-r1 \
  --agent-image-digest sha256:93db845150fccdd2b5cc34714087138056045f50f09fdb1ab6d48e92a856b3bf \
  --verifier-image-digest sha256:30f0fa534c18e82843a76fa93bf2affb98b15fbd9117307b1acbdd2f2fc7c726
```

仅回传已生成的任务包，不部署整个源码 checkout。原 manifest 保留 GPU 的绝对路径；本地 smoke 从 TaskRef 固定的 descriptor 重新绑定本地 fixture/metadata 路径，再注入 controller 独有第四文件 `evolution-binding.json`，没有修改包内文件。

本地实际执行命令（在本 worktree，Harbor 固定 0.16.1，复跑换新 output）：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$PWD:$PWD/verl:/private/tmp/uni-agent-cpu-20260907/lib/python3.12/site-packages:/private/tmp/harbor-h0-20260908/lib/python3.12/site-packages" \
/private/tmp/uni-agent-cpu-20260907/bin/python \
  -m deployment.checks.harbor_evolution_scripted_smoke \
  --task-dir /private/tmp/harbor-evolution-v1-docker-r1/harbor-evolution-v1-package-r1/task \
  --manifest /private/tmp/harbor-evolution-v1-docker-r1/harbor-evolution-v1-package-r1/manifest.json \
  --output /private/tmp/harbor-evolution-v1-docker-r1/smoke-r1 --timeout 600
```

## 证据与边界

- [数值、原始异常、逐文件哈希及身份清单](harbor-evolution-v1-docker-r1-results.json)。原始日志和四例 trace/result/reward 在 `/private/tmp/harbor-evolution-v1-docker-r1/smoke-r1`；构建日志在该目录的上一级。
- 原始结果：`smoke-r1/scripted-smoke.json`。归档：`/private/tmp/harbor-evolution-v1-docker-r1/evidence.tar.gz`，SHA256 `c9a3e40e3544a0b512ac9dd40ad7a26303fe76b2d9a53d1400fdb2e7b8a4c1ef`。归档排除 trial `config.json`，不需要保存 endpoint key。
- 每例调用 `_confirm_cleanup`：分别查询 agent/verifier 的 Compose project label，要求包含已停容器在内的 container、network、volume 都为空。没有清理其他项目资源；构建镜像与证据保留供后续复用。本机 scripted HTTP server 已逐例关闭。
- **Harbor 仍是 `evolution-v2-lifecycle-v1`，原 `examples/dsh/evolution_verifier.py`。** GPU 正在运行的 native M1 v2 使用不同准入规则，尚未通过此包接入 Harbor；本次 missing_define 的“通过”是确认旧 v1 拒绝行为，不是认可其适合下一轮 RL。先明确迁移并重建 TaskRef/镜像，再部署新版学生评估。
- 本次没有运行 worker HTTP ledger/receipt、训练侧 token 消费或学生 rollout；不能扩大为新的 Agent RL 能力提升。既有接线 CPU 测试和本次实际 Docker 结果分别记录。
