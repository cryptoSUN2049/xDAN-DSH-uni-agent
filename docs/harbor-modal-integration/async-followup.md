# 同步G1之后的异步验证

当前固定Uni-Agent/VERL已实现colocate_async与separate_async，无需新开发trainer。当前DSH/Harbor脚本trainer.v1.trainer_mode=sync；rollout.mode=async只说明生成服务，不能称整条训练全异步。

源码核查：verl/verl/trainer/ppo/v1/trainer_colocate_async.py使用FullyAsyncLLMServerClient，采样结束abort/sleep生成，更新后同步权重并resume；examples/quickstart/training/train_qwen3p5_dense.sh给出配套warmup配置。该quickstart模型与本项目不同，不照抄整份参数。

先完成Harbor同步学生RL数值与reload，再在独立run固定同任务/预算做单卡colocate_async。验收：暂停恢复不重复工具副作用、不将暂停当业务失败；会话/轨迹/奖励/策略版本绑定正确；未完成或过期组按规则处理；有限非零梯度、checkpoint及独立reload；与sync比较有效任务/分钟、token吞吐、墙钟、失败比例、显存峰值。无需为了占满显存先改训练模式。

separate_async留待独立采样与训练资源，另验证权重同步、staleness与样本淘汰。当前没有启动异步GPU实验；不改依赖pin、DSH或verifier，不将异步列为已验收能力。

## 用户补充确认的源码与模式边界

| 模式 | 行为 | 本项目验收状态 |
| --- | --- | --- |
| sync | 批次采样后更新 | M1已验收，Harbor M2进行中 |
| colocate_async | 任务异步推进、同GPU生成与训练交替，暂停/同步/恢复 | 上游已实现，本项目未真实验收 |
| separate_async | 独立采样与训练资源并行，周期同步权重 | 上游已实现，本项目未真实验收 |

参考固定源码：README.md的Fully Async/partial rollout声明；uni_agent/framework/entry.py提交rollout与TQ消费接口；verl/verl/trainer/ppo/v1/trainer_separate_async.py；replay_buffer.py中过期组控制；examples/dsh/train_qwen3_4b_online_rl.sh显式sync配置。行号可能随提交移动，以对应固定SHA源码为准。

训练权重同步与自动升级DSH源码不同；runtime/任务/verifier继续pin。异步实验独立验收任务超时、重复副作用、轨迹与reward/policy绑定、staleness、过期组比例、吞吐及效果，不能继承同步通过结论。

## 优先复用MemAgent脚本

examples/mem_agent/train_mem_agent.sh作为separate_async资源与trainer模板；当前DSH脚本作为任务/证据合同模板。保留TRAIN_BATCH_SIZE = PARAMETER_SYNC_STEP × PPO_MINI_BATCH_SIZE约束，默认4训练GPU+4rollout GPU不能直接用于当前单卡。HotpotQA/MemAgent Task须替换为DSH/Harbor数据和任务契约，不在DSH外增加执行循环。mini_swe_agent脚本有NPU配置，不能原样使用；不另走experimental/fully_async_policy入口。

## 当前授权

用户明确允许有机会在同步闭环通过后设置异步。允许现有单卡上有界colocate_async对照，无需重复询问；不授权新增GPU或中途修改当前同步run。开始前固定独立设计/参数和验收门，保留sync结果；不能原样运行4+4 separate_async配置。
