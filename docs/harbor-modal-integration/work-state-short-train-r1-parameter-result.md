# WS07短课程首轮参数与optimizer实测审计

## 结论

`ws-short-train-r1`已观察到真实参数更新。step2/4有有限非零任务梯度，step4/8的252个linear LoRA B均非零。step4→8的504个adapter张量全部变化，399个base张量逐元素不变；模型及optimizer数值检查通过。

**5–8步优势与梯度全为0，不能称这四步产生新任务学习。** 后半程参数变化与已积累的AdamW动量、weight decay相容。当前结果不证明能力提升，也不替代独立reload与实际消费审计。

## 身份与执行

- 固定源码：`b47521df1d6cd6b930ab6ac85ef41c670f2405d2`，远端checkout `/workspace/rebuild/uni-agent-work-state-short-r1`。
- 课程：`work-state-short-fact-v1`；训练run `/root/runs/ws-short-train-r1`。
- checkpoint：`/workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_4`及`global_step_8`。
- CPU审计时间：`2026-09-09T12:11:04.076596+00:00`，耗时98.638秒；线程OMP/MKL均2，`CUDA_VISIBLE_DEVICES=''`。模型/optimizer原文件只读，未启动GPU。
- 复用`deployment/checks/checkpoint_delta.py`与`optimizer_delta.py`串行执行，两者exit0；随后CPU `weights_only=True, mmap=True`只触LoRA B张量页。配置补证仅读取optimizer metadata，没有再次遍历moment或base张量。
- 完整远端脚本、argv、stdout、逐张量报告及JSON保留在 `/root/runs/ws-short-train-r1/final-audit-r1/`。本地[JSON报告](work-state-short-train-r1-parameter-result.json)包含远端原报告SHA、输入checkpoint SHA、各证据SHA及解释字段。

## 参数与优化器结果

| 指标 | step4 | step8 / 变化 |
|---|---:|---:|
| adapter张量 | 504 | 504个发生变化 |
| base张量 | 399 | 0个发生变化 |
| linear LoRA B非零张量 | 252/252 | 252/252 |
| LoRA B最大绝对值 | 0.000041961669921875 | 0.00008249282836914062 |
| optimizer内部step | 8 | 16 |
| active optimizer state | 504 | 504 |
| empty optimizer state | 37 | 37 |
| 非零moment张量 | 1008 | 1008 |
| 4→8发生变化的moment张量 | — | 504 |

模型张量及moment均finite。optimizer内部step不等于trainer global_step，8→16不能写成训练完成16步。

实际optimizer metadata：lr=1e-5、betas=(0.9,0.999)、eps=1e-8、weight_decay=0.01。resolved运行日志同时确认resume_mode=disable、lora_adapter_path=None、use_kl_loss=False、use_kl_in_reward=False、entropy_coeff=0。

## 任务梯度与历史动量的区别

| trainer step | grad_norm | advantage min / max |
|---|---:|---:|
| 1 | 0 | 0 / 0 |
| 2 | 0.14892578125 | -0.8660238981 / 0.8660238981 |
| 3 | 0 | 0 / 0 |
| 4 | 0.16845703125 | -1.4999970198 / 0.4999989867 |
| 5–8 | 各步均0 | 各步均0 / 0 |

学习率各步均1e-5。step2/4的pg_loss分别为-0.0201122891和-0.00850605965；其余均0。PG loss不为0不是必要验收条件，本次只是记录实际值。

`critic/rewards/min=0,max=1`在所有步骤都存在，但这混合了writer A0及reader B奖励，**不能据此推断同组B奖励有方差**；同组四个B奖励必须由原crosswalk与实际消费审计单独核实。

## 初始化与冻结base证据边界

实际PEFT源码SHA与此前已核定的0.19.1实现一致：config.py为`a9f95e1a143b8320cf2e0a3139f29c807d937876591f5fc1ce24fc4fd7833b59`，layer.py为`444bba0e5dbc5c55ed51a288a8366c18aa7ebe533d081312a19347eb48b215b6`。固定VERL fresh LoRA分支不覆盖默认`init_lora_weights=True`，linear B初始化为0。

因此，fresh无旧adapter/optimizer的运行配置、固定零B初始化源码、step4已非零B、早期有限非零任务梯度共同支持“本课程发生过梯度驱动参数更新”。零初始化B仅靠weight decay不能从0变为非0。此为源码与实测状态结合的推断，**不是实际保存过step0快照**；没有重建随机A冒充原始初始化。

base逐元素不变的数值证据仅覆盖step4→8，不扩展成已比较初始base→step8。非零B也不单独证明矩阵BA非零或能力提升；本轮未额外计算BA。

原旧课程r4零更新结论保持不变。独立reload/开发任务结果由主线程另行保存，本报告不提前宣告这些节点通过。
