# 四题独立reload执行记录 r1

状态：运行中，不能作为完成证据。源码9dea127bf7bb69eb916aebcc0ab69ff86f53df08已推送GitHub并部署独立checkout `/workspace/rebuild/uni-agent-work-state-singletons-r1`；复用 `/workspace/venvs/uni-agent-rebuild-cf2d3f5`，固定VERL显式补丁核验通过。

## 已通过检查

- 控制器19项CPU测试通过，含真实SIGTERM子进程清理、末题母checkpoint漂移和错误任务/消费数拒绝。
- Mac准备器测试在收集导入阶段中断，未计通过；Linux `/root/runs/work-state-singletons-cpu-r1/result.json` 追加3项after_run_recheck于2026-09-09 10:06:56 UTC退出0。
- Ruff check/format双门通过。部署未修改旧run/环境/母checkpoint。

## 当前运行

- driver PID270247；驱动记录 `/root/runs/work-state-singletons-cpu-r1/`。
- suite `/root/runs/ws-r4-isolated-eval-r1`，启动记录同级 `ws-r4-isolated-eval-r1-launch.json`，主日志同级 `-launch.log`。
- 母训练 `/root/runs/work-state-train-r4`，母checkpoint `/workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_8`，母源码5b4b01b保留。
- 固定WS01/03/05/06 variant1 seed303，逐题独立run、同母状态/预算；运行中看suite `summary.json`。
- 10:12:39 UTC采样：第一题WS01 running，398/398权重加载记录，GPU0%/9039MiB；并非模型任务或消费验收完成。

## 退出判定

`all_attempted`只表示四个作业均退出；`all_verified`才表示各题独立消费均通过。任何失败均保留，最终进程可能非零退出；不删失败题、不补零奖励或伪造dump。每题重核母checkpoint与源码身份，实际加载记录/无额外更新仍要检查。

本轮只补工程独立加载与评估收尾。原课程8步全零梯度/参数不变的结论不变，原W4未完成；下一短课程仅设计，不冒充已实现或已更新。
