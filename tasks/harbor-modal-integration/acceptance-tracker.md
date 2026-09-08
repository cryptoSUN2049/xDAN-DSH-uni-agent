# 原生四能力验收与历史G1索引

2026-09-09：当前节点以active-engineering-goal.md中的N0—N5/P1为准，均待新验收；M1已通过证据保留。以下G1表为历史记录，Harbor不再前置。

权威目标：[active-engineering-goal.md](active-engineering-goal.md)。冷启动：[handoff.md](handoff.md)。本页是状态索引，不替代原始日志或放宽验收。

| 节点 | 完成标准 | 当前状态/证据 |
| --- | --- | --- |
| G1.0 固定环境 | 固定源码、SDK/runtime、模型、依赖；真实CUDA/SDK检查 | 已通过基础检查；deployment/versions/g1-deployment-lock.json |
| G1.1 原生诊断 | 真实请求、多context、奖励分布、少步更新及reload | 原生诊断已跑；历史零梯度，不算有效更新 |
| G1.2 M1 DSH在线RL | 真实token/trace/fresh receipt绑定；正确准入；有限非零梯度；LoRA数值变化、base冻结；独立reload及留出eval | 本课程工程验收通过；v2-r4两步更新及消费/数值审计通过，独立reload两条fresh评估通过，GPU释放。v1零更新，v2-r1/r2存储失败，r3启动前失败 |
| G1.3 M2 Harbor增量 | 固定任务/镜像；真实学生经Harbor环境→DSH→Gateway→评分→VERL更新；数值审计和独立reload | Docker脚本策略已通过；学生训练与v2完整接线未验收 |
| G1.4 可复建交付 | 干净checkout按精确版本复建；完整命令、证据、checkpoint身份、测试、commit/push与handoff | 未完成 |

## M1 当前实验验收

- [x] r4自然退出：supervisor exit_code=0，reason=training-exited；训练manifest completed。
- [x] 审计训练组真实消费、奖励方差；基础设施错误与可信0分区分，无未匹配消费。
- [x] loss/gradient有限，存在非零更新；不能用文件hash变化替代逐张量检查。
- [x] checkpoint逐张量有限、LoRA变化、base不变；optimizer状态有限且step/动量有真实更新证据。
- [x] 独立reload继承r4完整环境与v2数据配置，加载最终checkpoint；两条新留出session/receipt通过审计，无再次训练。
- [x] baseline/训练后/独立reload同预算比较并保存证据。当前两条public holdout满分不证明泛化提升。

运行：/root/runs/dsh-redact-m1-v2-r4。持久checkpoint：/workspace/uni-agent-g1/checkpoint/dsh-redact-m1-v2-r4/global_step_<step>。

审计入口：examples/dsh/ops/audit_qwen3_4b_online_rl.py；deployment/checks/checkpoint_delta.py；examples/dsh/ops/reload_qwen3_4b_checkpoint.sh。旧redact-m1-runbook.md路径属于v1，不可原样执行。step1→step2 delta只证明这一段变化；第二步不变不能单独推断整轮零更新。

## 后续目标

G2能力效果：DSH调度内化、跨会话记忆/上下文管理、受约束RSI/harness演化、长任务留出评估。G3性能：质量门通过后再优化并发、全异步与Modal等云端沙盒。两者不冒充G1已完成。全局方案以docs/harbor-modal-integration/uni-agent-system-plan-v3.html及native-capability-roadmap.md为准；v2与task-roadmap是历史入口。

基线/step1/step2/reload共8条公开留出结果均1，证据docs/harbor-modal-integration/redact-m1-v2-r4-eval-comparison.json。

## 原生四能力最新可核验节点

| 节点 | 已通过范围 | 仍未通过 |
| --- | --- | --- |
| DSH执行 | 既有M1真实RL+reload；grounding容量对照完整执行 | grounding/T2任务质量与独立效果增益 |
| 文件证据上下文 | v1四题真实执行/轨迹回读；v2 12train/4dev准备；r4四题strict准入；两步RL14组消费/数值审计、独立reload4组通过，仅首步非零任务梯度 | 实际仅消费2条训练题；严格准确率0，真实多context切换能力未通过 |
| 记忆边界 | 固定Linux SDK工具边界14请求；r3真实A→freeze→独立B整链审计通过，双方reward1/eligible，真实读取与来源保真 | 第二族事实更新待验收，无记忆RL；旧r2越权失败不追认 |
| RSI运行时 | 固定Linux父→子→回滚18真实工具请求，持久候选与选择合同 | 学生候选开发任务比较、训练与效果归因 |
| 数据 | 独立实例/重复采样/消费口径审计 | 四能力完整课程与封存评估交付 |
| 展示 | v3 HTML 390px无横向溢出、0坏锚点、状态视觉检查 | 视觉结果不替代上述训练验收 |

最近运行状态看handoff，不在此把“正在运行”写成通过。相关报告入口为docs/harbor-modal-integration/native-data-coverage-audit.md、context-v2-view-range-compatibility.md和memory-writer-prompt-v2-design.md。
