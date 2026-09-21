# 全版本 checkpoint 评测交接

## TL;DR
- 用户要求每个版本 checkpoint 全量评测，取得整体结果。
- 本轮S2所有保留版本，加原版与S1 step12；GPU0全量队列持续运行。
- 已有完整结果：原版64.10%、OPD12 43.27%、RL20 50.96%、RL40 47.76%、RL60 46.15%；OPD12/RL20已补齐infra缺失。
- 新授权：TB2.1→SWE-bench Verified，固定原版/OPD12/RL60，GPU1。数据审计完成，正在验证沙箱/评分器。全量启动待核实既有Modal900美元上限；当前账单856.04美元。
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

## 2026-09-21 继续推进
- 13:46 UTC远端队列仍在运行，非全部完成。RL60 attempt2完整46.15%，差-17.95pp [-25,-10.90]；RL40 attempt1完整47.76%，差-16.35pp [-24.36,-8.65]。
- OPD12/RL20各两次后仍311/312，原队列标exhausted。固定以attempt2补缺，不能挑得分高的attempt。
- OPD12缺TL10836：tmux no server；RL20缺TL08999：verifier timeout300s。只补infra缺口，不改已有效0分；由eval_supplement.py新模块执行（实现中）。
- GPU0评OPD10，GPU1空闲可补缺；运行队列仍旧进程，不能声称新代码自动热更新。
- 新证据目录 docs/verl-uni-agent-harbor-opd-rl/checkpoint-full-eval/evidence-20260921/。
- 尚未得到全版本整体结果；用户明确要继续推进。

## 2026-09-21 补测部署
- eval_supplement.py 与 test_harbor_eval_supplement.py：9项补测测试+5项队列测试=14 passed，Ruff全仓双门通过。
- GPU1补测驱动：runs/run-supplements-20260921.sh；日志runs/supplements-20260921.log。固定OPD12/RL20 attempt2各补1，输出各自-label-supplemented-20260921目录，原attempt不动。
- 源全量队列status仍会显示这两项exhausted，不自动改写其他进程state；查询必须额外读取新目录validation.json、pair.json。
- 汇总时保留缺失当0的source_coverage_adjusted_framework_rate与补齐aggregate_framework_rate；历史infra事件不抹掉。
- 校验主要口径为framework resolved，behavior脚本raw reward solve_rate不同，不能混用。

## 2026-09-21 补测完成与跨集方案
- 补测驱动14:43:23 UTC exit=0。OPD12/RL20 aggregate validation均complete、errors=[]，每题4次无缺失。
- OPD12补齐43.27%，相对原版-20.83pp，95%区间[-28.53,-13.14]；RL20补齐50.96%，差-13.14pp，区间[-18.59,-7.37]。pair已存到checkpoint-full-eval/evidence-20260921/。
- 用户询问OPD+RL是否无效、能否评测其他软件benchmark。新文档docs/verl-uni-agent-harbor-opd-rl/cross-benchmark-proposal.md记录结论边界、TB2.1/Verified/EvalPlus可行性和三模型对照方案。
- TB2.1 parquet远端存在；Verified适配入口存在但未端到端验证。新benchmark尚未启动。不能将本次序列训练结果推广为所有OPD/RL无效；缺严格纯RL对照。

## 2026-09-21 新跨集评测授权与部署
- 用户明确要求完成TB2.1后SWE-bench Verified三模型同预算评测，原队列继续。范围/manifest/config/audit均在docs/verl-uni-agent-harbor-opd-rl/cross-benchmark/。
- Verified500题已下载。两套与实际S2训练500题的canonical ID/repo/题面哈希/词7-gram相似度检查无重叠；任务内容SHA已存，不能称语义污染完全排除。
- Verified500个verifier均采用FAIL_TO_PASS/PASS_TO_PASS及ResolvedStatus.FULL。远端nop/oracle控制驱动sid3495293，日志runs/cross-benchmark-20260921/verifier-controls.log。
- 新driver eval_benchmark_matrix.py，base/OPD12/RL60各固定3题探针后全量（TB n3、Verified n1）；--probe-only只验证不启动全量；base补缺已支持。新20测试通过；旧gate/matrix14通过；全仓Ruff lint/format通过。
- TB每题声明时间最多24600秒，Verified7800秒；配置外层分别25200/8400秒，sandbox25800/9000秒，同benchmark三模型一致。资源随任务，不压缩官方题目为满足旧3000秒。
- full计划2301条轨迹；已询问用户是否调高共享900美元上限。未获答复前不能默认扩额或启动整个full队列。小规模验证继续，GPU0旧矩阵不停止。
- 真实控制已完成：TB cancel-async-tasks、Verified astropy均nop0/oracle1；build-cython-ext oracle在planarity1.0.0/networkx3.6.1组合缺pos，作为已知参考解问题保留89题主结果，不能算模型失败证据。
- GPU1 TB三模型probe-only已发起，日志cross-benchmark-20260921/tb-model-probes.log，状态status-tb21-probe.json；不自动进入full。后续查真实加载/样本状态，不能把启动当成功。
- 新旧针对性回归合并34项通过，全仓Ruff519files通过；源码和manifest远端SHA与本地一致。全量仍未开始，预算答复待收。
