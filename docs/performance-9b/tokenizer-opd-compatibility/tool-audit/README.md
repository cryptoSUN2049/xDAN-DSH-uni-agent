# 工具输出 response mask 的 CPU 控制验收

本控制调用部署源码的 `ToolAgentLoop._handle_pending_state`、`_handle_generating_state`、`_handle_processing_tools_state`、`_call_tool`，以及真实 Hermes parser、QwenContinuousTokenBuilder 和 response metadata 对齐方法。没有手工替换生产 mask 方法；断言中的 0/1 列表仅是独立期望值。

唯一模拟的是 server_manager 返回的 assistant token（固定工具调用和最终答案）；工具执行是真实本地加法/受控异常，无付费沙箱、无 GPU、无外部服务。通过本控制不代表模型真实具备工具调用能力，也不验收教师工具轨迹评分。

五个控制：本地加法成功；本地函数抛异常；长工具结果的 left/right/middle 截断。每个控制均检查调用前 assistant span 为 1、工具上下文 span 为 0、后续 assistant span 为 1，工具上下文 logprob 占位为 0，长度与 token 串一致。特殊边界插入换行/assistant header 计入上下文 mask=0。

注意源码的 max_tool_response_length 截断按 Python 字符串长度（不是 tokenizer token 数），并额外附加截断提示；异常返回分支直接返回错误字符串，不经过成功分支的截断逻辑。当前异常控制未主张异常消息长度上限已覆盖。

## 运行

依赖现有 VERL uv 环境（torch、transformers、Ray、pydantic 等已有），仅加载 tokenizer 文件，不加载权重。使用部署源码目录，不另装不同版本。

```bash
source /workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/activate
export PYTHONPATH=/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/verl
export PYTHONNOUSERSITE=1
export CUDA_VISIBLE_DEVICES=""
python control.py --model /workspace/models/Qwen3.5-9B --output result.json
```

`result.json` 保存实际 response IDs、生产 mask、logprob 占位、各段边界、工具文本和被导入源码 SHA256。该证据仅覆盖单工具、文本、关闭 thinking、预算未耗尽的受控流程；不覆盖多工具并行、多模态、总 response budget 耗尽或真实自主工具 rollout。

## 合并样本的独立评分门禁

`validate_scores.py <目录>` 读取合并的 `samples.json`、`hf-replay.json`、`vllm-replay.json`，要求 8 条不同 live capture 行和 9 个指定模式，逐样本检查有限值、mean error < 0.1、P95 < 0.5。特别比较 **训练现场 live_teacher_logprobs 与 HF teacher@1**，而不是只比较两个事后评分器。保存 `score-acceptance.json`。现场 student/old 与 HF student@0.8 仅作诊断，需额外证明初始 base/LoRA B0 和尚未发生参数更新；不纳入通过门禁。

10 个合成正负控制已在本地运行：数值一致、超容差、NaN、空数组、长度错位，以及完整17行通过、现场教师数值破坏、缺模式、空mask、重复live身份拒绝。合成控制不属于真实模型结果。脚本不替代训练总microbatch覆盖审计、实际温度配置、权重与源码身份审计。
