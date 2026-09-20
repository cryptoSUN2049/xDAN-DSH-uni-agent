# 全版本 checkpoint 评测交接

## TL;DR
- 用户要求每个版本 checkpoint 全量评测，取得整体结果。
- 本轮默认 S2 所有保留版本，加原版与 S1 step12；是否包括 r1–r11 已异步询问。
- 用户已批准继续。评测校验和队列已实现并部署；GPU0单题探针运行，队列等待probe验证收据，尚无新全量结果。
- 先读 `docs/verl-uni-agent-harbor-opd-rl/checkpoint-full-eval-design.md`；旧训练历史在该 docs 目录的 `tasks/handoff.md`。

## 本轮交付物
- `docs/verl-uni-agent-harbor-opd-rl/checkpoint-full-eval-design.md`：候选清单、流程图、接口、费用、验证与拟改文件。
- 本文件：当前任务冷启动入口；文件行数可用 `wc -l` 复核。

## 设计约束
- 不把0题/exit0当成功；78题每题4条才是完整结果。
- 不合并bf16 LoRA；保持模型、数据、采样、评分口径可追溯。
- 不杀其他会话进程；训练结束的全局Ray清理完成后才开批量评测。
- 非平凡代码改动遵守用户提供的 AGENTS Human Gate，设计批准后实施。

## 已发现真实行为
- 原版与 OPD12 的相同0.6显存配置曾成功；失败step20初始化前额外占用约14.38GiB，checkpoint尚未加载。
- 静态路由检查未发现错卡，历史没有物理GPU UUID/占用PID证据；不能推断占用者。
- eval_val_only.sh 吞掉底层异常，0题结果仍退出0。
- S2保留 OPD10/11/12，RL20/40/58/59/60；58模型文件偏小，未证明完整。

## 下一里程碑
- [x] 清点保留文件、pinned去重与只读故障分析。
- [x] 设计落盘。
- [ ] 用户批准设计与范围。
- [ ] checkpoint完整性检查、显存/路由诊断与首题真实验证。
- [ ] 修复失败传播；实现可恢复队列与回归测试。
- [ ] 逐版本78×4，配对与行为统计，完整总报告。

## 分支/部署状态
- 分支 verl-uni-agent-harbor-opd-rl，清点前 HEAD fa2653a，工作区当时干净。
- pod SSH：root@157.157.221.177:11965，密钥 ~/.ssh/id_ed25519。
- 2026-09-20 12:37 UTC：第60步checkpoint已保存，最终验证4/8任务完成，GPU0工作，GPU1空闲。不能当当前实时状态。
- 本任务未部署代码、未启动新批次、未跑新CI；已写设计不等于已完成实现。

## 冷启动 checklist
1. 读设计与本交接，查看用户是否批准及范围答复。
2. 查git状态，保留所有已有改动。
3. 查训练收尾、GPU UUID/进程占用和Tinker排期、Modal额度。
4. 核查全部候选checkpoint文件，处理58异常。
5. 按批准设计完成首题真实验证，再运行全量队列。

## 2026-09-20 执行更新
- 训练12:53 UTC PASSED，最终60步保存；delta失败原因是损坏的step58，supervisor已完成退出。
- 新文件 eval_result_check.py：精确parquet任务身份、每题样本数、checkpoint加载证明、底层退出码；validation.json complete才通过。
- 新文件 eval_checkpoint_matrix.py：manifest哈希、数据/基线哈希、进程锁、GPU空闲检查、每版本独立目录、有限重试、0样本停止、配对/行为汇总。
- manifest：docs/verl-uni-agent-harbor-opd-rl/checkpoint-full-eval/manifest.json；服务器 runs/full-matrix-manifest-20260920.json。
- Probe：runs/matrix-probe60，脱机sid2663882，GPU0，step60，1题1次，原推理配置0.6/36864，model-only加载；14:20 UTC开始。
- Queue：runs/full-matrix-20260920-launch.log，gate.json/state在runs/full-matrix-20260920；初次等待进程已停止并更新竞态保护后重挂。
- step58 archive损坏已确认；保留证据，标记unavailable。
- 测试：14项新功能测试通过，Ruff全仓双门通过；更广回归卡在本地pandas/parquet子进程，已终止，不能宣称全套通过。
- 本地改动尚未commit/push；服务器已单文件部署，后续必须核对身份再交付。
- 下一次先检查probe validation.json：只有complete才让全量开跑；失败时队列会停，不反复空跑。

- 15:20 UTC复核：probe于14:55:35 UTC完整通过，1题1样本，得分0；第60步成功加载。队列重新启动sid2686667，首版本step60全量；仍需检查status.json实际running。
