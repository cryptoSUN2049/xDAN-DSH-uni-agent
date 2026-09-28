# MiMo RL 集成经验

- 用户要求不增加 Mac 性能占用：Mac 只做编辑、Git、轻量 SSH 与小证据回读。镜像、模型、依赖、测试、推理和训练都在云端；不要再次从 Mac 拉 Docker 镜像。
- 用户提醒复用既有 uv 环境时，先核 runbook、sys.prefix、freeze 与实际 metadata。当前 RL lane 的 273 项约束一致，本来没有 FA2/CuPy；重新 activate 不会增加依赖。不要把 SFT cu128 lane 或 VERL 另一版 uv.lock 混入现有 cu130/vLLM0.23 环境。
- GPU 分配前验证实际 recipe 所选 attention 与 checkpoint backend。单卡 colocate_async 的原生 naive 路径仍传真实权重，不应为继承的 NCCL 默认值修改共享环境。
- 平台 RUNNING 不证明容器可连接；r4 曾因宿主端口冲突无法启动，停止后启动同一实例恢复。依据 SSH、进程、GPU 和实际命令验收，守护回收期限保持不变。
- 计时须覆盖冷导入和子进程启动。首个 IPC 测试在 180 秒外层截止退出；原样同一测试延长等待后 203.53 秒通过。保留失败，不能跳过传输或削弱断言。带周期 traceback 的诊断探针出现 core，原因未建立，不能把该探针记为通过。
- 有效 GRPO 必须在同一步关联真实 reward 差异、正负 advantage、有限非零梯度和参数变化。旧 MECHANICS_ONLY、weight decay、optimizer step 增长都不足以证明学习。
- 新会话续训要核真实消费轨迹与 receipt，而非仅看步数。当前 TQ 版本无原生 checkpoint API，恢复从新队列采样；仍须在实际 GPU 环境核实。
- FlashInfer 0.6.12 的 JIT 版本检查优先读取 `CUDA_HOME/bin/nvcc --version`，仅 nvcc 不可用/失败才回退 `torch.version.cuda`。因此 Torch cu130 不证明系统 nvcc12.8 可编译 SM12；`Failed to get device capability` 在初始化被捕获为 warning，但留下空架构集合后，未来该 JIT 路径仍可能失败。先定位实际源码及所走 backend，不改活跃环境、不把 warning 当最终失败或兼容性通过。
- 手动verifier校准不覆盖Harbor生产编排。Harbor0.16.1 separate verifier跳过tests上传；原始MiMo图无/tests，须在独立verifier context注入冻结四文件，并用原生_run_separate_verifier复验，不能用手工bash替代。
- DSH max-tokens要核每轮真实usage。r4两条终轮input+output均为16384，而累计生成仅7337/7104；这是总上下文耗尽，非4096单次或14336生成预算耗尽。扩大上下文时同步训练/logprob容量，保留独立生成上限与截断拒绝。
- pytest禁用自动插件时须显式加载pytest_asyncio.plugin。UnknownMark/async unsupported是测试执行失败，不能将未执行用例算通过；保留失败后再复验。
