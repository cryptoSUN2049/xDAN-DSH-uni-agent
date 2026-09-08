# 4B DSH 专家策略与 Harness RL：能力审计后的路线

2026-09-08。当前 worktree 负责训练集成；本文是目标与复用决策，不是训练完成报告。

## 终局目标与可检验行为

4B 是首个目标模型，9B 为后续对照/扩展。固定 DSH 工具和运行合同，让模型熟练发现能力、组合工具、委派、处理失败、保留状态、检索记忆、管理上下文。RSI 不作为口号训练，而用“发现失败→提出隔离改进→测试→按证据采用或回滚→在新任务复用”行为验收。

Harness RL 是必要目标：把合法的 Harness 决策暴露为可学习动作，并依据后续任务结果训练学生策略。外部强模型搜索 Harness 可提供教师数据或对照，但不能代替学生自主能力证据。首版不要求模型修改 DSH 内核；先验证 profile/工具选择、上下文与记忆动作，再扩隔离插件候选。

## 已有资产与重复建设风险

| 资产 | 可复用内容 | 边界 |
|---|---|---|
| 本项目历史 RunPod RL | DSH→Gateway→VERL 的真实64 rollouts、4步更新、独立reload | 旧数据资格未全通过；不是新增Harbor或能力提升证据 |
| Uni-Agent Gateway / task runner | token真值、非追加上下文的轨迹处理、任务/Agent/环境接口 | 不等于学生已学会上下文管理；具体DSH变换仍需逐项验证 |
| examples/mem_agent/ | Qwen3-4B记忆训练recipe、多context轨迹、separate_async | 分块携带记忆并非DSH自主压缩/跨会话长期记忆；随库结果不是本项目复跑 |
| examples/mini_swe_agent/ | blackbox训练、separate_async接线 | 默认环境及模型配置不能直接视为DSH/Harbor配方 |
| HarborTask | CLI评估、环境provider接入 | DSH bridge与训练奖励合同仍缺增量；Modal可选，Docker先行 |
| ContextPilot能力SFT工作区 | 精确pre-assistant投影、过滤编译、跨会话数据和任务设计 | 文档记载5 attempts/10 Sessions/58 rows，仅两题一个family；人工审核及训练准入为0，SFT/RL未训练 |
| DSH m3数据工作区 | canonical-first、SFT渲染及独立split设计 | 文档记载5/20 accepted teacher trajectories，未独立复验；不能并入当前训练成果 |

## 明确缺口：OPD并未接通

uni_agent/framework/entry.py 的 AgentFrameworkRolloutAdapter 遇到 teacher_client 明确抛 NotImplementedError。存在teacher字段或VERL蒸馏功能不代表当前DSH路径能运行OPD。先设计学生状态、教师监督、token/分布对齐、loss、版本与预算合同；教师纠错SFT与严格OPD分开标记。

## ContextPilot采纳项

- 观测必须来自目标动作之前的真实request；动作后snapshot不得作为决策输入。
- 记忆训练使用Session A写入→冻结允许传递的产物→fresh Session B主动读取→任务结果评价A的记忆决策。不能将原始transcript或答案一并交给B。
- 优先终局质量与合法动作；压缩或节省token不能抵消丢失关键事实。
- 先任务级GRPO，再评估关键节点恢复/partial rollout/subtree credit；环境快照必须恢复文件、工具状态、记忆和预算，不能只复制prompt。
- ContextPilot的树分支partial rollout与全异步调度中的partial rollout不是同一个合同。
- SFT编译器的loss intent不等于真实token mask；SFT、online RL、OPD资格分别审计。

## 仓库分工补充（建议接线，不移动源码）

DSH-Exp生产运行事实和DSH能力；ContextPilot保留其专题数据编译器、任务与方法研究；Uni-Agent拥有训练集成入口、固定依赖和统一评估账本。ContextPilot自带train/verl参考实现不能直接替换本项目固定VERL。是否移植算法或调用版本化数据产物，需接口设计决定；不再维护第二套独立生产训练主线。

## 训练和评估路线

1. 复建历史DSH底座并完成新增正确性验证；Docker单任务验证Harbor增量，不重写Gateway或优化器。
2. 建立4B基线：DSH操作、错误恢复、上下文取舍、跨会话记忆、受控改进五类行为。大模型使用相同工具、信息和预算作为对照。
3. 按缺口复用教师SFT数据，canonical-first先按family/chain分割，再生成train-only输入；不继承旧27B/80+80配额。
4. 固定Harness动作接口，训练4B对工具、记忆和上下文的决策：先任务结果RL；教师辅助及OPD在适配后单独消融。
5. 增加候选生成、隔离测试、采用/回滚行为课程，验证新任务复用；候选不可改验收器或评估集。自动修改代码本身不算RSI通过。
6. 固定训练后模型，对独立终端任务和封存benchmark评估；报告成功率、失败类型、token/时间/教师成本、回归和不确定性。
7. 正确性通过后复用separate_async并扩并发；Docker可云端部署，Modal不是依赖前提。

## Terminal-Bench版本与验收

2026-09-08读取官方Hub：terminal-bench/terminal-bench显示rev.4 / 4.0.0 / v4.0.0，66任务，包含GPU及多容器任务。应将其记为该数据集的v4.0.0，固定registry digest与任务清单，不以动态latest作为可复现实验身份，也不与terminal-bench-2-1混用。

来源：https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest

初期CPU子集用于工程验证，必须标明子集成绩，不能称全套benchmark成绩。训练及开发集与最终封存评估分离；“比大模型更懂DSH”先限定在DSH专门任务上，并不承诺4B在全部通用终端任务超过大模型。

## 当前证据限制

本轮只读源码与HTML、查询官方Hub；未运行GPU、教师调用、MemAgent、ContextPilot训练或Harbor任务。ContextPilot源工作区有未提交文档，已记录所读文件hash，不能仅引用HEAD标识内容。新增接口/算法需单独设计测试；不把本路线当可直接执行的配置。
