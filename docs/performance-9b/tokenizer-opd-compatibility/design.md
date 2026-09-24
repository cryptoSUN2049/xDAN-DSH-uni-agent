# 9B→27B OPD 兼容性真实测试

用户2026-09-24已授权实际测试。当前worktree performance-9b/85ef145，保留已有未提交变更。

目标：验证实际加载的tokenizer/模板、学生生成token的教师评分、位置对齐；不宣称教师能力或训练收益。
路径：CPU编码与模板对照 → GPU0串行HF学生生成/教师前向 → GPU0 vLLM同token评分对照。
GPU1有其他任务，不使用、不清理。每次GPU阶段启动前确认GPU0空闲；无空闲则暂停GPU阶段。
文件：本目录probe.py、设计和证据JSON；远端runs/tokenizer-opd-compat-20260924独立目录。
接口：使用本地模型目录，JSON输入输出，记录模型配置、tokenizer、模板哈希；输出浮点logprob，不传访问密钥。
验证：文本/中文/代码/thinking/工具/新增token的编码、decode与模板；学生真实生成；HF next-token logits与vLLM prompt_logprobs的相同token及偏移对齐；记录数值误差而非要求bf16逐位相等。
限制：不运行优化器，不修改checkpoint，不代表MOPD或领域能力验收通过。
