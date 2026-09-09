# r4独立reload：状态加载成功，四题评估未完成

run `/root/runs/work-state-train-r4-reload`，母checkpoint `/workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_8`。supervisor child258242，exit1，545.014秒。只读CPU审计原件，未改GPU、源码、回执或消费文件；[JSON摘要](work-state-train-r4-reload-result.json)含原文件SHA、逐文件checkpoint复核与完整失败调用摘要。

## 独立加载已证实

实际日志记录：

- 07:02:37.484 UTC：从母 `global_step_8` 恢复，global step设为8。
- 07:02:40.230：Loaded model，读取 `actor/model_world_size_1_rank_0.pt`。
- 07:02:40.309：Loaded optimizer，读取 `actor/optim_world_size_1_rank_0.pt`。
- 07:02:40.323：Loaded rng与Loaded lr_scheduler，均读取 `actor/extra_state_world_size_1_rank_0.pt`。

对照准备器保存的 `checkpoint_origin.files`，结束后逐一重算全部11份母checkpoint文件SHA和大小，全部一致，文件集合无新增/缺失。检查母文件真实字节，而非只比较清单自身。此reload无训练消费、无metrics落盘、无新checkpoint文件；没有参数更新证据。

## 确切失败与权限

原任务manifest确认失败的是 `work-state-ws06-v1-s303`，writer A，chain `memory-16d036b8c74946628dd01f6b734687e4`。回执fresh=true、finished=true、eligible=false；DSH记录completed，不据此推断backend隐藏结束原因。

1. seq9先view本chain只读 `writer-data/sources/request.json`。
2. seq14对该只读源做str_replace，虽old_str==new_str，仍属禁止的写操作；seq15明确WORK_STATE_POLICY_DENIED。
3. seq19对 `writer-data/memory/index.md` 做str_replace，seq20同样被policy拒绝。**该index路径在fixture.write_files白名单内**，不是未授权路径；当时目的文件尚未创建，str_replace不能替代create。
4. seq24改用create，同一路径在seq25成功创建。后续写其它memory文件及正常结束不能消除先前只读源写入违规。

因此确证的安全拒绝原因是尝试修改只读源。不得把此次失败追认为成功，也无需为了通过而放宽路径或安全规则。

## 评估消费边界

此前WS01/WS03/WS05各完成一条合法A/B链，A/B reward均0，各fresh/finished/eligible通过并提交TQ；WS06 A被拒，未进入B。

固定 `audit_memory_training` 新输出位于 `reload-audit-r1/memory-consumption-audit.json`：3groups、0 consumed_groups、0 consumed_rows；validation/rollouts均无JSONL落盘。unknown/duplicate/overlap/errors为空，但passed=false、consumption_verified=false、run_completed=false保持原值。已有crosswalk/submission不能代替trainer实际消费证明，未补造缺失dump。

本次可确认独立进程真实加载model/optimizer/RNG/scheduler、母checkpoint不变；不能确认完整四题新鲜评估闭环。后续显式筛选任务的独立运行必须有新run与清单，不能重写本次失败状态，也不能把筛选结果冒充原四题全部通过。
