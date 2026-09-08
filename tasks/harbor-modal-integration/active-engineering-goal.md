# 第一阶段工程 Goal

2026-09-08 用户要求激活。平台仍保留旧blocked Goal，create_goal拒绝新建，不能将旧目标标记完成来绕过；需用户在Goal界面恢复或调整旧目标。以下为当前执行范围，不表示平台已激活。

## 版本基线

- 本项目集成源码：9b7dbdb78cb5f0bb0f28e90515050ea5d476d8cf（已推送）。
- 上游Uni-Agent：89733ec81a69c3cc93ac90479de7ea7f01e51c1f。
- 配对VERL：fefb080262e1c015a0ea05f958822a6a512dc795。
- 后续修复产生新集成commit时，更新候选部署清单；每次run固定完整commit，运行期间不pull漂移。

## 完成标准

- [ ] 固定并验证Python/GPU依赖、DSH runtime、模型/tokenizer、任务/Harness/verifier和训练配置。
- [ ] GitHub拉取的独立checkout可以重复安装与运行，预检明确报告缺失项。
- [ ] M1：真实DSH→Gateway/Uni-Agent→VERL；可信有效rollout进入优化器；有限loss/gradient，可训练张量数值变化。
- [ ] 独立进程reload指定checkpoint；同预算训练前后留出eval和失败分析。
- [ ] M2：固定Harbor单任务oracle→DSH bridge→新鲜评分/轨迹准入→训练更新/reload；不把M1成果计为M2通过。
- [ ] 保存运行身份、原始证据、安装锁与验收报告；文档交接更新，检查后commit/push。

范围：使用用户现有RTX PRO 6000；不创建额外付费资源。本轮不要求显著能力提分，DSH专长/记忆/RSI效果和全异步/Modal规模优化继续按后续里程碑。
