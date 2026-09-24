# 模式兼容验收矩阵

## 本轮边界

`prepare.py` 提供 9 案例：单轮、含 reasoning_content 的历史、内嵌 think 历史、工具返回历史各含 thinking on/off，以及约 3000 token 长 prompt。全部固定学生模板，然后比较同一文本在教师 tokenizer 中的 ID 坐标；记录教师原生模板差异，不以模板必须相同为门禁。

- `prepare`：CPU，仅合成 continuation/EOS 坐标控制；不可称真实学生轨迹。
- `generate`：HF 9B 真实生成，直接保存 raw IDs（没有 decode→encode 重构），默认每例 256 response token。逐条记录 EOS、预算耗尽、thinking 闭合；未闭合时只能验收 thinking 前缀评分，不能宣称完整 thinking 完成。
- 工具历史为明确构造的合法消息和固定返回值。没有运行工具环境，不能证明工具选择、执行、返回注入或跨轮 response mask 正确。

输出 `samples.json` 与现有 `deep_replay.py` 的 hf/vllm/compare 输入兼容。CPU 控制和真实生成必须使用不同 `--out`，避免混淆证据。

## 门禁

1. 所有学生渲染文本在双方 tokenizer 中编码完全一致；原始 prompt ID 与生成前缀逐 ID 一致；总长度加教师评分额外一 token 不超过 4096。
2. 原生 VERL teacher prompt_logprobs parser 对每位置 token ID 一致，末尾 dummy 正确；响应首尾位置均检查。
3. 每案例 HF / vLLM 响应 logprob 均 finite，平均绝对误差 < 0.1、P95 < 0.5；按案例判定，不由短样本稀释长样本。错一位对照仅作敏感性佐证。
4. 使用真实样本概率执行现有独立 loss/gradient 验算：ratio=1 控制、有效 token 数、padding 零梯度和 clipping 语义一致。该门禁不能替代 live trainer 张量捕获。
5. 最终报告必须区分“评分坐标通过”“样本生成完成”“真实 agent 工具 mask 已验收”三件事。第三项在此脚本中始终未验收。

## 建议执行顺序（主线程协调 GPU）

先激活专用 uv 环境，在无 GPU 的进程运行 `prepare`，再安排空卡运行 `generate --max-new-tokens 256`；thinking 不闭合时保留该结果，并用独立目录将预算扩至 1024，不覆盖首轮。接着对真实生成目录运行 `deep_replay.py hf`、`vllm`、`compare`。既有 compare 输出 scope 文本写死“五域 replay”，因此汇总必须明确该实际输入是 9 个模式案例，不能原样沿用该 scope 作为结论。

长 prompt 本轮约 3000 token，总上下文最多 4096；不表示 32k/128k 长上下文兼容。真实多轮工具 rollout 的 mask、工具输出不参与 actor loss、thinking 部分实际可训练等需额外接入 trainer 张量审计。

## 实际执行结果（2026-09-24）

9 模式 + 8 条 live capture 的17案例均已生成和评分，独立 `validate_scores.py` 严格数量/来源/数值验收通过。响应教师评分平均绝对误差0.00825642、P95 0.06524849。原1024预算的完整模式门禁 **失败**：`single_thinking_true` 没有闭合，driver实际 exit=1，其余评分坐标/数值门禁通过。见 `evidence/mode-verdict.json`、`evidence/score-acceptance.json` 和 `evidence/run.log`。

实际发现停止语义差异：HF默认GenerationConfig EOS为248044 `<|endoftext|>`，tokenizer EOS为248046 `<|im_end|>`。HF矩阵8条在248044结束；live rollout6条在248046结束，另2条数学截断至1024。固定同IDs的teacher评分仍可比，但不能据此宣称HF/vLLM生成停止过程等价。原样本不覆写，独立 `evidence/eos-audit.json` 纠正解读，并保存原脚本 `evidence/prepare-original.py`。当前 `prepare.py` 已修正以后按实际模型GenerationConfig记录EOS。

随后独立2048预算诊断仅重跑该thinking案例，实际1751 token结束，</think>闭合，最终答案391正确；原1024前缀逐ID一致，说明该案例初次失败是预算不足。此诊断真实exit=0，证据在 `diagnostic-2048/`。它不改变原1024门禁，也未对新增长尾做HF/vLLM评分，因此不能作为2048整个响应评分已通过的证据。
