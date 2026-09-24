# 27B → 9B OPD 完整测试结论

## 决策

当前本地 Qwen3.5-9B / Qwen3.8-27B 的文本 token 评分、真实原生 VERL loss/gradient、参数更新和导出重载通过。本轮不是“所有模式全绿”：单轮 thinking 在1024响应预算内没有闭合，严格模式门禁 exit1。不能以兼容性通过代替高性能验收。

统一入口：`../overnight/index.html`。机器结论：`full-acceptance.json`，保留各门禁与证据SHA。

## 实测结果

| 项目 | 结果 |
|---|---|
| 真实训练 | 1 step，warmup0，lr1e-6，train exit0；loss0.221157、grad_norm0.6953125 |
| 完整捕获 | 2 microbatch、8/8条、4455有效token；actor温度0.8 |
| 独立复算 | loss与梯度误差0，mask外梯度0，teacher ID错位0 |
| 现场teacher vs HF@1 | 8/8通过；加权mean0.00907492，最差样本mean0.02452252、P950.10510792 |
| 参数更新 | 248文本LoRA全部非零B；110视觉LoRA均零B，符合文本训练范围 |
| 导出重载 | 30/30固定验证、infra0；导出与独立eval SHA完全一致 |
| 17例模式/现场评分 | 6091响应token；HF/vLLM mean0.00825642、P950.06524849，逐例门禁和原生parser均通过 |
| 工具mask | 真实ToolAgentLoop/parser状态路径5/5控制通过，生成传输为mock |
| Thinking1024 | 单轮案例未闭合且截断，其他8案例未耗尽预算；原失败保留 |

权重SHA：`4de54f78dc7f1fce19dab20debd295b95a545b1bea9da176665f3c748eb951bb`。

本次样本领域实际为instruction3/code2/math2/chat1，没有knowledge样本。30题重载评分：math4/5、instruction5/8、knowledge1/1；code/chat未计正确率，不能称综合性能提升。

## 停止语义与边界

- 两份tokenizer的已测token坐标一致，不要求预训练数据相同。
- 使用学生渲染的raw IDs直接给教师评分，原生thinking模板不相同，不等于教师重新模板化评分。
- 实际teacher prompt评分温度1；student actor/rollout温度0.8；并非同温KL。
- HF矩阵模型默认EOS=248044 (`<|endoftext|>`)，VERL现场正常轨迹以248046 (`<|im_end|>`)结束。原eos_reached记录依据tokenizer导致8个短结束误标false，另存eos-audit纠正解释，原IDs不改。forced同ID评分可比，跨框架生成停止不等价。
- Thinking样本已反复计算出391，但不断修订简短答复，1024内未闭合；这属于行为预算失败，不是已证实token错位。
- 未认证：自主工具执行能力、多模态、超过4096上下文、广泛泛化收益、完整thinking质量。
- W&B为offline，未声称云同步或性能自动止损已经实现。

## 后续准入

关闭thinking的现有文本OPD链路可继续作为后续数据实验基础。开启thinking或扩长上下文，应建立独立的预算/停止配置版本与固定验证。扩大训练之前优先补合格数据、代码执行评分、聊天评分及封存测试，避免重复122样本冒充扩量。

## 2048预算单例诊断

独立追加测试在1751响应token闭合thinking，并回答391，最后以模型EOS248044结束。原1024个token逐ID完全复现，支持此案例是预算不足导致截断；不能外推所有thinking任务。新增尾部未另做教师评分。原1024门禁仍失败，未以更长预算替换历史结果。
