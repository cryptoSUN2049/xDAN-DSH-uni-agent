# Uni-Agent 原生任务选择：先诊断训练底座，再验收DSH

核查：2026-09-08，本地集成9b7dbdb，上游89733ec、VERL fefb080。本文基于固定源码审计，不是新训练结果。

| 入口 | 实际默认配置 | 本轮用途 |
| --- | --- | --- |
| examples/mem_agent/train_mem_agent.sh + hotpotqa | Qwen3-4B、FSDP2、separate_async；训练4GPU+采样4GPU；local sandbox；纯文本评分 | 原生训练底座诊断的首选候选，需要单卡同步适配 |
| examples/quickstart/training/train_qwen3p5_dense.sh | Qwen3.5-4B、Megatron、8节点×8GPU、长输出；默认Claude Code任务 | 不直接运行；模型/拓扑/外部Agent均增加变量 |
| examples/quickstart/training/task_config_react.yaml | SWE任务，vefaas sandbox、编辑器与shell | 后续工具任务对照，当前需替换并验证环境 |
| examples/mini_swe_agent/run_train.sh | Megatron异步、openyuanrong任务环境、预构建工具镜像与隧道 | 不作为单卡首跑 |
| examples/quickstart/harbor/task_config_oracle.yaml | Harbor oracle，默认modal | M2环境诊断；需改为经验证的Docker环境，oracle本身不是RL |
| examples/dsh/train_qwen3_4b_online_rl.sh | 本项目已有单卡sync GRPO/LoRA，DSH严格证据链 | 继续作为M1主验收，不能被原生任务替代 |

## 最短可行安排

- E0a（有界诊断）：优先复用HotpotQA Task、MemAgent和dataset adapter，固定少量训练/留出数据，将训练拓扑改为单卡sync，缩短上下文/分块与总步数。若适配成本超过一个短工作批次，停止扩展该支线，回到现有DSH单卡入口。
- E0b（M1）：相同模型与GPU依赖下切回DSH单卡任务；比较两条路径定位Gateway/VERL和DSH runtime问题。
- E0c（M2）：Harbor oracle→DSH bridge→评分/训练；独立记录，不能拿原生MemAgent成功替代。

单张卡不能仅把separate_async的GPU_IDS改为0：该recipe要求互斥trainer/rollout资源池。应复用数据/Agent/评分合同，单独采用已验证的单卡训练拓扑；不把MemAgent套到DSH外形成第二个执行循环。

## 真实合同差异

- HotpotQATask返回TaskResult.reward/accuracy/extra_info，但没有显式finished，也没有DSH verifier receipt。其原生recipe关闭mask_unfinished_episode；不能直接打开DSH严格准入后宣称兼容。
- 若加入finished判定，须来自实际终止行为并覆盖截断/失败测试，不能硬编码True。
- HotpotQA把答案奖励传给多个context链，适合检查多轨迹采样；这不是A会话写入→B独立会话检索的跨会话训练。
- 原生任务诊断单独标为native-smoke，不出具DSH严格合格报告。
- GRPO若所有样本奖励相同，可能没有有效学习信号；先检查真实奖励分布再扩大更新，不改造评分制造差异。
- 现成README的训练结果属于上游报告，不能计为本项目复现或承诺单卡同等效果。

## 执行前固定

模型/Tokenizer revision、任务数据revision与划分、上下文分块、采样预算、reward实现digest、训练模式与可训练参数；先eval，再少量update、张量数值对比和独立reload。尚未实现/运行E0a单卡适配。
