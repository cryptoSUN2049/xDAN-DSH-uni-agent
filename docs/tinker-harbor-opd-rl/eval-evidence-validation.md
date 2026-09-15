# 评估证据关卡：本地实现与验收

2026-09-15。用户确认主线：**OPD 提供密集指导，RL 强化实际成功行为**。
本轮完成记录与验收逻辑，代码提交 `2ef293b6a173f28154a21f5c5df143ac280f5967`。尚未部署新云版本、运行新模型评估或训练。

## 结果

- 465 项相关离线回归通过，覆盖训练、蒸馏、评估、capture、Harbor 和沙箱资源调用方。
- 本轮涉及的 8 个实现模块：语句覆盖 88.98%，分支覆盖 77.23%，综合 86.34%。新增 harbor_eval_evidence.py 综合 91%。这是指定模块范围，不是全仓覆盖。
- 独立审查发现的 5 类缺口均已修复；另用 6 个本地最小复现复核，未发现阻止本轮交付的 P0/P1 问题。
- 实际 Cookbook 日志、模块导入和 Plotly bootstrap 在源码与临时安装的 wheel 中均通过；本机为 macOS，不能替代新 Linux 云镜像验收。
- 原验证节点仅修改文件的 Ruff 通过。2026-09-15 提交收尾已用独立 style commit 修复全仓基线：两处 union 类型顺序及 Markdown 代码块格式；两仓全量 `ruff check .` / `ruff format --check .` 通过。额外 math_env 回归 37 项通过。格式提交不代表新云部署。

## 改了什么

1. **实际采样证据**：复用官方 capture，记录 max_tokens、temperature、top_p、top_k、seed 和 stop；逐请求匹配原始 observation、action token IDs 与 action logprobs。默认 seed=None，不能宣称确定性配对。
2. **工具与 verifier 证据**：可选 observer 保存最后一次工具输出、grader stdout/stderr/exit code、reward 文件原文、执行时间及错误类型；不把测试内容加入模型上下文。
3. **多轨迹归属**：事件与 Store 都有 task_dir_sha256、traj_idx，事件另有 sandbox_id。task_dir_sha256 是路径身份，不是任务内容哈希；内容版本仍由 manifest 文件哈希核对。当前每个 phase 同一路径最多一个 group，未来重复 group 须增加 group 实例身份。
4. **原文校验**：按事件独立保存 body，校验字节数、SHA256、路径与存在性，读取 reward 后独立对照 trajectory reward/test_passed。目录与文件独占创建，历史产物不覆盖。
5. **输出边界**：单个 body 保存最多 128KiB，每个 journal 最多 1024 个事件；清楚记录本地截断和服务端未知状态。明确的 reward 截断、非有限值、缺文件仍拒绝。不能声称未知的服务端截断为完整。
6. **状态分离**：infrastructure_passed、evidence_passed、task_solved、score 分开。正常零分可以是有效实验；capture 退出失败也保留已经知道的任务分数。观察器写盘失败会阻止证据验收，但不改变原始奖励。
7. **终止与时间**：实际测量评估耗时；任一成功轨迹使组为 correct；无成功且全组预算终止才为 truncated；正常失败与预算终止混合组为 wrong。成功的 max_turns 仍单独显示终止原因，避免重复计数。
8. **正常模型错误**：框架在执行前拒绝未知工具或错误参数时，不要求并未发生的 sandbox 执行事件。真正执行的命令仍须对应 observer 证据。

## 使用与产物

既有 harbor_smoke evaluate 命令自动启用 schema_version=2，另建 `<output-stem>-evidence/task-000/`：
- `capture/sample.jsonl` 与 `capture_status.json`：官方采样请求和完整性。
- `harbor/events.jsonl` 与各 body 文件：工具、grader、reward 原文及哈希。
- `iteration_000000/evaluate*`：官方 Store、HTML、终态和 typed result。
训练入口在 record_training_artifacts=True 时，把同类事件保存到对应 iteration/phase 目录。

离线原始检查存于实现 worktree 的 `outputs/eval-evidence-local-20260915/`（ignored）：coverage.json、checks.json、完整 lint 输出和 bootstrap 报告。尚无本轮云验收报告。

## 下一次有效 OPD + RL 实验

当前共有 4 道原创工程题，train 2 / validation 2；不是正式 Terminal-Bench。
历史 P0 max_steps=1、groups_per_batch=1 只消费第一题 csv-paid-totals。直接重跑同配置仍可能再次 RL=0。

已新增并离线校验 `examples/harbor-opd-smoke/manifest-rl-candidate.json`，将 repair-interval-union 明确设为唯一训练候选，保留两道验证题。它仍可能太简单，不预设 Student 会失败或 Teacher 更强。现有云 P0 controller 仍固定原 manifest 与 group_size=2；新候选并未自动部署/启用。

下一阶段按顺序进行：
1. 基于已提交 wheel 构建新的 Linux 镜像，做不调用模型的 bootstrap，以及有界云环境复验。
2. 锁定候选、预算及重复次数，先筛查 Student 成败分布、Teacher 是否有可解释的成功轨迹。
3. 若 Student 全成功/全失败或 Teacher 无可观察优势，结束该候选；不自动补采直到凑出混合组，不加随机奖励。
4. 新训练用新鲜 rollout；独立重算同题回报→组均值→RL advantage→action mask，必须同时有真实 verifier 的0/1差异和非零RL；预算/上下文惩罚另报。
5. 核对 OPD 与 RL 分项、combined 公式、真实 optimizer 回执，再做同源参数变化与独立评估。训练数据上的奖励变高不替代独立验证集提升。

可考虑的首轮候选筛查为 Student 4 次、Teacher 2 次，另 nop/oracle 各1次，但这只是待核算的预算方案。按3轮×4096计算，6条轨迹生成上限73,728 tokens，仍需加输入token和Modal成本；不得将10美元充值当成实时余额或硬上限。后续group_size=4的一次更新需同步修改并审核controller预算，不能复用原2轨迹预算说明。

## 与历史 P0 的关系

历史云代码 b06728a 的真实更新、53,520,850个LoRA元素变化和独立reload证据保留；训练前2/2、后1/2、RL advantage=0仍为事实。本轮改动不追认旧产物缺失的字段。Qwen3.8-27B top-k服务实测、非零RL实训、正式Terminal-Bench、optimizer恢复及网页Control Panel仍待完成。

## 打包来源

wheel：`tinker_cookbook-0.5.8.dev30+g2ef293b6a-py3-none-any.whl`。
SHA256：`e2aeb838522851ae24684fd7d187694bf8c600fbebd5132c0fa1709b1fa8dd66`。
7个关键源文件与包内字节逐一一致；临时安装后导入和bootstrap通过，Tinker/Modal调用均为0。
包和安装目录位于/private/tmp，路径与机器可读结果保存在ignored outputs/eval-evidence-local-20260915/package.json；丢失时按上述代码提交重建。
