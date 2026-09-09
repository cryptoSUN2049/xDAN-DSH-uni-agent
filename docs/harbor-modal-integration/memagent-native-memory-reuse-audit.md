# MemAgent 与 NativeMemory：固定源码复用审计

审计基线：本地集成 `c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0`，部署锁上游 Uni-Agent `89733ec81a69c3cc93ac90479de7ea7f01e51c1f`，实际 VERL `fefb080262e1c015a0ea05f958822a6a512dc795`。只读本地源码，不检索网络、不操作 GPU。`git diff 89733ec... -- uni_agent/agents/mem_agent examples/mem_agent/train_mem_agent.sh examples/mem_agent/dataset.py uni_agent/tasks/hotpotqa` 为空：下述原生实现与固定上游一致；`train_native_smoke.sh` 是本项目另加的单卡诊断入口。

## 结论

当前 resident memory RL **不是直接运行 MemAgent**。它复用 MemAgent 同样使用的 Uni-Agent Gateway、多 trajectory、Task runner 和 VERL GRPO 底座；额外实现 DSH A→B 两个独立 session 的可信编排、文件冻结与身份/评分/消费审计。这部分不等于重写 trainer，也没有再套一个 MemAgent 模型调用 loop。

原先“复用原生 4B recipe 和多 context 能力”的承诺目前仅部分兑现：原生 recipe 与单卡入口已在仓库，通用训练底座被实际复用；**原生 chunk→memory→fresh context 的多段策略尚未接入当前 DSH memory 任务**。两次独立会话验证的是持久记忆传递，不能代称完成长上下文分块、多 context 读写学习或 ContextPilot 集成。

## 原生代码到底做什么

| 层 | 固定源码证据 | 行为与边界 |
| --- | --- | --- |
| 4B 完整 recipe | [train_mem_agent.sh](../../examples/mem_agent/train_mem_agent.sh)、[README](../../examples/mem_agent/README.md) | HotpotQA 32K 训练，Qwen3-4B，FSDP2、GRPO、separate_async；默认训练 4 GPU＋rollout 4 GPU，n4，chunk 5000 token，mini-batch 32，parameter sync step 2，train batch 64。不能原样套单卡。README 的 53.5→58.0 是随库报告，非本 DSH 复现结果。 |
| 单卡诊断 | [train_native_smoke.sh](../../examples/mem_agent/train_native_smoke.sh)、[task_config_native_smoke.yaml](../../examples/mem_agent/task_config_native_smoke.yaml) | 本项目已有 sync/LoRA16、n4、2 step 的原生 mem_agent 入口；独立于 DSH。它仍有自己的数据、checkpoint 路径与验收范围，不应替换当前冻结 run。 |
| 数据与分块 | [dataset.py](../../examples/mem_agent/dataset.py):35、[preprocess.py](../../uni_agent/tasks/hotpotqa/preprocess.py):49 | tokenizer 编码后按 token 切块，放 metadata.chunks；模型训练样本仍是一个问题，而不是每 chunk 一个独立问题。 |
| 多 context 策略 | [agent.py](../../uni_agent/agents/mem_agent/agent.py):190、:292 | `update_context()` 用新 messages 替换当前模型上下文并收集上一段。`run()` 逐块输入“问题＋前一 memory＋当前 chunk”，模型生成新 memory；最后仅凭问题＋memory 回答。`max_chunks` 会限制处理段数，扩大长度评估时必须匹配配置，不能默认长输入全部被读。 |
| 原生执行 loop | [agent.py](../../uni_agent/agents/mem_agent/agent.py):127、:205 | 独立创建 OpenAICompatibleChatModel，`step()` 直接请求模型；这是 MemAgent 自己的策略循环。不是 DSH SDK runtime、DSH 工具调用或 DSH 文件隔离。 |
| 原生任务奖励 | [hotpotqa/task.py](../../uni_agent/tasks/hotpotqa/task.py):28 | 对最终 answer 评分，设置各 context 的结果 reward，返回 TaskResult.reward；不是每段生成一张 DSH verifier 回执。 |
| 共同训练底座 | [framework.py](../../uni_agent/framework/framework.py):1120、[VERL utils.py](../../verl/verl/trainer/ppo/v1/utils.py):148 | Gateway 采真实 token、保留所有 trajectory；固定 VERL 以每个 `{uid}_{sibling}` 最后输出算 GRPO 并广播。该实现属于通用底座，不是新写的 NativeMemory 优化器，也不应称 MemAgent 专属 GRPO。 |

## 当前 NativeMemory 复用了什么、为何仍需要新增代码

[NativeMemoryFramework](../../uni_agent/framework/memory_chain.py):309 的 `_stage()` 仍调用父 Gateway 的 `_execute_gateway_stage()`，复用真实 Ray Task、token/logprobs、session finalize 与 dump。`_write_prompt_trajectories_to_tq()` 核验跨阶段关系后调用父 TQ 写入；没有新增 trainer 或梯度算法。

[StageSpec](../../examples/dsh/capabilities/memory_training_stage.py) 创建两个独立 DSH Task。A 只能按白名单读源/写 memory，控制端冻结 A 实际产物；B 新 session 只读冻结 memory 与问题，不能继承 A 原对话。[memory_credit.py](../../examples/dsh/capabilities/memory_credit.py) 绑定 source、session、实际权重与 stage 原奖励，排序 A trajectories 后接 B trajectories。末 B 提供 GRPO 终态 credit，A 原 reward 不被篡改。这是原生 HotpotQA Task 未提供的安全与因果隔离合同，属于必要适配。

两者共享“终态任务表现指导此前记忆生成”的学习方向，奖励语义却不同。原生 HotpotQA 把同一个 answer reward 广播给 context；当前 DSH 保留 A、B 各自原回执，VERL 才用末 B 做链级 advantage。因此不能把原生 `ContextManagerResult.set_reward()` 生搬到 DSH 原始回执上。

明确限制：当前 `validate_stage_execution()` 要求 writer reward=1 后才能冻结/进入 B。故它只训练“正确 A 产物条件下的完整链”，不覆盖合法但有遗漏的 A 记忆导致 B 失败的学习样本。四个 B 同分时 GRPO 仍为零。这是首轮工程合同的范围，不是完整 MemAgent 学习能力。

原生 recipe 的 `custom_reward_function=score_from_runner_result` 也不能复制进 NativeMemory：后者明确拒绝 custom reward，实际 DSH verifier 奖励已绑定；VERL 注入句柄由 NativeMemory 隔离，防止第二评分路径覆盖或 fallback。

## 承诺核对与最短后续

1. **先完成当前已授权 resident 工程验收**：fresh A/B、真实 token/version、n4 消费与是否存在非零梯度分别记录；不因本审计另启 GPU 分支或改本 run。
2. **下一份版本化 DSH 课程补齐原生方法复用**：复用现有 token 分块 helper 与问题/记忆/新块的观测组织，增加至少两个实际 context 段及最终独立回答。由 DSH 自己的上下文能力完成消息切换与动作，保留 context ID、memory artifact lineage 与真实 Gateway trajectory；不能只在外部把长文本分文件就宣称 context switching。需要先审计固定 DSH 的可用上下文接口再设计实现，不在此臆造 API。
3. **从工程准入走向有效学习**：另行冻结 rubric，区分“安全合法但信息不足的 memory”与越权/伪造；前者才可作为有根据的低分学习样本，后者继续硬拒。不得放宽当前旧 rubric 或追认旧结果。增加独立实例与模板的 train/dev/封存评估后，再谈 DSH 记忆能力提高；仅 token 压缩率不是目标。
4. **原生 MemAgent 是可选对照，不是必须再造一轮主线**：若要量化方法差异，可用已有单卡入口做固定数据/预算对照；明确它不调用 DSH，不能作为 DSH 熟练度验收。现有 [原生诊断历史](native-v1-and-dsh-runtime-results.md) 已记录两个 step 同分、零梯度/零 LoRA 变化，不能被“脚本完成”覆盖。
5. **性能阶段再移植拓扑配置**：当前 sync 同版本合同先保留。separate_async/colocate_async 会改变真实版本跨度和准入条件，须独立设计，不能只把 `trainer_mode` 改成异步；Modal 也不是实现 MemAgent 分块或 A/B 持久记忆的必要前提。

审计未执行训练或 benchmark，未修改任何代码；源码存在与 CPU 合同不被写作新的 GPU 结果。
