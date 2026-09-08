# Uni-Agent 本地能力审计（2026-09-08，只读）

审计根：`/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/harbor-modal-integration`。
HEAD db95b7a；已有 index.html / tasks/lessons.md 未提交变化，未触碰。未运行产品测试、训练或网络查询。本报告依据当前实际代码及随库文档，不声明上游最新状态。

## 核心判断

无需重新开发 Agent RL 底座：已有 DSH SDK adapter、Gateway、多 context / subagent token chains、VERL 训练、同步与全异步 recipe、MemAgent。真正缺的是将 DSH 的调度/记忆/上下文/Harness 动作纳入任务与学习合同、Harbor 环境桥、当前运行基线恢复和实测能力提升。

用户需要的 Harness RL 不应一概降级为“外部搜索以后再做”：模型在 DSH 中选择检查能力、组合/更新/回收能力、检索/写记忆、压缩/恢复上下文，本身可以成为策略动作，进入同一学生 rollout 与 RL。外部修改 Harness 源码并晋升版本则是另一个慢速演化闭环，两者分开定义与验收。

## 已实现与避免重复

| 能力 | 真实入口 | 边界 |
| --- | --- | --- |
| Agent/task/sandbox解耦 | uni_agent/agents/base.py:89；uni_agent/tasks/base.py；uni_agent/sandbox/base.py:233 | DSH应使用已有接口；不再创造平行执行框架 |
| DSH执行与语义事件 | uni_agent/agents/dsh/agent.py:34 / :266；runner.py:62 | 使用真实 deepseek_harness SDK、Gateway URL、session、事件hash；适配器不重新实现DSH内部调度 |
| 动态Harness启动工具 | examples/dsh/evolution.patch.yml | 注入cordis-host-runner与tool-cordis；是operator启动overlay，不等于已有自动持久自修改 |
| 外部/黑盒Agent训练 | uni_agent/framework/framework.py:297；agents/mini_swe_agent/agent.py；agents/claude_code/agent.py | Gateway收集真实模型token，框架评分并送TransferQueue；无需重新从语义trace伪造训练token |
| OpenAI/Anthropic协议适配 | uni_agent/gateway/gateway.py:163 / :189 | 模型调用统一通过会话Gateway；外部教师旁路必须明确是否可训练 |
| 多context/子Agent链 | uni_agent/gateway/session/session.py:78 / :717 / :822 | 支持多条chain、压缩后新chain、assistant rewrite rollback；不是自动记忆或自动压缩策略 |
| 模型输出mask/logprob/版本 | gateway/session/session.py:37 / :688 / :835 | 真实生成token、上下文token和权重版本区分；上下文重写必须保持此合同 |
| CPU回归示例 | tests/uni_agent/gateway/test_session_multiple_chains_on_cpu.py:222 / :255 | 明确测试子Agent系统提示分叉、context compaction新链；本轮未执行测试 |
| 严格DSH评分与谱系 | uni_agent/tasks/dsh/task.py:297 / :349 / :388；framework/task_runner.py | finished、verifier_reward、session/任务身份/hash已有；Harbor尚未映射完整合同 |
| Sandbox后端 | uni_agent/sandbox/{local,docker,modal,openyuanrong,vefaas}.py | Docker本地或云端皆可，Modal非必选；Harbor任务自己拥有环境不能重复包一层UniAgent sandbox |
| 训练/reload运维 | examples/dsh/train_qwen3_4b_online_rl.sh；examples/dsh/ops/* | 可复用历史底座，不能因新Harbor没跑就说旧链路从未跑过 |
| 全异步 | examples/mini_swe_agent/run_train.sh:32；examples/mem_agent/train_mem_agent.sh:121；examples/quickstart/training/train_qwen3p5_dense.sh:110 | separate_async/colocate_async已有；本项目DSH脚本:207仍sync，:248 rollout.mode=async不等于全异步 |
| Harbor任务评估 | uni_agent/tasks/harbor/task.py:54 / :67 / :99 | 明写evaluation-only；默认docker；绕过UniAgent Agent registry，dsh名称不能自动工作 |

## 与用户记忆/上下文目标高度相关：MemAgent已在本仓

- `uni_agent/agents/mem_agent/agent.py:108`：chunk上下文、显式context_session/update_context，跨context保留生成的memory。
- `:292–342`：对预切分chunks逐块生成memory，每次创建fresh context，最后用memory回答。
- `:90–94`：最终任务reward广播给每个context segment。
- `examples/mem_agent/README.md:1–20`：随库recipe报告Qwen3-4B，HotpotQA32K训练、8K–1M多长度评估，macro score53.5→58.0。**这是随库/上游报告，非当前DSH实验复现，也非Terminal-Bench提升**。
- `examples/mem_agent/train_mem_agent.sh:121`：separate_async GRPO；默认8 GPU（4trainer+4rollout），不能照抄成单5090资源承诺。
- 可以复用：多context轨迹、memory输出训练、训练启动、评估套路。
- 不能直接当成：DSH持久记忆、证据检索、scope隔离、何时压缩/保留哪些内容的自适应策略、跨任务经验晋升。现有MemAgent主体是固定chunk读取流程，决策时机由Python循环固定。
- 最短做法不是在DSH外再包一层MemAgent。让DSH拥有context生命周期，复用Uni-Agent Gateway对重建context的轨迹能力；迁移MemAgent的训练思想及测试/recipe参数结构。

## OPD明确代码阻断

`uni_agent/framework/entry.py:126–130` 在 teacher_client 非空时直接抛 NotImplementedError：
“AgentFrameworkRolloutAdapter does not support teacher_client yet; disable teacher policy/distillation or use an AgentLoopManager that supports it.”
因此当前DSH黑盒framework路径不能仅开VERL教师选项就运行OPD。
`framework/framework.py:200–201` 存在teacher_logprobs / teacher_ids字段名只说明tensor schema可容纳，不能据此声明teacher请求与token对齐已实现。
SFT可先离线构建经过真实执行验收的DSH轨迹；严格OPD需要单独设计教师状态、tokenizer/probability合同、loss及训练数据身份。

## 历史实跑的准确边界

`docs/dsh-adapter/project-status.md:126–137`：v2 Qwen3-4B，64rollouts、4optimizersteps，独立reload504LoRAkeys，8holdout均执行meanreward0.8125。完整组14/16=87.5%，variance9/16=56.25%，credible资格未通过；8/8是执行完成不是全成功；未证明相对原模型提升。本报告未确认5090型号。
当前handoff明确H0没跑、八类v3live未完成、Modal未部署；这些新增验收不能抹掉历史训练实跑。

## 针对4B DSH专长/RSI的最小缺口清单

1. 固定并恢复真实DSH SDK/runtime，重新确认当前修复版本的旧训练数据准入。
2. 统一policy action contract：DSH inspect/compose/update/cleanup，memory write/read/retrieve，context compact/pin/restore、子Agent调度等，具体只列真实runtime支持动作。
3. 三组任务并列：DSH专长任务、上下文记忆任务、独立terminal任务；不能仅用Terminal-Bench一个指标证明所有能力。
4. 同token/时长/工具预算比较：4B训练前/后、较大模型相同DSH Harness；证明“更懂DSH”须有可复现实验，不等于普遍超过大模型。
5. 短循环Harness策略RL：把学生可见状态→工具/Harness动作→真实后果→奖励接入现有Gateway+VERL。
6. 慢循环RSI：学生提出候选变更、沙盒试验、独立固定验证器、晋升/回滚与版本身份。当前仅catalog和部分执行器，未有可靠全自动能力提升证据。
7. Harbor桥只处理环境复用/DSH入口/Gateway网络/严格奖励映射；不要顺带重造训练器或沙盒调度系统。
8. 教师SFT、学生纠错数据、真正OPD分清里程碑；OPD当前有明确teacher_client阻断，单独验证。

## 提议的重新排序

保留既有训练底座→明确DSH/Harness与记忆动作和验收→恢复旧路径并真实跑v3→Harbor Docker DSH bridge→三类小规模训练/独立holdout→验证DSH专长及长程提升→再全异步/Modal规模化→受控慢速RSI。
H0是新增Harbor环境局部测试，不是重走整个训练项目。不要在做完外部Harness搜索之前一律禁止Harness策略RL，两者并无此先后依赖。
