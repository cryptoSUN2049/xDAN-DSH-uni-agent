# Modal 替代方案调研：任务简报（供独立会话执行）

目的：为 Harbor 的 agent 沙箱找成本更低、销毁更可控的执行后端。背景见 `modal-cost-postmortem.md`：一夜 358 美元，主因是 Harbor 在 Modal 上创建的沙箱默认 24 小时生命周期、进程被杀后不销毁。

## 一、需求

一条 trial = 一个隔离沙箱，里面跑 terminus-2 agent 与 verifier：

| 维度 | 要求 |
|---|---|
| 规格 | 1 核、2 GB 内存、约 5 GB 磁盘 |
| 时长 | 单条 10 到 20 分钟，超时上限 1800 秒 |
| 并发 | 常态 16 到 32，扩到 500 题规模时需要 64 |
| 镜像 | 能按任务的 `environment/Dockerfile` 构建，或拉取已构建镜像；需要构建缓存 |
| 网络 | 任务内可能要访问 PyPI、apt、GitHub |
| 销毁 | 必须支持空闲超时或明确的生命周期上限，进程异常退出后不能继续计费 |
| 接口 | Harbor 0.16.1 已内置的后端优先，避免自研适配器 |

## 二、候选（Harbor 已内置的后端）

`harbor/environments/` 下现成的实现：`modal`、`e2b`、`ec2`、`gke`、`openshift`、`novita`、`runloop`、`blaxel`、`islo`、`cua_cloud`、`cwsandbox`、`tensorlake`、`apple_container`、`dind_compose`。

优先评估这四类：

1. **自建 Docker（`dind_compose` 或 `ec2`）**。在一台按小时计费的 CPU 机器上跑 Docker。32 核机器每小时 0.5 到 1.5 美元，可并发约 30 个沙箱，折合每条 trial 不到 0.01 美元。缺点是要自己管镜像缓存、磁盘和清理。注意：我们现在的 RunPod pod 里没有 docker 命令，需要确认能否装、是否有特权。
2. **E2B**。按秒计费的沙箱服务，Harbor 已内置。适合直接对比 Modal 的单价与启动延迟。
3. **Novita / Runloop / Blaxel**。同类沙箱服务，价格与区域各异，用同一套基准测。
4. **继续用 Modal，但把泄漏堵住**。如果清理脚本加优雅停止能把实际成本压到每条 0.016 美元，一轮 20 步约 12 美元，可能已经够用，不必迁移。这条要作为基线一起测。

## 三、实验设计

固定用同一批 10 道题（5 道 Terminal-Lego + 5 道 SWE，来自审计通过集），同一个 agent 与 verifier，分别在每个后端跑一遍，记录：

| 指标 | 怎么测 |
|---|---|
| 单条 trial 成本 | 后端账单除以 trial 数；自建机器按机时折算 |
| 启动延迟 | 从创建沙箱到 agent 第一条命令执行的时间 |
| 镜像构建 | 冷启动构建耗时、二次运行是否命中缓存 |
| 正确性 | verifier 能否生成 CTRF 报告并写出 reward，与 Modal 结果一致 |
| 销毁行为 | 杀掉客户端进程后，沙箱是否自动消失；能否设空闲超时 |
| 并发上限 | 并发 16、32、64 时的失败率与限流表现 |

建议的判定顺序：先验证正确性与销毁行为，再比成本和延迟。销毁行为不过关的后端直接淘汰，无论多便宜。

## 四、起步命令

```bash
# 在双卡 pod 上（共享盘已有环境与数据）
ssh -p 11965 root@157.157.221.177
export PATH=/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin:$PATH
cd /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent

# 现成的 10 题数据（审计通过、已剔除共享评估集）
ls /workspace/verl-uni-agent-harbor-opd-rl/data-r4/stage1/tasks-train | head

# 单条 trial 直接跑，不经过训练链路（这是最小实验单元）
harbor trial start --path <任务目录> --trial-name probe-1 --trials-dir /tmp/probe \
  --agent oracle --env modal --timeout-multiplier 1
```

把 `--env` 换成 `e2b` 等后端即可对比。`--agent oracle` 用参考解，不需要 GPU 推理，最适合测基础设施。

## 五、交付物

- 一张对比表：各后端在上述六个指标上的实测值。
- 一个结论：迁移还是留在 Modal，以及理由。
- 如果迁移：把新后端接进 `examples/harbor_opd_rl/tb21_terminus2_smoke.yaml` 的 `harbor_env`，并在 `run_opd_round.sh` 里暴露成参数。

## 六、注意事项

- 本线的训练随时可能恢复，实验请用独立的 trials 目录与独立的 Modal app 名，不要动 `runs/pipe-*`。
- 凭据在 pod 的 `/root` 下，不要写进仓库。
- 任何新后端的密钥同样只放 `/root` 或环境变量。
