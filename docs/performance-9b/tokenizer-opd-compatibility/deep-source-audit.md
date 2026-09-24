# OPD 深层源码审计：k1、PG 与 teacher token 对齐

日期：2026-09-24。范围：本地实际 VERL 源码及 overnight/train.sh；只读源码分析，未修改 VERL、未运行 GPU。本文件不替代真实批次、实际函数数值测试或长轨迹重放验收。

## 源码身份

本地 `shasum -a 256` 实测如下，与主线程提供的远端哈希逐项一致。此处未独立连接服务器重新获取哈希。

| 文件（仓库根目录相对路径） | SHA256 |
|---|---|
| `verl/verl/trainer/distillation/losses.py` | `8fc5835f410228c110f492a10dddfe6ce3274efd22f439dfaf8c88c5d5a6d843` |
| `verl/verl/workers/config/distillation.py` | `c91c4f6bf68f57431d5f71828afbe13ebfe4f5dfa0bd27ee4b61750da183b719` |
| `verl/verl/trainer/ppo/core_algos.py` | `a54b6d812db4441e8b0989ae69d2c46b0a0a7b584296f73d8316f264462c37cb` |

以下行号针对本次本地快照。

## 实际目标与梯度

本次使用 `k1 + use_policy_gradient=True + use_task_rewards=False`。记学生当前 token 分布为 q、教师为 p：

```text
d = log(q) - log(p)
A = -stop_gradient(clamp(d, -10, 10))
r = exp(clamp(log(q_current) - log(q_old), -20, 20))
L1 = -A * r
L2 = -A * clamp(r, 0.8, 1.2)
Lclip = max(L1, L2)
Ltoken = where(A < 0, min(-3*A, Lclip), Lclip)
L = masked_sum(Ltoken) / global_batch_num_tokens * dp_size
```

若实际 batch 存在 rollout importance weights，还会在归一化前乘该权重；必须由批次证据确认，不能仅凭公式假设不存在。

- `losses.py:389–400`：展开学生和教师 logprob，核对 shape，调用 k1。
- `core_algos.py:2228–2229`：k1 是 student logprob 减 teacher logprob。
- `losses.py:258–260`：差值截断到 ±10。
- `losses.py:283`：负差值 **detach 后**作为 advantage；teacher 信号由此进入 policy gradient。
- `core_algos.py:1336–1368`：log-ratio 稳定截断、PPO ratio clipping、负 advantage dual clip、可选 importance weights、最终聚合。
- `core_algos.py:1170–1175`：token mean 使用全局有效 token 数归一化，并乘 dp_size。
- `losses.py:216–224`：任务奖励 policy loss 被置零，distillation coefficient 在此模式强制为 1。
- `overnight/train.sh:53–54`：额外 KL loss 关闭、entropy coefficient=0、聚合为 token-mean。

符号符合“提高教师相对更偏好的学生采样 token，压低教师相对不偏好的 token”的 PG 更新。不能直接对 k1 反传：那样 teacher 不参与梯度；`workers/config/distillation.py:120–124`明确拒绝这一配置。

这属于局部 surrogate 的正确性检查。有限采样、状态分布、clamp、PPO clipping，以及可能的 top-p/top-k 截断会影响与完整 reverse-KL 期望梯度的对应；不能称为完整无偏 KL 梯度。

## 重点发现一：温度不对称

当前重算应使用：

```text
q = softmax(student_logits / 0.8)
p = softmax(teacher_logits)
```

- `overnight/train.sh:60`：student rollout temperature=0.8。
- `trainer/ppo/ray_trainer.py:1331,1479`：把 rollout temperature 写入 batch。
- `workers/engine/fsdp/transformer_impl.py:1474–1482`：当前 padded FSDP 路径用该温度缩放学生 logits。
- `experimental/teacher_loop/teacher_manager.py:40–55`：teacher prompt_logprobs 是原始前向概率；参数 temperature 固定为 1。

这不是 token 坐标不兼容，而是实际目标分布的设定。独立验算若把学生也按 T=1 计算，会得到错误的不一致结论。还应核对 rollout 采样过滤与训练概率的关系。

## 重点发现二：k1 未使用 log_prob_min_clamp

`overnight/train.sh:92` 设置 `log_prob_min_clamp=-10.0`，但 `losses.py` 的 k1 路径没有读取这个字段。实际有效的是 `loss_max_clamp=10.0` 对 **logprob 差值**做截断。

因此不能把本轮实现描述成“学生、教师 logprob 各自下限 -10”，也不能在独立重算时自行加上这一操作。该字段的存在不代表它在所有 loss 模式生效。

## Teacher token 对齐路径

1. `experimental/agent_loop/agent_loop.py:1017–1018`：直接发送学生 `prompt_ids + response_ids`。
2. `experimental/teacher_loop/teacher_manager.py:128–141`：将 raw IDs 传入 teacher，不重新渲染 teacher chat template；返回 teacher IDs/logprobs，检查长度。
3. `workers/rollout/vllm_rollout/utils.py:534–557`：跳过第一个 token 的 None logprob，末尾补 dummy。teacher 对位置 i+1 的 token 评分存放在位置 i。
4. `teacher_manager.py:60–75`：按学生 prompt 左 padding、response 右 padding。
5. `workers/utils/padding.py:137–138`：response 截取 `[P-1:P+R-1]`，与 student next-token prediction 位置一致，末尾 dummy 不进入 response loss。
6. `agent_loop.py:749`：response mask 乘 response attention mask，排除 padding。
7. `losses.py:283–285`：最终 PG 计算使用 response mask。

在这些前提成立时，源码坐标逻辑是相容的，没有观察到必然的一位错位。但它仍需实际 token 数组验算。

## 重点发现三：teacher_ids 缺少内容断言

teacher manager 只 assert 返回长度；k1 分支只 assert student/teacher/mask 的 shape，**没有逐元素检查 teacher_ids 对应学生目标 token**。k1 的损失只使用 teacher_logprobs。

所以相同长度并不充分。实际验收必须比较有效 response 上的 teacher_ids 与 shifted student input_ids，并覆盖首 response、EOS、截断尾 token、混合长度 padding；还应设置故意错移一位的负对照，确认能拒绝错配。

## 尚未由此文证明的验收项

- [ ] 实际 VERL 函数的 CPU 数值/梯度对照，包括正负 advantage、±10 截断、PPO clip、dual clip、mask、全局归一化。
- [ ] 实际学生长轨迹上 teacher HF/vLLM 同 token、同位置评分对照。
- [ ] 真实训练 batch 的 old/new logprob、teacher logprob、mask、temperature 与 loss 一致性；若无保存张量，应明确是重放而不是恢复历史批次。
- [ ] EOS、截断、不同长度 padding 的逐 token 边界检查。
- [ ] thinking、多轮、工具输出 mask 的独立验收；今晚关闭 thinking 的结果不能覆盖这些模式。
- [ ] 教师在学生模板下是否有稳定领域优势。模板条件下的教学质量属于效果问题，与数值/坐标兼容分别验收。

结论：源码支持当前配置的有限工程兼容性，未发现必然错误符号或必然错位；**完全兼容、历史每个训练 token 均正确及稳定能力收益，均不能由本次只读审计推导**。
