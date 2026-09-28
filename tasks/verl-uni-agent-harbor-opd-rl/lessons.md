# MiMo RL 集成经验

- 用户要求不增加 Mac 性能占用：Mac 只做编辑、Git、轻量 SSH 与小证据回读。镜像、模型、依赖、测试、推理和训练都在云端；不要再次从 Mac 拉 Docker 镜像。
- 用户提醒复用既有 uv 环境时，先核 runbook、sys.prefix、freeze 与实际 metadata。当前 RL lane 的 273 项约束一致，本来没有 FA2/CuPy；重新 activate 不会增加依赖。不要把 SFT cu128 lane 或 VERL 另一版 uv.lock 混入现有 cu130/vLLM0.23 环境。
- GPU 分配前验证实际 recipe 所选 attention 与 checkpoint backend。单卡 colocate_async 的原生 naive 路径仍传真实权重，不应为继承的 NCCL 默认值修改共享环境。
- 平台 RUNNING 不证明容器可连接；r4 曾因宿主端口冲突无法启动，停止后启动同一实例恢复。依据 SSH、进程、GPU 和实际命令验收，守护回收期限保持不变。
- 计时须覆盖冷导入和子进程启动。首个 IPC 测试在 180 秒外层截止退出；原样同一测试延长等待后 203.53 秒通过。保留失败，不能跳过传输或削弱断言。带周期 traceback 的诊断探针出现 core，原因未建立，不能把该探针记为通过。
- 有效 GRPO 必须在同一步关联真实 reward 差异、正负 advantage、有限非零梯度和参数变化。旧 MECHANICS_ONLY、weight decay、optimizer step 增长都不足以证明学习。
- 新会话续训要核真实消费轨迹与 receipt，而非仅看步数。当前 TQ 版本无原生 checkpoint API，恢复从新队列采样；仍须在实际 GPU 环境核实。
