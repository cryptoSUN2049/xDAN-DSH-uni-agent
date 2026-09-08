# G1 验收追踪索引

权威目标：[active-engineering-goal.md](active-engineering-goal.md)第4节。冷启动：[handoff.md](handoff.md)。本页是状态索引，不替代原始日志或放宽验收。

| 节点 | 完成标准 | 当前状态/证据 |
| --- | --- | --- |
| G1.0 固定环境 | 固定源码、SDK/runtime、模型、依赖；真实CUDA/SDK检查 | 已通过基础检查；deployment/versions/g1-deployment-lock.json |
| G1.1 原生诊断 | 真实请求、多context、奖励分布、少步更新及reload | 原生诊断已跑；历史零梯度，不算有效更新 |
| G1.2 M1 DSH在线RL | 真实token/trace/fresh receipt绑定；正确准入；有限非零梯度；LoRA数值变化、base冻结；独立reload及留出eval | 未完成；v2-r4两步更新及消费/数值审计通过，独立reload进行中。v1零更新，v2-r1/r2存储失败，r3启动前失败 |
| G1.3 M2 Harbor增量 | 固定任务/镜像；真实学生经Harbor环境→DSH→Gateway→评分→VERL更新；数值审计和独立reload | Docker脚本策略已通过；学生训练与v2完整接线未验收 |
| G1.4 可复建交付 | 干净checkout按精确版本复建；完整命令、证据、checkpoint身份、测试、commit/push与handoff | 未完成 |

## M1 当前实验验收

- [x] r4自然退出：supervisor exit_code=0，reason=training-exited；训练manifest completed。
- [x] 审计训练组真实消费、奖励方差；基础设施错误与可信0分区分，无未匹配消费。
- [x] loss/gradient有限，存在非零更新；不能用文件hash变化替代逐张量检查。
- [x] checkpoint逐张量有限、LoRA变化、base不变；optimizer状态有限且step/动量有真实更新证据。
- [ ] 独立reload继承r4完整环境与v2数据配置，加载最终checkpoint；两条新留出session/receipt通过审计，无再次训练。
- [ ] baseline/训练后/独立reload同预算比较并保存证据。当前两条public holdout满分不证明泛化提升。

运行：/root/runs/dsh-redact-m1-v2-r4。持久checkpoint：/workspace/uni-agent-g1/checkpoint/dsh-redact-m1-v2-r4/global_step_<step>。

审计入口：examples/dsh/ops/audit_qwen3_4b_online_rl.py；deployment/checks/checkpoint_delta.py；examples/dsh/ops/reload_qwen3_4b_checkpoint.sh。旧redact-m1-runbook.md路径属于v1，不可原样执行。step1→step2 delta只证明这一段变化；第二步不变不能单独推断整轮零更新。

## 后续目标

G2能力效果：DSH调度内化、跨会话记忆/上下文管理、受约束RSI/harness演化、长任务留出评估。G3性能：质量门通过后再优化并发、全异步与Modal等云端沙盒。两者不冒充G1已完成。全局方案见docs/harbor-modal-integration/uni-agent-system-plan-v2.html和task-roadmap.html。
