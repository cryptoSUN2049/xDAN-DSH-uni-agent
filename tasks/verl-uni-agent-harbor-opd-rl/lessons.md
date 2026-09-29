# MiMo RL 集成经验

- GPU 库存随时变化：一次区域分配失败不等于 RTX PRO 6000 持续无货；升级到高价 GPU 前重新查询目标区域和规格。用户指定其他会话使用的机器时，只读核对归属，未经明确接管不得停止；2026-09-29 用户明确授权接管 11403，仍须先核对进程身份、优雅退出并验证显存释放，SSH 超时不能当作命令已执行。
- Mac TCP 已连接但 SSH banner 超时，先查 route 与网络接口；2026-09-29 默认 utun4 路由失败，单次 `ProxyCommand=nc -b en0 -G 8 %h %p` 成功，无需重启 Pod 或修改全局网络。仅对当前网络适用，不能把 Mac en0 参数带入云端控制器。
- 云端 Ruff 0.13.3 与本地0.15.8 对独立快照的导入分组检查结果不同；快照须携带仓库配置、包标记，工具版本也须对齐。显式src未解决本次差异，不能宣称已通过或修改导入分组迎合缺少上下文的检查。静态检查与真实云端测试分别记录。

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
- r6真实证明另一种max-tokens：32K上下文尚余空间，但累计生成恰为14336，末轮被裁至119/125。须按真实usage分别诊断context与episode预算；本轮改20480生成，保留32K与完成门。测试通过但未完成的轨迹仍不能伪装completed或从失败组挑选成功成员训练。

- 云端独立测试快照必须包含 tests/__init__.py、tests/uni_agent/__init__.py；否则helper imports可能落到editable旧仓，出现假RED/GREEN。同步排除__pycache__/*.pyc；最终验证使用独立PYTHONPYCACHEPREFIX并核__file__/co_filename与源码hash。
- 用户提醒及时commit/push：按已验证slice提交；混合worktree有独立嵌套仓库时，以待推送commit的干净detached worktree运行完整ruff check .和ruff format --check .，两者通过后从该精确HEAD推送，不绕过门禁、不格式化其他独立仓。
