# M1：原生小数据训练与恢复入口

## 问题与实现

默认两行数据只够一个外层步，旧epoch=1导致请求10步的训练提前退出且不保存。新入口在Ray启动前使用配对VERL原生HFModelConfig和create_rl_dataset，按过滤后的行数计算steps_per_epoch，令epoch上限足够覆盖绝对目标步。最终保存仍由原生VERL负责，不修改子模块或创建新训练循环。

有效训练数据不足一个batch、验证集为空、非正步数/保存间隔会明确拒绝。随机subset且seed为空也拒绝，避免预检与训练选择不同数据；默认全量数据保持可用。

新增CLI：--total-training-steps、--save-freq、--resume-from-path、--preflight-only。print-config不读模型/数据，preflight-only读tokenizer/数据但不训练。实际启动记录training-preflight.json，再将有效epoch传给原生trainer。

恢复要求显式global_step_N、actor目录及data.pt，目标步必须大于恢复步；model/optimizer/extra与TQ状态交原生加载，不把入口通过说成GPU恢复通过。

## 变更文件

- examples/harbor_opd_rl/launch.py：原生数据预检、步数计划和显式恢复/预算。
- tests/uni_agent/examples/test_harbor_launch_preflight.py：真实本地tokenizer与native dataset过滤、CLI边界。
- tests/uni_agent/examples/test_harbor_training_preflight.py：真实PPOTrainer.fit控制流边界（模型/日志stub）。
- docs/verify-native-training-closure/training-recipes.md：本节点实际参数与验收边界。

## 验证与限制

先红后绿：入口测试最初6失败/2通过；最终123项相关回归通过，144.74秒，入口136/137行覆盖（99%）。真实过滤测试使用本地生成tokenizer/config及JSONL，无模型权重或外部模型调用。原生fit覆盖2/8/16/20行到达目标并最终保存，以及step5恢复到step10。详见cpu-validation.json。

独立review核对原生过滤、epoch推导、最后一步保存与恢复语义，无当前范围内剩余阻断。未运行GPU训练、未宣称有效更新/独立reload/能力提升。原实施会话的Modal/LoRA同步变更未被覆盖，本节点提交可独立集成。
