# 数据结构筛选报告

状态：筛选产物已验收；尚未通过训练准入。

| 来源 | 输入 | 结构候选 | 隔离 | 排除 | 重复 |
|---|---:|---:|---:|---:|---:|
| greghavens/gpt-5.6-sol-coding-and-debugging-traces | 17939 | 16312 | 89 | 1538 | 0 |
| saidutta69/Qwen3.8-Agent-Premium | 11087 | 11048 | 25 | 14 | 0 |
| MoreThought/SuperiorThoughts-1 | 9640 | 8042 | 11 | 1587 | 0 |
| MoreThought/Fable-5.1-Max-Reasoning-Filtered-5000x | 5000 | 0 | 5000 | 0 | 0 |
| saidutta69/fable-5-premium-v2 | 85000 | 0 | 85000 | 0 | 0 |
| CodeFlame/Qwen3.8-GLM5.2-Kimi-K3-GPT5.6-Gemini-3.1-Claude-Fable5-Mythos5-distillation | 157939 | 26628 | 118109 | 7847 | 5355 |
| HelioAI/Claude-Fable-5-5500x | 5469 | 0 | 5469 | 0 | 0 |
| KrazyKitty/Fable-5.1-Max-Reasoning-Filtered-1000x | 1000 | 0 | 1000 | 0 | 0 |

## screened

关联任务组件：26757；选中组件：0。

领域分布：{"code": 13100, "reasoning": 9693, "general": 3964}

配额缺口：{"office": 3000, "data": 2500, "translation": 1500, "writing": 1500, "general": 1500}

## three_teacher

关联任务组件：26757；选中组件：0。

领域分布：{"code": 13100, "reasoning": 9693, "general": 3964}

配额缺口：{"office": 3000, "data": 2500, "translation": 1500, "writing": 1500, "general": 1500}

## 限制

- Source task IDs and exact prompts define components; semantic overlap not fully audited
- Publisher/row teacher claims are retained, not independently authenticated
- Correctness, tokenizer masks, template and supervised-token budgets still require validation
- Cyrillic language heuristic quarantines for review; not a full Russian language classifier
