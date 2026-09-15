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

## 2026-09-15：系统方案 HTML
- 主入口 docs/tinker-harbor-opd-rl/system-plan.html，覆盖目标/架构/流程/算法/SDK契约/数据/阶段/启动/云运行/缺口。
- 单文件离线HTML；浏览器桌面/手机与三模式交互、打印展开、内部链接检查通过。
- 目标防护与已实现能力严格区分：每批Teacher评分finite/None/全零mask拒绝尚待补实现。
- Context7旧自动文档有compute_logprobs返回类型冲突；按SDK0.29.0及官方API实际列表返回契约。
- 用户本轮提供Tinker key，已仅注入评分探针子进程；未写入任何项目文件。最终停在 capabilities：SDK 与直接只读路由均 HTTP 402（billing blocked）；已停止等待进程，无采样/评分/训练发生。

- 最新阻塞已从“没有提供key”更新为“提供key后真实服务返回HTTP 402计费限制”；凭据未持久化，下次仍需安全注入。
- 402不能解读为模型不支持；SDK0.29.0会暂停等待计费恢复，表象可能类似卡住。

## 充值后复测
用户报告充值10美元；capabilities HTTP200，共35个模型，9B/27B均列出。
现有SDK探针完成：prompt31/action111；teacher fixed评分有效，词表hash365c2d8a0c0e72d4bcc5dbc6c2e9330a87dae7ffc77e9fcd9d65739f4d16bfff。
Student sample/rescore最大绝对差0.2730098963，探针未设容差，必须继续数值核查，不能宣告完整严格OPD验收。
Teacher推荐renderer实测qwen3_8_xhigh_reasoning；评分输入保持qwen3_5。没有训练/update/reload/Modal创建，未读取实际余额/费用。
