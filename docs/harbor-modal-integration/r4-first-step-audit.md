# r4首步：真实n4链消费已核，学习信号仍为零

单次只读CPU审计的时间、完整源码SHA与原证据哈希见 [JSON摘要](r4-first-step-audit.json)。源码固定`5b4b01b`，远端 `/workspace/rebuild/uni-agent-work-state-r4`；run `/root/runs/work-state-train-r4`。未改运行源码、旧回执或GPU状态。

## 首步已核事实

- 任务只有一个：`work-state-ws01-v0-s101`；组UID `a89c1881-f30c-4080-8106-57797eca9408`，四个真实sibling、四条独立A/B链。
- `rollouts/1.jsonl` 实际记录8个唯一TQ keys，分别为sibling0–3的A后B；step=1，采样policy version=0。原crosswalk仅声明提交，本次固定 `audit_memory_training` 联合实际trainer消费文件后确认首组 `consumption_verified=true`。
- 原NPZ、stage回执、任务fixture、原trace/result谱系独立核验通过。八stage均fresh/finished/eligible；stage奖励与消费score逐项一致。missing/duplicate/score mismatch均为空，未改A或B奖励。
- 四个终态B奖励均0；step1 `actor/pg_loss`、`actor/loss`、`actor/grad_norm`和advantage范围均0。首步证实采样→完整组消费链路，不构成新增任务学习。

## 进行中快照边界

审计期间训练继续进行；单次全局快照已看到2个完整消费组、16条唯一消费行，unknown/unadmitted/duplicate/overlap/errors均为空。整体 `consumption_verified=true` 仅针对当时已有的groups；`run_completed=false`、`passed=false` 保留原值，不改为完整训练通过。

远端新输出位于 `/root/runs/work-state-train-r4/interim-r1/memory-consumption-audit.json` 与 `first-step-summary.json`，未重复覆盖历史审计。本报告只详细验收首步，未验收全部8步、checkpoint、optimizer或独立reload。metrics文件会增长，JSON记录的是采集时观察字节的SHA，未来整文件SHA变化不等于篡改。
