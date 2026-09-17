# Lessons：verl-uni-agent-harbor-opd-rl

1. **venv 不能建在 pod 本地盘。** 2026-09-16 发现之前通过 GPU 组件验证的 venv 在 `/tmp`，pod 重建后全丢，只剩 freeze 和 cache。规则：venv / cache / 模型 / 证据只放 `/workspace`，脚本层面拒绝其他路径（`uv-lane-bootstrap.sh`）。
2. **每个 GPU lane 的 freeze 必须进仓库。** 远端 `runs/` 里的 freeze 是唯一幸存物，如果它也在本地盘就全没了。规则：每次改依赖后 `uv pip freeze` 覆盖 `deployment/versions/uv-lanes/<lane>.freeze.txt` 并同提交。
3. **SSH 端口随 pod 重建变化。** 12524 → 30284。规则：handoff 里写端口时标注日期，冷启动第一步先核。
4. **交接文档放 `docs/<worktree>/tasks/`，不放根目录 `tasks/`。** 旧位置的 handoff/notes/memory 已 git mv 过来。
5. **跨项目的运维办法要"继承"而不是"引用"。** 用户明确要求把 MetaRSI 的 uv 管理办法搬到本项目并按本项目路径落地，链接过去不算完成。
6. **DSH 专属校验不能带进 Harbor 路线。** `require_verifier_reward` 只有 `uni_agent/tasks/dsh` 会填 `TaskResult.verifier_reward`；Harbor adapter 只给 `reward` + `eval_completed`（`finished=None`）。带着它训练会让每个 session 失败并被 sync refill 反复重采，看起来像"卡住"。规则：从 DSH 脚本派生新 recipe 时逐条核对 `require_*` 与 postprocessor 是否依赖 DSH 字段；`mask_unfinished_episode` 只作用于 `finished is False`，None 不受影响。
7. **远端 `pgrep -f`/`kill` 会命中自己的 ssh shell。** 用 `pgrep -f <script名>` 杀进程时，承载该命令的 `bash -c` 自身也匹配，ssh 直接 255 断开。规则：用 `ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"` 这类锚定到可执行文件的模式；`pgrep -f "main_ppo"` 连存活检查都会误判（第二次踩：r2 已退出仍报 alive）。
8. **DAPO 依赖 reward 方差。** `filter_groups` 会把组内 reward 全相同的 group 扔掉重采，reward 全 0 时只会耗尽 `max_num_gen_batches` 后报错。先用 GRPO 拿到 0/1 混合再开 `DAPO=1`。
9. **VERL 训练结束后主进程可能挂在 wandb teardown。** r2 的 step、checkpoint、wandb 同步全部完成后，`wandb` atexit 抛 BrokenPipe，主进程不退出、`exit-code` 不写。规则：判定完成看 `global_step_N` 目录 + step 指标行 + wandb "View run"，不等 exit-code；起下一轮前按上一条的模式核进程再清理。
10. **Modal 消费上限是训练链路的硬依赖。** 一天内 oracle + rollout + 三轮训练约 80 个沙箱就触到了 workspace spend limit，表现为 `ResourceExhaustedError` → 每条 trial `Sandbox not found` → `fail_on_rollout_error` 终止。规则：起长训练前先在 Modal 控制台核余额/上限；acceptance 的 failure_reasons 里出现 `spend limit` 直接判外部阻塞，不重试。
11. **`ruff … | tail -1` 会吞掉退出码。** 用管道时 `&&` 判断的是 `tail` 的退出码，lint 失败照样 commit/push（f9e1fca 就这样漏过去了）。规则：门禁命令不接管道，或用 `set -o pipefail`；`ruff check .` 直接跑，不截断输出。
12. **Harbor 的 `--agent-timeout` 不覆盖卡在 Modal API 的沙箱调用。** attempt4 一条 fix-git trial 在 terminus-2 上下文摘要后卡在 Modal 调用 30+ 分钟（进程只连着 Modal 443，vLLM 空闲），整步被拖住。规则：Harbor task config 必设 `trial_timeout_sec`（适配器 `run_harbor_cli` 用 `asyncio.wait_for` 兜底，超时 exit 124）；训练脚本默认 `FAIL_ON_ROLLOUT_ERROR=0`，让 `sync_refill_failed_groups` 补组而不是中断整步；`modal container stop` 在非交互 shell 要加 `-y`。
13. **VERL v1 checkpoint 布局是 `global_step_N/actor/*.pt` + `data.pt`**（sync 旧布局把 .pt 直接放在 `global_step_N/`）。校验和 delta 都要兼容两种布局；attempt5 训练成功却被误判 "checkpoint missing" 白等一轮。
14. **`set -e -o pipefail` 下，grep/find 无匹配会让 `x=$(...)` 直接退出脚本，且没有任何输出。** `trainer_pids`、`find_final_ckpt` 两处都因此静默失败。规则：辅助函数里 `grep … || true`、`find` 前先 `[[ -d ]]`；阶段脚本失败时若 driver.log 没有本阶段任何行，先怀疑这一类。
15. **两个 pod 共享一个 `/workspace` 时，data 阶段会重建 `data/stage1/tasks-*`，可能打断另一 pod 正在启动的 trial。** 第二台机器起 pipeline 时用 `SKIP_STAGES=data`（沿用已 PASSED 的 parquet）或独立 `DATA_DIR`；`rsync --delete` 源码也只做一次。
16. **Mac 断网 → 两台 pod 的 Ray 同时收到 SIGTERM（2026-09-17 02:48/02:50）。** 用 `nohup … &` 从 ssh 命令里起的驱动仍和会话有隶属关系。规则：远端长任务一律 `examples/harbor_opd_rl/launch-detached.sh`（setsid + nohup + /dev/null，trap 记录信号），"训练完接评测"用服务器端 `;`/`&&` 链，不在 Mac 上挂等待。
17. **共享卷配额（500 GB）被 22 个 8.7 GB checkpoint 撑满，`Disk quota exceeded`。** 每条 run 只留首尾 checkpoint；清理前先核对哪个 checkpoint 可能损坏（保存中被杀的 `global_step_N` 会 `EOFError`），别把它前一个删了——pipe-r3 的 step 6 损坏、step 5 已删，只能重训。配额已加到 1 TB。
18. **checkpoint 保存后、指标上报前被杀 → 有 checkpoint 无指标。** 复用逻辑改为：控制台缺失则从 wandb 重建；仍缺最后一步时接受但写 `reuse-note.txt`。
19. **评测比训练更吃 Modal 额度。** 89 题 × n 次 = 每次基线 89–267 个沙箱，加上镜像构建也计费；两次基线把当天额度打穿，连带训练链被迫暂停。规则：基线评测先 n=1；起评测前用探针沙箱核额度；额度按"训练每步 batch×n + 评测题数×n"预估并留 50% 余量。`ImageBuildError: terminated due to external shut-down` 与 `NotFoundError/ConflictError` 成片出现都是额度耗尽的表现，不是任务本身的问题。
20. **共享卷上的 `pipeline-summary.jsonl` 可能出现 NUL 填充的撕裂行。** pod 断电/重建时正在 append 的一行被写成一串 `\0` 再接 JSON，`json.loads` 直接失败，summary/acceptance 整阶段 FAIL（pipe-r2 07:36）。规则：读 jsonl 证据一律去 NUL、跳空行；写证据的 `record` 保持单次 `printf`。
21. **验收要以记录为准，不以环境变量为准。** 重跑 `FROM_STAGE=acceptance` 时没带 `TRAIN_STEPS`，脚本用默认值算 `resume_continued` 得出 FAIL；同时控制台解析把非指标行记成 `{}`，让 `all_finite` 与 wandb 对账假失败。规则：验收从 train 记录里取实际步数；解析器丢弃没有 `training/global_step` 的行；假 FAIL 与真 FAIL 要在脚本里分清。
22. **Modal 的 spend limit 是"账期上限"设置，不是余额。** 报错原文 `Container terminated due to reaching billing cycle spend limit` / `Workspace … has exceeded its spend limit`：加 $10 后 2.5 小时内（pipe-r3 6 步 + resume + 89 题基线）第三次触顶。规则：训练前让用户在 Modal 工作区设置里把 spend limit 调到覆盖整个计划（每步 batch×n 个沙箱 + 评测题数×n，留 50% 余量）；链路上一律用 `deployment/bootstrap/modal-quota-wait.sh && …` 排队，额度恢复自动续跑，不靠人盯。

