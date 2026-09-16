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
