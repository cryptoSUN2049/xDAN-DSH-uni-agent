# 项目记忆
2026-09-15
- 用户优先 Tinker 官方资源/服务/代码，Harbor 管任务，Modal 管 sandbox。
- 主线 Teacher Qwen3.8-27B / Student Qwen3.5-9B，账户可用性须实测。
- 暂停 Modal 2.4T strict scoring；不能断言 Modal 平台不能部署或不能 scoring。
  已观察 chat logprobs 和若干 scoring 路由 404；不是所有 API 的穷举验证。
- 旧 Docker Hub 文本粘连了 0 B：基础版本应读作 SGLang 0.5.16、
  CUDA 13.0.1、SGL-Kernel 0.4.5；后续 COPY 源码可能覆盖基础版本。
- Teacher fixed-sequence logprobs 足以构造 sampled reverse-KL；不需要全词表 logits，
  不需要 Teacher 自己 rollout。token 数量相等不足以证明 tokenizer 兼容。
- 指令版 9B 优先验证工具任务；Base 属于另一个初始化实验。
- 最终 Terminal-Bench 测试题不用于训练；训练用独立 Harbor 格式任务。
- 目标超越 Opus 4.6 尚无证据。训练更新、reload、holdout 提升分别验收。
- 设计 docs/tinker-harbor-opd-rl/design.md；实施 ../tinker-cookbook-opd-rl。
- 不能根据旧截图推断当前凭据/Endpoint 状态，不保存 API key。
