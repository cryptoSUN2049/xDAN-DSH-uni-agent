# Modal 成本复盘：一夜 358 美元，沙箱泄漏是主因

日期：2026-09-18。数据来源：Modal 按应用用量明细（由 Tinker 训练线从后台导出）、本线 run 日志、Harbor 0.16.1 源码。

## 一、账单事实

| 项目 | 金额（美元） |
|---|---|
| `__harbor__` 应用（我们的 trial 沙箱）2026-09-17 | 358.08（CPU 267.88 + 内存 90.20，GPU 0） |
| Tinker 线的审计与评估沙箱 | 4.81 |
| Tinker 线的训练控制器 | 1.68 |
| 本账期计量合计 | 385.25 |
| 本账期已计费 | 439.25 |

结果：工作区触发 `billing cycle spend limit`，计算调用全部被拒，两条线同时停摆。读操作仍然可用。

我们当天约 600 到 800 条 trial，折算每条 0.45 到 0.60 美元。

Modal 对沙箱按 **Sandbox 单价**计费，是 Function 单价的 3 倍：CPU 每核每秒 0.00003942 美元（每核每小时约 0.142 美元），内存每 GiB 每秒 0.00000667 美元（每 GiB 每小时约 0.024 美元）。用这个单价反推当天账单：CPU 267.88 美元约合 1888 核时，内存 90.20 美元约合 3756 GiB 时，按 2 核 4 GB 折算都是约 940 沙箱小时，与 SandboxList 实测的 953 沙箱小时（698 个沙箱）一致。实际轨迹运行约 200 小时，计费约为实际的 **4.8 倍，约八成是空转**。

**更正（2026-09-18）**：本文初版按 Function 单价折算，得出"约 2820 沙箱小时、超出约 14 倍"，这是错的。由会话 xdan-dsh-uni-agent-67 和 e1 指出。

## 二、根因

1. **沙箱泄漏（主因）**。Harbor 创建 Modal 沙箱时的默认值是 `sandbox_timeout_secs=86400`、`sandbox_idle_timeout_secs=None`（`harbor/environments/modal.py:881`）。Harbor CLI 进程被杀时不清理沙箱，于是沙箱继续计费，最长 24 小时。

   **更正（2026-09-18，由会话 xdan-dsh-uni-agent-67 指出）**：这两个参数命令行是可以传的，`harbor trial start --environment-kwarg sandbox_timeout_secs=2700`（`cli/trials.py:411` → `factory.py:313` 的 `**config.kwargs` → `ModalEnvironment.__init__`）。我们原先写"命令行没有暴露"是错的。正确做法是创建时就传入，由 Modal 服务端强制执行，而不是事后靠脚本轮询清理。
2. **我们当天强杀了 7 次训练**：pipe-r4 的 5 次（3 次 27B Teacher OOM、2 次主动改配置）、pipe-r6 与 pipe-r7 各 1 次。每次有 16 到 32 个沙箱在跑，合计约 150 到 200 个沙箱被留在后台。按 Sandbox 单价，2 核 4 GB 每小时约 0.38 美元。约 750 空转沙箱小时合约 285 美元，占 358 美元的八成。SandboxList 实测沙箱寿命中位数 10 分钟、p90 6.2 小时、最长 9.1 小时。
3. **沙箱规格超配**。我们设 `override_cpus=2`、`override_memory_mb=4096`，而任务自身声明 `cpus=1`、内存 1 到 2 GB。多付 2 到 4 倍。
4. **等待模型时沙箱照常计费**。沙箱按秒计费，agent 每一轮都要等 GPU 生成。并发超过 GPU 吞吐时，多出来的沙箱在排队，钱照花。
5. **两条线共用一个工作区**，昨晚合计 64 并发跑了一整夜。

## 三、已修复（2026-09-18）

| 修复 | 位置 | 效果 |
|---|---|---|
| 沙箱规格降到 1 核 2 GB | `examples/harbor_opd_rl/tb21_terminus2_smoke.yaml` | 单价约降一半 |
| trial 超时 2400 → 1800 秒 | 同上 | 卡住的 trial 少空转 10 分钟 |
| **创建时传入生命周期（主控制）** | `tb21_terminus2_smoke.yaml` 的 `environment_kwargs`：`sandbox_timeout_secs=2700`、`sandbox_idle_timeout_secs=1200`、`app_name=verl-harbor`；适配器经 `--environment-kwarg` 透传 | 服务端强制回收，客户端被杀也不泄漏；独立 app 隔离影响面 |
| 残留沙箱清理脚本（兜底） | `deployment/bootstrap/modal-sandbox-cleanup.sh` | 手动排查用。注意：modal 1.5.5 的 `Sandbox.list()` 没有 `created_at`，改用 SandboxList RPC 读取，年龄未知一律保留（会话 67 修复） |
| 默认并发 16 | `examples/harbor_opd_rl/run_opd_round.sh` | 与 Tinker 线约定，峰值 48 |
| 冒烟优先 | `run_opd_round.sh --smoke` | 换模型或配置先花几十条 trial 验证，不再连烧 5 次 |

修复后单条 trial 约 0.047 美元（1 核 2 GB、15 分钟，Sandbox 单价），一轮 20 步（约 700 条 trial）约 30 美元，前提是不再泄漏。初版写的"0.016 美元、11 到 15 美元"用的是 Function 单价，偏低约 3 倍。

pipe-r9 中途实测（2026-09-18 04:35 UTC，50 条 trial）：每条约 0.023 美元，因为本切片的 trial 平均只跑约 5 分钟。最终数字以 pipe-r9 的 cost 阶段为准。

**每轮自动核验**：`examples/harbor_opd_rl/stages/90_cost.sh` 调用 `cost_report.py`，按小时取本轮时间窗内本轮应用的 CPU 与内存账单，用 Sandbox 单价折算核时，与 trial 实际时长对比。门槛：计费/实用 ≤ 1.5、每条 ≤ 0.05 美元、残留沙箱 0。测不到的数一律记为失败。初版 cost 阶段有三个缺陷：用 Function 单价、查的是旧应用 `__harbor__`、按天查询当天无数据时空值被当作通过。它从未产出过真实账单数，已于 2026-09-18 修复。

## 四、待办

- **把花费上限改成按天**，触顶只影响当天，不会锁死整个账期。需要工作区所有者在 Modal 后台操作，命令行改不了。
- **优雅停止代替强杀**：先停止取新任务、等在跑的 trial 自然结束，再杀进程；或者杀进程后立刻跑清理脚本。
- **给 Harbor 提 issue 或本地包装**：暴露 `sandbox_timeout_secs` 与 `sandbox_idle_timeout_secs`，默认值 24 小时对 RL 训练不合理。
- **评估替代后端**，见 `modal-alternatives-brief.md`。
