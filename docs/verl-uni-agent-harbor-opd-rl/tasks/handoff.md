# VERL 训练线交接文档（2026-09-19 12:55 UTC）

**绝对路径（先看这里）：**

| 用途 | 绝对路径 |
|---|---|
| 本机 worktree（仓库根，所有命令在这里执行） | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl` |
| 本线文档目录 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl` |
| 本文 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/handoff.md` |
| 给 Codex 的交接封面 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/handoff/交接训练claude-to-codex-0919-2050.md` |
| 每日训练日记 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/每日训练日记.md` |
| GPU 排期与共用规则 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/gpu-schedule.md` |
| pod 上的 lane 根目录 | `/workspace/verl-uni-agent-harbor-opd-rl` |
| pod 上的源码（脚本都从这里跑） | `/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent` |
| pod 上的 runs（日志、checkpoint、评测） | `/workspace/verl-uni-agent-harbor-opd-rl/runs` |
| pod 上的 Python 环境 | `/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1`（vLLM 0.23.0） |
| pod 上的模型 | `/workspace/models/Qwen3.5-9B`、`/workspace/models/Qwen3.8-27B` |
| Tinker 训练线交接 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/tasks/handoff.md` |
| Tinker 评测线交接 | `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/tasks/handoff-eval.md` |

pod 连接：`ssh -o ConnectTimeout=30 -o BatchMode=yes -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177`（09-19 有效；pod 重建后端口会变）。

下文的相对路径：文档以本线文档目录为基准，代码以仓库根为基准，`runs/...`、`data-...` 以 pod 的 lane 根为基准。第 10 节的阅读清单全部写成绝对路径。

- 交出方：VERL 线会话（重启后当前名为 `xdan-dsh-uni-agent-25`；Tinker 文档里记为 `b7`，更早是 7e）。
- 接手方：下一个 VERL 会话，Claude 或 Codex 都可以。**Codex 接手请先看第 10 节。**
- 旧版交接：`tasks/handoff-history-20260918-1830.md`（pipe-r11 时期；其中第 2 节"一条命令起一轮训练"、第 4 节"成本纪律"仍然有效）；`tasks/handoff-history.md`（09-15 及以前）。

## 分工（2026-09-19）

| 会话 | 负责 | 交接文档 |
|---|---|---|
| **VERL 线（本文）** | VERL 训练（pipe-s2 及以后）；这台 pod 的 GPU 排期；本线口径的评测（`eval_val_only.sh`） | 本文 |
| Tinker 训练线 `4b`（09-19 重启前为 1a，更早是 c6、e1） | Tinker 训练、训练数据选用、HF 发布、Modal 额度 | Tinker `tasks/handoff.md` |
| Tinker 评测线 `5e`（09-19 重启前为 76） | 所有模型的 TB2.1 官方口径评测（terminus-2、89 × 5、开思考），在本 pod 的 GPU 上用 vLLM 跑 | Tinker `tasks/handoff-eval.md` |

- **会话名重启后会变**，联系前先 `ListAgents`。
- **负责人约 12:00 UTC 定的规矩**（Tinker 文档记为北京时间 20:00）：所有模型的评测，包括 Tinker 的，统一在本 pod 的 GPU 上做。
- 评测会话的窗口（详见 `gpu-schedule.md`）：
  - GPU1 09-20 01:00–07:30 做部署验收，07:30 硬截止；
  - GPU1 08:30 以后跑全量；
  - GPU0 08:30 以后留给 pipe-s2 最终模型的评测。
- **与评测会话的约定（09-19 约 13:10 已由 5e 确认，并写进 Tinker `handoff-eval.md` §3.3）：**
  1. 排期照 `gpu-schedule.md`：01:00–07:30 GPU1 部署验收（启动前先确认显存小于 2 GB）；08:30 以后只用 GPU1，一个 `vllm serve --enable-lora` 同时承载原版和 A'；GPU0 不碰。
  2. 所有 vllm serve 都导出 `KEEP_GPU_PROCESS=1`（孤儿清理会跳过，1541ce7），并用 `launch-detached.sh` 启动。
  3. 文件和缓存放 `/workspace/tinker-eval/`。只读借用 `envs/ua-verl-py312-vllm023-ws1`；Harbor 装在它自己的 venv 里。
  4. 每次启动前，它会发来启动时间、预计时长和卡号。

## 0. TL;DR

1. **S1（联合 OPD+RL）第 12 步显著退步：−0.172 [−0.285, −0.060]，已暂停，不再继续。**
   - OPD 打分的实现逐项核对无误，问题在算法层面：k1 约 2/3 落在 analysis、plan 这些说明文字上；句末 `.",` 平均 k1 +0.134，推长篇幅；老师信号与成败不对齐；第 12 步 8 组里 6 组没有 RL 信号。
2. **pipe-s2 正在跑，负责人决定不改动、跑到完。** 做法：先 OPD 12 步，再 RL 48 步，阶段 B 用 `CKPT_LOAD_CONTENTS=model` 重置优化器。
   - 阶段 A 12:41 UTC 通过；阶段 B 12:41:48 开始，预计 09-20 08:30–09:30 到第 60 步。守护进程在，驱动崩了会自动续跑。
3. **他线参照：Tinker 的分阶段 run（OPD 8 + RL 24）比原版 −0.160，比只用 RL 的 A' −0.359。Tinker 主线已改为只用 RL**（A' +0.199 [+0.115, +0.282]）。
   - pipe-s2 回答的问题是：重置优化器之后，RL 能不能把 OPD 造成的退步追回来。
4. **12:44–12:47 两个修复已提交并部署到 pod**：delta 阶段不再挑中空壳 checkpoint（1c6b65b）；孤儿进程清理跳过带 `KEEP_GPU_PROCESS=1` 的进程（1541ce7）。评测会话 5e 已确认：它启动 vLLM 时会导出 `KEEP_GPU_PROCESS=1`。
5. **下一轮建议同数据只用 RL（`TEACHER=0`），和 Tinker A' 对齐。** OPD 变体要等 D1 证明老师在无思考时明显更强再考虑。由负责人定。

## 1. 来龙去脉

| 时间（UTC） | 事件与结果 | 证据 |
|---|---|---|
| 09-16 | 路线 ① 用 Harbor 内置 terminus-2 加 Modal 沙箱；16:47 机制闭环验收 PASS | `tasks/memory.md` 09-16 各节 |
| 09-17 | 双卡 pod；pipe-r2（4B 纯 RL）、pipe-r3（4B 自评，蒸馏损失约 0）、pipe-r4（9B + 27B 老师，20:07）验收 PASS；eval-set-v1 冻结；Modal 换到工作区 l98348740 | `pipe-r2/`、`pipe-r3/`、`pipe-r4/` |
| 09-18 06:07 | pipe-r9 停止：`pass_ratio` 在 SWE 上"什么都不做"的下限中位数 0.936，默认奖励改为二值 | `pipe-r9/reward-floor-finding.md` |
| 09-18 18:23 | pipe-r11 验收 PASS：26.83 美元，计费/实用 1.02，残留 0；看不出学习信号（0.553 / 0.544），长度无副作用 | `pipe-r11/report.md` |
| 09-18 19:26 | S1 启动：阶梯 A 500 题，带老师，学习率 1e-4，8 题 × 4，计划 60 步 | `训练方案.md` 第 12 节 |
| 09-19 02:22 | S1 停在第 12 步，按 Tinker 标准快检 | `runs/pipe-s1/PAUSED` |
| 09-19 04:05 | 快检 −0.172 [−0.285, −0.060]；SWE −0.232 显著，TL −0.117 不显著；输出 token 中位数 +48% | `pipe-s1/quickcheck-step12/` |
| 09-19 05:35 | 老师打分审计：实现正确，信号落在行文风格上 | `pipe-s1/teacher-scoring-audit/report.json`、`opd-then-rl-design.md` 第 5 节 |
| 09-19 06:08 | pipe-s2 阶段 A（纯 OPD）开始训练 | `runs/pipe-s2-driver.log` |
| 09-19 12:41 | 阶段 A 训练通过（delta 阶段失败，见第 6 节）；阶段 B 开始 | 同上、`runs/pipe-s2-rl/handover.log` |
| 09-19 12:44–12:47 | delta 修复（1c6b65b）、孤儿清理跳过 `KEEP_GPU_PROCESS=1`（1541ce7）提交并部署 | `tasks/memory.md` 12:45 一节、`gpu-schedule.md` |

**决策记录（都是负责人做的，时间为 UTC，出处是每日训练日记和 `tasks/memory.md`）：**

- 09-18 19:20：S1 带老师，用阶梯 A 立即起跑，不等单卡 pod。
- 09-19 约 02:20：暂停 S1，先快检。
- 09-19 03:00："teacher=1 就继续跑完"，快检只作参考。这一条被 04:05 的快检结果推翻。
- 09-19 04:50：再次暂停 S1，查老师打分格式。
- 09-19 05:40：路线定为先 OPD 后 RL。
- 09-19 07:53：批准磁盘第 1 档清理。
- 09-19 07:55："先完整训练完再说"。pipe-s2 不改动，中途不止损。
- 09-19 08:10：Modal 上限调到 900 美元。
- 09-19 08:41："全部训练都要完成"，于是挂了守护进程。
- 09-19 12:00：TB2.1 原版评测每题 3 次。
- 09-19 约 12:00：所有模型的评测统一在本 pod 上做。

## 2. 当前状态（12:33–12:52 UTC 只读核对）

| 对象 | 状态 | 位置 |
|---|---|---|
| pipe-s2 阶段 A | 12 步完成；`train/PASSED` 12:41:26 写入；final 是 `global_step_12`。收尾验证 mean@4 0.438 → 0.406（8 题 × 4，只能看方向）。delta 阶段失败（已修），summary 和 cost 没跑；A 的费用等 pipe-s2 结束后按小时账单合并核算 | `runs/pipe-s2-opd/` |
| pipe-s2 阶段 B | 12:41:48 开始训练，第 13–60 步。已核对：`load_contents=['model']`、从 A 的 `global_step_12` 恢复、预热 3 步、单卡、`TEACHER=0`、不思考。12:51 时还在加载 | `runs/pipe-s2-rl/train/train-command.txt` |
| GPU | 12:33（阶段 A 中）：GPU0 65.2 GB，利用率 90%（学生：WorkerDict 19.5 GB，vLLM 45.5 GB）；GPU1 77.5 GB（老师 vLLM）。12:51：GPU0 685 MiB，GPU1 3 MiB，阶段 B 还在加载，快检还在等 "Loaded model from"。**接手后先确认 B 真的开始跑第 13 步** | `nvidia-smi` |
| 评测产物 | `runs/qc-base` 有：0.612，58 题 114 条。`qc-pipe-s2-opd-step12`、`tb21-base-9b-n3`、`eval-v1-base-9b-n4` 都还没生成 | `runs/` |
| 磁盘 | `/` 73%，剩 28 GB；`/workspace` 是网络卷；`runs/pipe-s2-opd` 占 58 GB | `df -h` |
| 代码 | 本机 HEAD 1541ce7，已推送，与 origin 一致。pod 源码的 manifest 是 613aab9（05:27 rsync），之后单独拷上去的有：`supervise_run.sh`（08:40）、`stages/50_delta.sh`（12:44）、`run_opd_round.sh` 和 `gpu_orphans.sh`（12:46）。12:52 核对，这些文件和 `run_opd_then_rl.sh` 的 md5 都与 HEAD 一致 | `runs/source-manifest-613aab9.json` |
| 数据隔离 | 已核：pipe-s2 的训练 500 题、验证 8 题与 eval-set-v1 78 题，按题、按 SWE 仓库的重叠都是 0；quick 58 题是 eval-set-v1 的子集 | `data-pipe-s2-opd/stage1/`、`data-eval-set-v1/` |
| Modal | **本次没核到**：本机 `modal billing summary` 报 "Could not connect to the Modal server"。最近的数字：本线 08:10 记为本月 624.67 美元；Tinker 文档 12:30 UTC 记为用量约 660 美元，上限 900 | 第 8 节 |

**阶段 A 逐步指标**（`runs/pipe-s2-opd/train/metrics-20260919T060827Z.jsonl`）：

| 步 | 解题率 | 回复均长（token） | 撞上限 | 蒸馏损失 | 用时（分） |
|---|---|---|---|---|---|
| 1 | 0.733 | 16,243 | 3.3% | 0.108 | 25 |
| 2 | 0.433 | 19,511 | 3.3% | 0.117 | 21 |
| 3 | 0.500 | 22,840 | 3.1% | 0.101 | 30 |
| 4 | 0.484 | 20,971 | 3.2% | 0.108 | 22 |
| 5 | 0.613 | 22,029 | 3.2% | 0.084 | 23 |
| 6 | 0.531 | 18,393 | 3.1% | 0.080 | 21 |
| 7 | 0.500 | 23,324 | 3.3% | 0.058 | 29 |
| 8 | 0.312 | 23,154 | 3.1% | 0.060 | 32 |
| 9 | 0.517 | 23,025 | 3.4% | 0.056 | 29 |
| 10 | 0.367 | 25,958 | 3.3% | 0.051 | 34 |
| 11 | 0.500 | 19,749 | 3.3% | 0.057 | 21 |
| 12 | 0.312 | 25,234 | 3.1% | 0.066 | — |

读法：解题率就是 `critic/score/mean`，纯 OPD 阶段只记录、不进梯度；每步都是不同的题，步与步不能直接比。回复长度从 1.6 万涨到 2.0–2.6 万 token；撞上限一直在 3.1%–3.4%，没到"20% 就报告"的线。

**pod 上的四个后台作业**（都用 `launch-detached.sh` 启动，按会话号 sid 管理）：

| 作业 | sid | 做什么 | 日志 | 怎么查 |
|---|---|---|---|---|
| 驱动 `run_opd_then_rl.sh` | 1530153 | 阶段 A，然后阶段 B；启动命令在 `runs/pipe-s2-launch.txt` | `runs/pipe-s2-driver.log` | 看末尾 `[round …]`、`[driver …]` 行；退出时写 `[detached] exit=` |
| 守护 `supervise_run.sh` | 1734737（12:07 起；第一个实例 1630551 已换下，日志是 `pipe-s2-supervise.attempt1.log`） | 驱动退出后，如果 `runs/pipe-s2-done-check.txt` 不成立（要求 `pipe-s2-rl/train/PASSED` 存在，并且 final 是 `global_step_60`），就用原命令续跑。最多续跑 3 次。续跑前等所有 `verl.trainer.main_ppo` 退出，最多等 14 小时（`TRAINER_WAIT_POLLS=420` × 120 秒）。它自己从不杀进程 | `runs/pipe-s2-supervise.log` | 现在只有两行 start/cmd。出现 `relaunch`、`giving up`、`still alive` 就要处理 |
| 快检 `runs/pipe-s2-qc-a.sh` | 1530184 | 等 B 的 `train.log` 出现 "Loaded model from"，再等 600 秒，然后选显存小于 2000 MiB 的卡，用 `eval_val_only.sh` 跑 A 的 final：quick 58 × 2。没有空卡就 exit 3，不跑 | `runs/pipe-s2-qc-a.log` | 产物 `runs/qc-pipe-s2-opd-step12/summary.json` |
| 评测队列 `runs/pipe-s2-evalq.sh` | 1734775 | 等快检日志出现 `[detached] exit`，最多等 10 小时，也就是到约 22:07。然后在空卡上依次跑 `tb21-base-9b-n3`（TB2.1 89 × 3，约 8 小时）和 `eval-v1-base-9b-n4`（78 × 4，约 3 小时）。每一项没有空卡就跳过 | `runs/pipe-s2-evalq.log` | 产物是两个目录下的 `summary.json` |

**时间推算（会浮动）：** 快检约 13:00–14:30；TB2.1 原版约 14:30–22:30；eval-set-v1 原版约 22:30–01:30。**eval-set-v1 可能拖过 01:00**，挤占评测会话的 GPU1 窗口。00:30 前核一次进度，拖了就和评测会话商量。

## 3. 本轮交付物（09-18 18:30 以后）

**代码（已提交、已推送）：**

| 提交 | 文件（行数） | 作用 |
|---|---|---|
| 047a187 | `examples/harbor_opd_rl/eval_val_only.sh`（99）、`eval_pair_report.py`（72）、`eval_taskdeclared.yaml`（47）、`merge_lora_checkpoint.py`（122）、`prepare_eval_set.py`（136）；`eval_tb21.sh`（96）有改动 | 原版与训练后模型在 eval-set-v1 上配对评测；LoRA 合并带 ΔW 检查 |
| b6f0735 | `stages/10_data.sh`、`stages/40_train.sh`、`train_tb21_lora_smoke.sh`（340） | S1 用的开关：学习率与预热、验证采样、永久保留 checkpoint、分层打散取题 |
| 5041d40 | `eval_val_only.sh` | `EVAL_RUN` 从 run 里读 LoRA 等参数，用于从 checkpoint 评测 |
| ca7f393 | `eval_behavior_report.py`（118） | 按来源统计行为：token、跑满轮数、超时、解析错误 |
| e178270 | `stages/file_logger_metrics.py`（54）、`stages/40_train.sh`（151）、`stages/60_resume.sh`；测试 `tests/uni_agent/examples/test_harbor_file_logger_metrics.py`（50） | 每次尝试写一个指标文件；控制台缺行时从这些文件取指标 |
| 613aab9 | `run_opd_then_rl.sh`（113）、`stages/teacher_format_check.py`（330）、`diag_teacher_scoring.py`（284）、`run_opd_round.sh`（176，加了格式守卫）、`40_train.sh`（冻结蒸馏参数）、`train_tb21_lora_smoke.sh`（`CKPT_LOAD_CONTENTS`）；测试 `test_harbor_opd_then_rl.py`（190）、`test_harbor_teacher_format_check.py`（245） | 分阶段驱动、老师格式守卫、老师打分诊断 |
| 9a1284a | `supervise_run.sh`（51）；测试 `test_harbor_supervise_run.py`（63） | 驱动崩了就续跑，直到 run 完成 |
| 1c6b65b | `stages/50_delta.sh`（29）；测试 `test_harbor_delta_stage.py`（70） | delta 取最早一个仍有模型文件的 checkpoint，不再挑中轮转留下的空壳 |
| 1541ce7 | `gpu_orphans.sh`（21，新）、`run_opd_round.sh`（178）、`gpu-schedule.md`；测试 `test_harbor_gpu_orphans.py`（53） | 孤儿进程清理跳过环境里带 `KEEP_GPU_PROCESS=1` 的进程及其子进程 |

**文档（已提交）：**
- `每日训练日记.md`（117 行，9d2f159、60929b9）、`gpu-schedule.md`（40，9b439b7、1541ce7）、`opd-then-rl-design.md`（121，61062e0、a960af2）、`verl-vs-tinker-algorithm.md`（36，2916e86，61062e0 更正）、`训练方案.md`（183，96ceddc、11589a9、692d2cb）。
- `tasks/memory.md`（444，最新一节"12:45 pipe-s2 阶段 A 完成"，60929b9）、`tasks/lessons.md`（56，新增第 47–53 条）、`tasks/todo.md`（165，H6、H7）。
- `tasks/handoff-history-20260918-1830.md`（83 行，旧版交接原样归档，60929b9）。
- 证据：`pipe-r11/`（d55feb5）、`pipe-s1/quickcheck-step12/`（6 个 json，1927623）、`pipe-s1/teacher-scoring-audit/report.json`（344 行，a960af2）。

**没提交（本次交接写的）：** `tasks/handoff.md`（本文，重写）、`handoff/交接训练claude-to-codex-0919-2050.md`（给 Codex 的封面）。

## 4. 数据集现状与缺口

| 集合 | 规模 | 位置 | 用途 |
|---|---|---|---|
| 阶梯 A `stage1-ladderA-v1` | 训练 500 题：SWE easy 253、SWE medium 23、TL easy 25、TL medium 199；另有验证 8 题 | HF `gump2049/xDAN-Harbor-Stage1-Tasks`（`10_data.sh` 默认的 `STAGE1_REPO`）；pod `data-pipe-s2-opd/stage1/` | S1 和 pipe-s2 的训练数据。按"来源 × 难度"分层打散，种子 20260918 |
| eval-set-v1 | 78 题：SWE 28、TL 50 | pod `data-eval-set-v1/eval/harbor_tasks-eval.parquet`；保留名单在 HF `gump2049/xDAN-Harbor-Stage1-Tasks-Full` 的 `eval-set-v1/reserved.json` | 最终结论：78 × 4 |
| quick | 58 题：SWE 28、TL 30，是 eval-set-v1 的子集 | `data-eval-set-v1/quick/harbor_tasks-quick.parquet` | 节点快检：58 × 2 |
| TB2.1 | 89 题 | `data/tb21-full/harbor_terminal-bench_terminal-bench-2-1.parquet` | 本线口径（见下），**不能和 Tinker 官方口径（`tb21o-`）比** |

- **本线的 TB2.1 口径：** 不思考；时限按任务声明，但单个 trial 最多 3000 秒（`eval_taskdeclared.yaml`）；每题 3 次（`pipe-s2-evalq.sh` 设定）。
- **用量：** 60 步 × 8 题 = 480 题，所以 pipe-s2 用不完一遍阶梯 A。只用 RL 的下一轮可以原样复用这份数据，不缺题。
- **扩大规模的缺口**（`训练方案.md` 第 3 节，以及 Tinker 交接第 4 节）：
  - TL medium 可训练的 202 题里，阶梯 A 已用 199 题；
  - SWE easy 还剩约 131 题；
  - SWE medium 原版通过率只有 0.07，RL 信号弱；
  - 再扩大要等数据线补审 TL（在 Modal 上审）。
- **注意：** pipe-s2 数据阶段的日志是 `reserved eval sets [] … excluded 0`，说明本地没有再剔除一遍，靠的是切片发布时已经剔除。今天已按题、按仓库复核，重叠是 0。

## 5. 设计约束（铁律）

1. **回复用户用中文**，包括一两句的通知（lessons 36）。按全局规则分"直接执行"和"深度交互"两部分。
2. **token 和密钥不进仓库。** 凭据只放在 pod 的 `/root`（`.netrc`、`.modal.toml`）和本机 home（`~/.zshenv` 里的 `$GH_TOKEN`）；不打印任何 key。
3. **杀进程分两步。** 第一条命令只读，列出 PID；第二条命令只含数字，或者是 `pkill -TERM -s <sid>`（lessons 7、24、41）。不碰其他项目的进程：这台 pod 上还有 metarsi-apus、skyrl，还有评测会话的 vLLM。
4. **每次 push 前跑 `ruff check .` 和 `ruff format --check .`，不接管道**（lessons 11）。只 `git add` 自己确认过的路径，不用裸 `git stash`；到里程碑就 commit 并 push。
5. **每次运行 `sync-source.sh` 之后，都重跑 `deployment/bootstrap/apply-verl-patches.sh`，看到 `already=1` 才能启动或续跑**（lessons 52）。
   - 有 run 正在执行某个脚本时，不能原地覆盖它（lessons 31）。只换一个文件的话，先写临时文件，再 `mv` 过去。
6. **短训练的 LoRA 不合并进 bf16。** 评测一律走 `eval_val_only.sh`（lessons 50），温度 1.0，每题多次（lessons 51）。
7. **说"格式不一致"之前**，先读这次运行的 `train-command.txt`，按网关真实的拼接方式构造序列，再用真实轨迹确认（lessons 53）。
8. **只凭配对区间下结论。** 区间下界大于 0 才算提升，上界小于 0 才算退步。SWE、TL、合计分开报。
9. **监控只在有变化时汇报。** 用一次性后台等待，醒来就重挂（lessons 48），汇报前先核对当前时间。
10. **一切脚本化、脱机运行。** 远端长任务一律 `launch-detached.sh`，链条放在服务器端串；Mac 断网不能影响训练（lessons 16）。
11. **Modal 上限 900 美元，与 Tinker 线共用。** 花钱前先查 `modal billing summary` 或 `modal billing report`，快到上限就停下来汇报。CLI 读不到上限值，以负责人的确认为准。
12. **跑什么、停不停，由负责人决定。** pipe-s2 不设止损（07:55 的决定）。换模型或换关键配置，先跑 `--smoke`（lessons 37）。
13. **到里程碑就更新每日训练日记和 `tasks/memory.md`**；踩了坑写进 `tasks/lessons.md`。
14. **架构分工：** Uni-Agent 管 Agent、Task、Gateway 和轨迹准入；VERL 管优化器；Harbor 管 verifier；Modal 只提供沙箱。奖励默认二值；看效果要看二值解决率（lessons 46）。

## 6. 已踩过的坑（真实行为）

- **VERL 文件记录器用 "wb" 打开指标文件。** 续跑会覆盖前一次的逐步指标。e178270 改成每次尝试一个文件：`<stage>/metrics-<开始 UTC>.jsonl`。
- **控制台的 `step:N - …` 行会丢。** Ray actor 的输出有缓冲；阶段 A 11 步只看到 10 行。所以看进度读上面那个 jsonl（格式是 `{"step":N,"data":{…}}`），不要 grep `train.log`。
- **`train.log` 里的 `RayTaskError(HarborInfraFailure)` 不是致命错误。** 它表示一个会话碰上了基础设施故障，框架剔除这条会话，不足就整组补题。阶段 A 到 12:35 共出现 13 行，训练没受影响。
  - 丢组的 WARNING 不进 `train.log`，要看指标 `training/rollout_failure/evicted_samples`（lessons 49）。
- **`stop_lingering_trainer` 会清场**（`stages/common.sh:59-67`，在 `40_train.sh:146` 调用）。每个训练阶段收尾时，它结束**所有** `python -m verl.trainer.main_ppo`，再执行 `ray stop --force`。
  - 阶段 B 在 09-20 约 08:30–09:30 结束时会触发，所以用 `eval_val_only.sh` 跑的评测不要跨过这个时间。
  - 独立的 `vllm serve` 不走 Ray，不受影响。
- **`run_opd_round.sh` 会把别人的 GPU 进程当孤儿杀掉。**
  - 触发条件：没有 main_ppo 在跑，并且不是冒烟模式。这时它先 `ray stop --force`，再对孤儿列表发 `kill -TERM`。
  - 危险场景：阶段 B 崩溃，守护进程续跑，而评测会话的 vLLM 正在 GPU1 上。
  - 1541ce7 起，孤儿列表由 `gpu_orphans.sh` 生成，跳过 `/proc/<pid>/environ` 里带 `KEEP_GPU_PROCESS=1` 的进程；子进程继承这个变量，所以 vLLM EngineCore 也会被保留。**读不到环境的进程仍算孤儿**，外部进程必须自己导出这个变量。
- **delta 阶段曾拿到空壳 checkpoint 而失败。** `MAX_CKPT_TO_KEEP=3` 轮转时只删 `actor/`，留下只剩 `data.pt` 的 `global_step_1`，旧的 `50_delta.sh` 拿它当第一个 checkpoint。
  - 阶段 A 的驱动因此停在 delta，summary 和 cost 都没跑；设计上 B 照常开始。
  - 1c6b65b 已修复并部署，B 收尾时会用新脚本。即使 delta 再失败，守护进程的完成判据也只看 `train/PASSED` 和 `global_step_60`，不会误续跑。
- **不分块的 vLLM prompt logprob 预填充，在显存比例 0.7 时 OOM。** 一个 2.1 万 token 的提示要约 20 GB。所以诊断脚本里"不分块"这条路径改由 HF 参考覆盖。
  - 老师显存要给 prompt logprobs 留余量（lessons 33、35）。
- **守护和防重检查不能用进程模式匹配。** 第一次挂守护时，防重检查匹配到了自己的 ssh 命令，误报"已在运行"。改用日志文件或 sid 判断。
- **Modal CLI 看不到花费上限。** 本机访问 Modal 时常报 "Could not connect"，重试一两次，不要循环重试（lessons 28）。
- **SSH 经常断。** 只读命令外面包重试：`for i in 1 2 3 4; do ssh … && break; sleep 10; done`；启动任务一律 `launch-detached.sh`（日志追加写）；同步源码时断线会让 VERL 补丁缺失，要重打（lessons 52）。
- **纯 OPD 阶段日志里仍有 `actor/pg_loss`。** VERL 照常计算这个指标，但 `use_task_rewards=False` 时 policy loss 置 0，不进梯度。
- **VERL 的 TB2.1 评测不符合官方口径**：不思考、trial 上限 3000 秒、每题 3 次。所以 `tb21-base-9b-n3` 只能和 pipe-s2 自己配对。
- **还没修的**（`tasks/todo.md` H6、H7）：超时的轨迹被丢弃，而不是记 0 分；超时后用 SIGKILL 强杀，Harbor 来不及关沙箱，沙箱要空转 20 分钟才被回收；熔断没有实现。

## 7. 下一步清单

- [x] 孤儿进程清理跳过 `KEEP_GPU_PROCESS=1`（1541ce7），delta 修复（1c6b65b）。都已提交、推送，12:44–12:46 单文件部署到 pod，md5 已核。
- [x] 已通知评测会话 5e（13:10 确认）：启动 vLLM 时导出 `KEEP_GPU_PROCESS=1`，排期照 `gpu-schedule.md`。
- [ ] **确认阶段 B 开始跑**：`runs/pipe-s2-rl/train/train.log` 出现 "Loaded model from"，之后出现第 13 步的指标文件。
- [ ] pipe-s2 结束后核算阶段 A 和 B 的 Modal 费用：按小时账单合并算，因为 A 的 cost 阶段没跑。
- [ ] **收快检结果**：`runs/qc-pipe-s2-opd-step12/summary.json` 出现后，跑 `eval_pair_report.py runs/qc-base/summary.json runs/qc-pipe-s2-opd-step12/summary.json --labels base pipe-s2-opd-step12`，再跑 `eval_behavior_report.py`。
  - 参照：Tinker E' −0.129，S1 −0.172。
  - 写进 `tasks/memory.md` 和日记；报告用户，同步给 1a 和 76。
- [ ] **盯阶段 B**：第 20、40、60 步永久保留 checkpoint（`runs/pipe-s2-rl/train/pinned/`），并各做一次验证；撞上限比例超过 20% 要报告；看 `evicted_samples`；守护日志有新行就处理。
- [ ] **00:30 前核评测队列**：eval-set-v1 原版如果会拖过 01:00，和评测会话商量。
- [ ] **第 60 步之后（约 09-20 08:30–09:30）做最终评测。** 等驱动写出 `[detached] exit=` 之后，在 GPU0 上跑（在 pod 的 `src/uni-agent` 目录下）：

```bash
L=/workspace/verl-uni-agent-harbor-opd-rl; CK=$(cat $L/runs/pipe-s2-rl/train/final-checkpoint.txt)   # 应以 global_step_60 结尾
bash examples/harbor_opd_rl/launch-detached.sh $L/runs/eval-v1-pipe-s2-step60.log \
  "EVAL_ROOT=$L/runs/eval-v1-pipe-s2-step60 CUDA_VISIBLE_DEVICES=0 EVAL_RUN=$L/runs/pipe-s2-rl RESUME_FROM=$CK EVAL_N=4 CONCURRENCY=16 bash examples/harbor_opd_rl/eval_val_only.sh && \
   EVAL_ROOT=$L/runs/tb21-pipe-s2-step60-n3 CUDA_VISIBLE_DEVICES=0 EVAL_RUN=$L/runs/pipe-s2-rl RESUME_FROM=$CK EVAL_DATA=$L/data/tb21-full/harbor_terminal-bench_terminal-bench-2-1.parquet EVAL_N=3 CONCURRENCY=16 bash examples/harbor_opd_rl/eval_val_only.sh"
```

  - 配对：eval-set-v1 对 `runs/eval-v1-base-9b-n4`，TB2.1 对 `runs/tb21-base-9b-n3`。按 SWE、TL、合计出区间，附行为报告。
  - 下结论，回答"重置优化器后，RL 能否从 OPD 起点追回来"，并与 Tinker 分阶段 run（−0.160）和 A'（+0.199）对照。
  - 同步给 1a，由 1a 补进 `open-question-opd-harm.md` 第 7 节。
- [ ] **D1：测老师 Qwen3.8-27B 在无思考时的能力**，用 quick 集，约 1 小时、约 10 美元（`opd-then-rl-design.md` 第 3 节）。还没有脚本，先确认 27B 在单卡上跑 `eval_val_only.sh` 装得下；需要负责人批准，并排一个 GPU 窗口。
- [ ] **下一轮训练（等负责人定）：**
  - 推荐只用 RL：`TEACHER=0`，同一份阶梯 A，60 步，与 Tinker A' 对齐。要严格复现 Tinker，再加 `norm_adv_by_std_in_grpo=False`（`verl-vs-tinker-algorithm.md`）。
  - 可选的 OPD 变体只在 D1 证明老师明显更强之后考虑：只蒸馏动作 token 的掩码，加结果门控，系数 0.1。
- [ ] **磁盘第 2 档清理（约 446 GB）等负责人批。** 文档里只记了体量，要先用只读的 `du` 重新列清单。
- [ ] **可选：`SAVE_LORA_ONLY=True` 缩小 checkpoint。** `train_tb21_lora_smoke.sh:69` 默认是 False。启用前要验证续跑和 `eval_val_only.sh` 在只有 LoRA 的 checkpoint 上照常工作。
- [ ] **问负责人：pipe-s2 final 要不要上传 HF**（gump2049，私有）。按约 12:00 定的规矩，模型版本统一上 HF。
- [ ] **下一轮开训之前修掉 H7 的两项**：超时记 0 分；先 SIGTERM，再 SIGKILL。
- [ ] 到里程碑更新 `每日训练日记.md`（09-20 新开一节）和 `tasks/memory.md`，然后 commit、push。

## 8. 分支、部署与账号

- **分支 `verl-uni-agent-harbor-opd-rl`**：上游 `origin/verl-uni-agent-harbor-opd-rl`（`https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent.git`），12:52 时 HEAD 1541ce7，已推送。PAT 在本机 `~/.zshenv` 的 `$GH_TOKEN` 里，不写进任何文件。
- **CI**：`ci.yml` 只在推送到 main、develop 或向 main 提 PR 时触发；本线的门禁是本地 ruff 双检加 `tests/uni_agent/examples/` 下的相关测试。
- **pod**：2 × RTX PRO 6000 Blackwell，每张 96 GB；容器盘 `/` 100 GB，不放权重，只有 `/workspace` 能持久保存。端口变了先跑 `deployment/bootstrap/gpu-pod-restore.sh <新端口>`。训练时 `run_opd_round.sh` 会把模型暂存到 `/tmp/models/`。单卡 pod（端口 12063）09-17 起没再用过，状态没核。
- **代码同步**：本机 `bash deployment/bootstrap/sync-source.sh 11965 --rsync`，再跑 `apply-verl-patches.sh` 看到 `already=1`。有 run 在跑时只换单个文件。pod 上的 `runs/source-manifest-<sha>.json` 记录同步的是哪个提交。
- **Modal**：工作区 l98348740，pod 上的配置是 `/root/.modal.toml`；沙箱都在应用 `verl-harbor` 下；上限 900 美元，与 Tinker 线共用。
  - 查账：`modal billing summary`，或 `modal billing report --for yesterday --show-resources`。
  - 杀掉一轮训练后清理沙箱：`HARBOR_MODAL_APP=verl-harbor bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than 0`。
- **W&B**：entity `xdan-ai`，项目 `xDAN-Verl-Uni-agent-Harbor-rl-opd`；凭据在 pod 的 `/root/.netrc`。
- **HF**：数据在 `gump2049/xDAN-Harbor-Stage1-Tasks`（切片）和 `gump2049/xDAN-Harbor-Stage1-Tasks-Full`（审计索引、`eval-set-v1/reserved.json`），都是私有。本线还没有往 HF 上传过模型。
- **checkpoint**：路径 `runs/<run>/train/checkpoints/xDAN-Verl-Uni-agent-Harbor-rl-opd/pipe-train/global_step_N`，只留最近 3 个；第 20、40、60 步用硬链接永久保留在 `train/pinned/`；S1 的第 12 步在 `runs/pipe-s1/train/pinned/global_step_12`。

## 9. 冷启动 checklist

1. 读本文，再按第 10 节第一层读。
2. `git -C /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl status -sb`，再跑 `log --oneline -10`，看 1541ce7 之后有没有新提交。
3. 查 pod 状态（只读，在 zsh 或 bash 里都能用）：

```bash
pod() { ssh -o ConnectTimeout=30 -o BatchMode=yes -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177 "$@"; }
for i in 1 2 3 4; do pod 'date -u; cd /workspace/verl-uni-agent-harbor-opd-rl/runs; nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader; ls pipe-s2-opd/train/PASSED pipe-s2-rl/train/PASSED pipe-s2-rl/train/pinned 2>&1; for f in pipe-s2-driver pipe-s2-supervise pipe-s2-qc-a pipe-s2-evalq; do echo "== $f"; tail -n 3 $f.log | cut -c1-200; done; ls -d qc-pipe-s2-opd-step12 tb21-base-9b-n3 eval-v1-base-9b-n4 2>&1' && break; sleep 10; done
# 逐步指标：run、步、解题率、回复均长、撞上限、蒸馏损失
for i in 1 2 3 4; do pod 'cd /workspace/verl-uni-agent-harbor-opd-rl/runs && python3 - <<"EOF"
import json, glob
for f in sorted(glob.glob("pipe-s2-opd/train/metrics-*.jsonl")) + sorted(glob.glob("pipe-s2-rl/train/metrics-*.jsonl")):
    for line in open(f):
        line = line.replace("\x00", "").strip()
        if not line: continue
        r = json.loads(line); d = r["data"]
        if "critic/score/mean" not in d: continue
        print(f.split("/")[0], r["step"], round(d["critic/score/mean"], 3), int(d["response_length/mean"]), round(d["response_length/clip_ratio"], 3), round(d.get("actor/distillation/loss", float("nan")), 4))
EOF' && break; sleep 10; done
```

4. 用 `ListAgents` 找 Tinker 训练会话（09-19 为 4b）和评测会话（09-19 为 5e）。会话名重启后会变，找不到时以两边的交接文档为准。
5. **重挂监控。** 在本机用后台 Bash（`run_in_background`）跑一次性等待：状态一变就退出、唤醒会话，处理完立刻重挂。它会在这些时候醒：阶段通过、出现永久保留的 checkpoint、评测产物生成、守护日志有新行、作业退出，以及 90 分钟没有新指标（`STALE`）。

```bash
pod() { ssh -o ConnectTimeout=30 -o BatchMode=yes -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177 "$@"; }
probe() { pod 'cd /workspace/verl-uni-agent-harbor-opd-rl/runs && echo OK; ls pipe-s2-opd/train/PASSED pipe-s2-rl/train/PASSED pipe-s2-rl/train/pinned qc-pipe-s2-opd-step12/summary.json tb21-base-9b-n3/summary.json eval-v1-base-9b-n4/summary.json 2>/dev/null; wc -l < pipe-s2-supervise.log; grep -h "^\[detached\] exit" pipe-s2-driver.log pipe-s2-qc-a.log pipe-s2-evalq.log; find pipe-s2-opd/train pipe-s2-rl/train -maxdepth 1 -name "metrics-*.jsonl" -mmin -90 2>/dev/null | grep -q . && echo fresh || echo STALE; true' 2>/dev/null; }
base=$(probe); until [[ "$base" == OK* ]]; do sleep 60; base=$(probe); done
while sleep 600; do now=$(probe); [[ "$now" == OK* && "$now" != "$base" ]] && { diff <(echo "$base") <(echo "$now"); break; }; done
```

6. **续跑或重启：**
   - **守护还在**：驱动崩了由它续跑，只需看 `runs/pipe-s2-supervise.log`。
   - **守护已放弃**（日志里有 `giving up` 或 `still alive; not relaunching`）：
     1. 先读 `runs/pipe-s2-driver.attempt-*.log` 和 `runs/pipe-s2-rl/train/train.attempt-*.log` 查原因；
     2. 用只读命令确认没有 `main_ppo` 在跑；
     3. 在 `src/uni-agent` 下重挂守护。驱动日志里已经有 `exit=`，守护会马上判断完成与否并续跑，计数从 0 开始：

```bash
L=/workspace/verl-uni-agent-harbor-opd-rl
bash examples/harbor_opd_rl/launch-detached.sh $L/runs/pipe-s2-supervise.log \
  "RUN_DIRS=\"$L/runs/pipe-s2-opd $L/runs/pipe-s2-rl\" TRAINER_WAIT_POLLS=420 bash examples/harbor_opd_rl/supervise_run.sh $L/runs/pipe-s2-driver.log \"\$(cat $L/runs/pipe-s2-done-check.txt)\" \"\$(cat $L/runs/pipe-s2-launch.txt)\" 3"
```

   - **只想单独续跑阶段 B**：先确认守护已经退出（否则会有两个驱动），再把 `pipe-s2-launch.txt` 里的命令前面加上 `PHASE=b`，用 `launch-detached.sh` 启动。它会从 B 自己最新的 checkpoint 全量恢复。
   - **pod 重建了**：先按 `.claude/skills/harbor-rl-operator/SKILL.md` 恢复环境，再重打补丁，最后按上面的方法重挂守护。
7. 向负责人确认第 7 节里等决定的几项：下一轮方案、D1、第 2 档清理、HF 上传。

## 10. 接手阅读清单（Codex 或新会话）

按顺序读。前两层读完就能接手，后面的用到再查。

**第一层：现状与规矩（约 20 分钟）**

- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/handoff.md`：本文，讲现状、铁律和下一步
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/每日训练日记.md`：09-17 到 09-19 每天的结论、决策和费用
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/gpu-schedule.md`：GPU 排期，以及和评测会话共用这台 pod 的规则
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/lessons.md`：53 条踩坑记录，重点看第 44–53 条
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/memory.md`：逐条台账，从"2026-09-18 21:20"那一节读起

**第二层：结论是怎么得来的**

- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/opd-then-rl-design.md`：第 0 节是格式更正，第 1 节是算法严查，第 5 节是老师打分审计
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/pipe-s1/quickcheck-step12/`：S1 快检的配对结果和行为指标
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/pipe-s1/teacher-scoring-audit/report.json`：打分审计的原始数字
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/verl-vs-tinker-algorithm.md`：两条线在算法上的差异，以更正后的表格为准
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/open-question-opd-harm.md`：OPD 为什么有害；第 5 节是 VERL 的证据，第 7 节等着 pipe-s2 的结果
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/retros/stage1-staged-opd-rl-v1-20260919-1130.md`：Tinker 的分阶段 run 为什么失败
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/retros/stage1-teacher-ablation-v1-20260919-0327.md`：A' 为什么成功

**第三层：数据与评测**

- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/训练方案.md`：第 3 节题池与切片，第 6 节评估规则，第 12 节 S1 的实际配置
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/eval-set-v1-design.md`：评估集怎么选的
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/tasks/handoff-eval.md`：第 2、3 节，TB2.1 官方口径，以及在本 pod 上的 vLLM 方案
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/pipe-r9/reward-floor-finding.md`：为什么奖励默认二值
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/pipe-r11/report.md`：上一轮验收的范本

**第四层：动手前查**

- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/handoff-history-20260918-1830.md`：第 2 节一条命令起一轮训练，第 4 节成本纪律
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/.claude/skills/harbor-rl-operator/SKILL.md`：从新 pod 到一次完整训练，给 agent 用的操作手册
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/operator-runbook.md`：同一套流程的人工版
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/modal-cost-postmortem.md`：沙箱单价与泄漏
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/todo.md`：H5 到 H7，没做完的修复

**代码入口**（都在 `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/` 下）：

- `examples/harbor_opd_rl/run_opd_then_rl.sh`：分阶段驱动，A 纯 OPD，B 纯 RL，用 `CKPT_LOAD_CONTENTS` 控制 B 恢复哪些内容
- `examples/harbor_opd_rl/supervise_run.sh`：驱动崩了就续跑，直到完成判据成立
- `examples/harbor_opd_rl/run_opd_round.sh`：一轮训练的入口，负责暂存模型、等额度、老师格式守卫，以及孤儿进程清理
- `examples/harbor_opd_rl/gpu_orphans.sh`：列出可以当孤儿清理的 GPU 进程，跳过带 `KEEP_GPU_PROCESS=1` 的
- `examples/harbor_opd_rl/stages/40_train.sh`：训练阶段，冻结参数、写指标文件，收尾时 `stop_lingering_trainer`
- `examples/harbor_opd_rl/train_tb21_lora_smoke.sh`：VERL 命令行的组装处，所有 `++` 覆盖都在这里
- `examples/harbor_opd_rl/stages/teacher_format_check.py`：带老师启动前，逐 token 比对网关序列和老师原生格式
- `examples/harbor_opd_rl/diag_teacher_scoring.py`：在真实轨迹上复算老师打分，三路对比
- `examples/harbor_opd_rl/stages/file_logger_metrics.py`：控制台缺行时，从指标文件恢复逐步指标
- `examples/harbor_opd_rl/eval_val_only.sh`：从 checkpoint 评测，不合并 LoRA；不给 `RESUME_FROM` 时评测的就是原版
- `examples/harbor_opd_rl/eval_tb21.sh`：完整 HF 权重的 TB2.1 评测，要求合并 LoRA，所以短训练不要用它
- `examples/harbor_opd_rl/eval_pair_report.py`：按题配对，bootstrap 出 95% 区间
- `examples/harbor_opd_rl/eval_behavior_report.py`：按来源统计 token、跑满轮数、超时、解析错误
- `examples/harbor_opd_rl/launch-detached.sh`：脱机启动；日志追加写，退出时写 `[detached] exit=`
- `deployment/bootstrap/sync-source.sh`：把本机 HEAD 同步到 pod
- `deployment/bootstrap/apply-verl-patches.sh`：打上 `patches/verl/0001-padding-rebuild-teacher-fields.patch`，要看到 `already=1`

**不要当作事实来源：**

- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/handoff-history.md`：09-15 的，里面有已撤回的阻塞归因
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/handoff-history-20260918-1830.md`：除第 2、4 节外的状态都过期了，比如 Modal 上限还写着 700
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/progress-report-2026-09-17.md`：09-17 的快照
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/tasks/notes.md`：09-15 的
- `verl-vs-tinker-algorithm.md` 的初版（2916e86）中"S1 蒸馏覆盖思考"的说法已被 61062e0 更正；`tasks/memory.md` 中 04:50 报告的"老师打分格式不一致"已在 05:40 一节撤回（lessons 53）
- `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/verl-uni-agent-harbor-opd-rl/训练方案.md` 第 5、8、9 节：S1、S1-ctl、S2 的分轮计划、止损条件和预算，写于 700 美元上限时期，已被 pipe-s2 和负责人"不止损"的决定取代
- `/Users/gumpm5/.claude/projects/-Users-gumpm5-Documents-Code-xDAN-DSH-uni-agent/memory/`：只给 Claude 会话用的索引，以仓库文档为准

## 11. 用户偏好

- 用中文沟通。按全局规则分"直接执行"和"深度交互"两部分，对不合理的路径直接提出更短、更便宜的办法。
- 只在有变化时汇报；汇报先核对当前时间，数字写到能复算（区间、样本量、步数、提交号）。
- 跑什么、停不停，由负责人决定；汇报节点时写清等待期间训练会继续花多少钱。
- 到里程碑就 commit、push，并更新每日训练日记；方案、台账、复盘都要能回溯。
- 对成本敏感，花钱前说金额；Modal 与 Tinker 线共用额度。
- 一切脚本化、脱机运行，Mac 断网不影响训练。
- 跨项目的办法要搬过来落地，不能只贴链接（lessons 5）。
