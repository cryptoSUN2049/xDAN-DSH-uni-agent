# 同步G1之后的异步验证

当前固定Uni-Agent/VERL已实现colocate_async与separate_async，无需新开发trainer。当前DSH/Harbor脚本trainer.v1.trainer_mode=sync；rollout.mode=async只说明生成服务，不能称整条训练全异步。

源码核查：verl/verl/trainer/ppo/v1/trainer_colocate_async.py使用FullyAsyncLLMServerClient，采样结束abort/sleep生成，更新后同步权重并resume；examples/quickstart/training/train_qwen3p5_dense.sh给出配套warmup配置。该quickstart模型与本项目不同，不照抄整份参数。

先完成Harbor同步学生RL数值与reload，再在独立run固定同任务/预算做单卡colocate_async。验收：暂停恢复不重复工具副作用、不将暂停当业务失败；会话/轨迹/奖励/策略版本绑定正确；未完成或过期组按规则处理；有限非零梯度、checkpoint及独立reload；与sync比较有效任务/分钟、token吞吐、墙钟、失败比例、显存峰值。无需为了占满显存先改训练模式。

separate_async留待独立采样与训练资源，另验证权重同步、staleness与样本淘汰。当前没有启动异步GPU实验；不改依赖pin、DSH或verifier，不将异步列为已验收能力。
