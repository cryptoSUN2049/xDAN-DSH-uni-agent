# 真实 VERL 微批捕获与独立重算验收

状态：**本轮实际1步训练的 loss 边界、梯度、ID、mask及覆盖检查通过**。这份结论不替代后续独立 HF 教师评分验证。

## 权威运行

- run：`/workspace/verl-uni-agent-harbor-opd-rl/runs/opd-live-acceptance-20260924`
- 专用 uv Python：`envs/ua-verl-py312-vllm023-ws1/bin/python`
- 原生 actor WorkerDict PID1045333，安装marker与实际.pt均已保存。
- command.txt验证：batch8、n1、ppo_epochs1、total_training_steps1、warmup0。
- `exit-code.txt = 0`，step1模型checkpoint实际存在。
- 训练日志：distillation loss0.2211572900，grad_norm0.6953125，实际lr1e-6。

## 独立数值验收

| 实际微批 | 有效响应token | actual loss | CPU loss绝对误差 | raw梯度最大误差 | teacher-ID错位 |
|---|---:|---:|---:|---:|---:|
| 0001 | 2534 | 0.1493584961 | 0 | 0 | 0 |
| 0002 | 1921 | 0.0717987940 | 0 | 0 | 0 |

全部mask外梯度为0，loss/梯度/教师有效概率有限。两个微批全覆盖8行；worker调用1、2连续，未达到64捕获上限。真实data中的actor temperature均为0.8。教师temperature1仍由教师源码与实际启动配置证明，不从actor温度推断。

8条响应长度：152、612、746、1024、128、165、604、1024，总4455token。8/8原始prompt IDs精确映射冻结train集合（映射仅用于来源，不重编码替换捕获IDs）：instruction3、code2、math2、chat1。本批没有knowledge样本，不宣称五域全部实际捕获。

## 证据

- `evidence/capture/micro-1045333-0001.pt`、`0002.pt`：原始CPU TensorDict、teacher IDs/probs、old probs、model probs、原生loss及autograd.grad。
- `evidence/capture/replay-verdict.json`：逐微批独立重算。
- `evidence/capture/coverage-verdict.json`：真实exit、checkpoint、command、全8行覆盖。
- `evidence/capture/real-capture-samples.json`：完全保留真实IDs及历史teacher/student/old概率，用于后续HF/vLLM同IDs评分。
- `evidence/command.txt`、`evidence/exit-code.txt`：本地保留权威启动与退出。

## 范围与剩余项

捕获位置是distillation_loss内部实际返回边界，CPU verifier不导入VERL。验证了本轮原生k1 + vanilla PG数值及梯度；不是仅复述源码或重编码历史文本。合成fixture结果单独保留，未混入真实.pt。

尚需独立HF对同一组实际IDs重评分并与**历史live teacher probabilities**比较；仅新HF与新vLLM一致不足以证明原训练teacher评分。本轮依然为文本、单轮、thinking关闭。多轮、thinking及工具mask专项需独立证据；一次正确更新也不证明更大规模训练必然提高能力。

## 导出模块补充审计

CPU检查716个tensor、358组LoRA A/B：248个language_model文本模块的B全部非零；110个visual视觉模块的B全部为0。所有A/B有限，未发现文本未更新模块或无法归类模块。权重SHA为`4de54f78dc7f1fce19dab20debd295b95a545b1bea9da176665f3c748eb951bb`。完整模块名与形状见`evidence/capture/adapter-module-audit.json`。该证据限定本轮文本更新，视觉模块未训练不应被解释为多模态能力验收。

## 独立 HF 对真实历史教师评分补充

8条实际样本4455个响应token全部通过mean<0.1、P95<0.5的逐例门禁。token加权平均绝对误差0.00907492，最差样本平均误差0.02452252、最差样本P95误差0.10510792、最大单token误差0.24349523。全部概率有限。此处直接对比历史捕获的live teacher概率，不是仅比较两次新的评分。证据`evidence/capture/hf-vs-live-verdict.json`。多模式最终统一验收仍需17case vLLM及统一validate_scores结果。
