# VERL pod GPU 排期与共用规则

pod：`ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177`，2 × RTX PRO 6000 96 GB。连接常断，远程命令要包重试。pod 重建后端口会变。

## 排期（UTC）

| 时段 | GPU0 | GPU1 |
|---|---|---|
| 09-19 06:08 起 | pipe-s2 阶段 A 学生 | pipe-s2 阶段 A 老师 |
| 09-19 13:00 起 | pipe-s2 阶段 B（每步约 31–36 分钟，**预计 09-20 13:00–16:00 到第 60 步**） | 13:09 起：阶段 A 快检（比预计慢，约 17:00 结束） |
| 09-19 约 17:00–22:00 | 同上 | eval-set-v1 原版 78 × 4（`runs/eval-v1-base-9b-n4`，由 `runs/pipe-s2-evalq2.sh` 自动执行） |
| 09-20 01:00–07:30 | 同上 | **Tinker 评测会话 5e：部署验收**（07:30 硬截止） |
| 09-20 08:30 以后 | 同上，直到约 13:00–16:00；之后跑 pipe-s2 最终模型评测（eval-set-v1 78 × 4 加 TB2.1 89 × 3） | **5e：全量**（一个 `vllm serve --enable-lora` 承载原版和 A'），约 6–8 小时 |
| 09-20 5e 全量结束后 | 同上 | TB2.1 原版 89 × 3（从 09-19 挪到这里，以免挤占 5e 的窗口） |

GPU1 上 09-19 晚间的评测由 `runs/pipe-s2-evalq2.sh` 自动排队。它在 14:21 替换了 `pipe-s2-evalq.sh`：替换时旧队列只在等待，没有跑任何评测。时间会随训练速度浮动，启动前先看显存（小于 2 GB 才算空闲）。

## 共用规则

1. **`run_opd_round.sh` 会误杀别人的 GPU 进程。** 每轮开始时，如果没有 `verl.trainer.main_ppo` 在跑，它会 `kill -TERM` 所有占着 GPU 的进程，当作孤儿处理。pipe-s2 由守护进程 `supervise_run.sh` 看护，阶段 B 崩溃后会自动续跑，续跑就会执行这一步。
   - **已修复（09-19 12:50，已部署）**：孤儿列表由 `examples/harbor_opd_rl/gpu_orphans.sh` 生成，环境变量中带 `KEEP_GPU_PROCESS=1` 的进程（及继承该变量的子进程，比如 vLLM EngineCore）会被跳过。
   - **外部进程启动时务必导出 `KEEP_GPU_PROCESS=1`**，例如 `KEEP_GPU_PROCESS=1 vllm serve ...`。
2. **训练阶段收尾时会清场。** `40_train.sh` 的 `stop_lingering_trainer` 会结束所有 `verl.trainer.main_ppo` 并执行 `ray stop --force`。约 09-20 08:30 pipe-s2 结束时会触发。独立的、不走 Ray 的 `vllm serve` 不受影响；用 `eval_val_only.sh` 或 `eval_tb21.sh` 跑的评测不要跨过这个时间点。
3. **启动前的冲突与等待。**
   - `run_opd_round.sh` 发现有 main_ppo 在跑时会拒绝启动。
   - 守护进程续跑前会等所有 main_ppo 退出，最多等 14 小时。
   - 在训练期间跑 VERL 类评测，会推迟崩溃后的自动续跑。
4. **磁盘。** `/workspace` 是网络卷，09-19 清理出约 146 GB；外部项目放到自己的目录，例如 `/workspace/tinker-eval/`。容器盘 `/` 和 `/tmp` 共约 100 GB，只剩约 28 GB，不要放权重。
5. **环境和账号。**
   - `envs/ua-verl-py312-vllm023-ws1`（vLLM 0.23.0）可以只读借用。
   - Harbor 请装在自己的 venv 里。
   - Modal 用的是 `/root/.modal.toml`，工作区 l98348740，两条线共用 900 美元上限。

## 评测入口（本线）

- `examples/harbor_opd_rl/eval_tb21.sh`：完整 HF 权重，经网关加 vLLM，Harbor 用 terminus-2，不思考。
- `examples/harbor_opd_rl/eval_val_only.sh`：VERL 的 LoRA checkpoint，不合并。
- 两者都配合 `eval_taskdeclared.yaml` 使用（按任务声明的时限，试验上限 3000 秒）。TB2.1 数据：`/workspace/verl-uni-agent-harbor-opd-rl/data/tb21-full/`。
- 汇总：`eval_pair_report.py`、`eval_behavior_report.py`。
- 短训练的 LoRA 不要合并进 bf16，合并后基本就是原版。`merge_lora_checkpoint.py` 自带 ΔW 检查。
