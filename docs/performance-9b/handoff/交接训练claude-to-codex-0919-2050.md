交接文档本身：
  /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/tasks/handoff.md

## 直接执行：Codex 接手阅读清单

**第一层：现状与规矩（约 20 分钟）**
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/tasks/handoff.md：现状、铁律、下一步
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/每日训练日记.md：09-17 到 09-19 每天的结论、决策、费用
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/gpu-schedule.md：GPU 排期，以及与 Tinker 评测会话共用 pod 的规则
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/tasks/lessons.md：踩过的坑，重点看第 44–53 条
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/tasks/memory.md：逐条台账，从"2026-09-18 21:20"一节读起

**第二层：结论是怎么得来的**
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/opd-then-rl-design.md：格式更正、算法严查、老师打分审计（第 0、1、5 节）
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/pipe-s1/quickcheck-step12/：S1 第 12 步退步 −0.172 的配对与行为证据
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/pipe-s1/teacher-scoring-audit/report.json：打分审计的原始数字
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/verl-vs-tinker-algorithm.md：两条线的算法差异（以更正后的版本为准）
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/open-question-opd-harm.md：OPD 为什么有害，读第 5、7 节
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/retros/stage1-staged-opd-rl-v1-20260919-1130.md：Tinker 先 OPD 再 RL 为什么失败

**第三层：数据与评测（写下一轮方案前必读）**
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/训练方案.md：题池、切片、评估规则、S1 的实际配置（第 3、6、12 节）
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/eval-set-v1-design.md：评估集怎么选的
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/tasks/handoff-eval.md：TB2.1 官方口径，以及在本 pod 上的 vLLM 方案（第 2、3 节）
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/pipe-r9/reward-floor-finding.md：为什么奖励默认二值
- /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/pipe-r11/report.md：上一轮验收的范本

第四层（动手前查）、代码入口、"不要当作事实来源"的清单：在交接文档第 10 节，同样都是绝对路径。

**pod 上的路径**（`ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177`，连接常断，只读命令包重试）：
- lane 根目录：/workspace/verl-uni-agent-harbor-opd-rl
- 源码（脚本都从这里跑）：/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent
- runs：/workspace/verl-uni-agent-harbor-opd-rl/runs（`pipe-s2-opd/` 是阶段 A，`pipe-s2-rl/` 是阶段 B，`qc-base/` 是快检基线）
- 日志：/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-s2-driver.log、pipe-s2-supervise.log、pipe-s2-qc-a.log、pipe-s2-evalq.log
- 启动命令与完成判据：/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-s2-launch.txt、pipe-s2-done-check.txt
- 环境：/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1（vLLM 0.23.0）；模型：/workspace/models/Qwen3.5-9B、/workspace/models/Qwen3.8-27B
- 数据：/workspace/verl-uni-agent-harbor-opd-rl/data-pipe-s2-opd/stage1/（阶梯 A 500 + 8）、data-eval-set-v1/eval/harbor_tasks-eval.parquet（78）、data-eval-set-v1/quick/harbor_tasks-quick.parquet（58）、data/tb21-full/harbor_terminal-bench_terminal-bench-2-1.parquet（89）
- 四个后台作业脚本：
  - 驱动：/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/examples/harbor_opd_rl/run_opd_then_rl.sh
  - 守护：/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/examples/harbor_opd_rl/supervise_run.sh
  - 阶段 A 快检：/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-s2-qc-a.sh
  - 原版评测队列：/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-s2-evalq.sh

## 深度交互

接手的时候，pipe-s2 正在阶段 B 中途（12:41 UTC 开始，预计 09-20 08:30–09:30 结束）。孤儿清理和 delta 两个修复 12:47 前已提交并部署，评测会话 5e（原 76）已确认：启动 vLLM 时会导出 `KEEP_GPU_PROCESS=1`。**剩下有时限的是**：00:30 前核一次原版评测队列会不会拖过 01:00，因为那之后评测会话要用 GPU1。阶段 B 在跑的时候不要整体跑 `sync-source.sh`，只换单个文件。

给 Codex 的启动指令本身也要带绝对路径。最省事的是一句话：

> 先读 /Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-uni-agent-harbor-opd-rl/docs/performance-9b/tasks/handoff.md，按第 10 节的顺序读完，先处理第 7 节里 09-20 01:00 UTC 截止的那一项，再开始动手。

其余路径都在交接文档里，指令就不必重复列一遍，免得两处不一致。
