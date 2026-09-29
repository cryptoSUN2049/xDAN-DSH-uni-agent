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
- 用户延长运行时间时先核内存中的controller/supervisor deadline；改磁盘JSON不能延长现有进程。新run使用原请求时刻算出的绝对截止，不能重启后重新计五小时；训练退出与Pod停止计费分别报告。
- r8完整n4奖励[0,1,1,0]仍在old-log-prob entropy阶段OOM。真实采样与可信reward只是训练前置条件；不得等同于optimizer更新或checkpoint成功。dense输出路径须实际核配置开关是否被执行，不能只看YAML已设置。

- 用户明确双卡目标时，区分 sync/colocate_async/separate_async 与卡数；单卡 smoke 仅用于短期排障，不应长期占用双卡而未给出迁移路径。2026-09-29 用户批准 separate_async，应落实 actor/rollout 独立资源池、非 naive 权重同步和实际 GPU 映射验收，不能仅修改可见卡数。

- 用户要求按实际创建时间清理超过两天的闲置 Modal App 时，不应额外要求名称含日期，也不应仅因代码未来可能 lookup 通用名字而保留。以平台 created_at、Function/Class、当前 Task/Sandbox 和正在运行流程的实际依赖判断；2026-09-29 扩大清理覆盖 undated 实验及 verl-crossbench/verl-harbor/verl-eval，冻结 r10 executor 未覆盖 app_name，故仅保留其实际继承的 __harbor__ 默认命名空间、近期 App 与部署的 Function 服务。Live Apps 数量不等于活跃 sandbox 数量，清理空部署不能虚报节省正在计费的计算资源。

- rl-insight0.3.0的finish仅清理进程内state，且Hub实际并非detached；不能据过时docstring推断它会存活。真实CPU Ray探针证明保留TaskRunner仍可能丢失最后Hub handle、导致首次Prometheus scrape前actor消失。必须保留原生Hub handle跨越finish，并以唯一preflight实验的真实Prom/Tempo回执验证，不靠sleep或端口健康推定通过。

- 冻结源码必须保持只读；Hydra会在进入用户entry之前创建日志目录，compose/tokenizer预检不覆盖这一步。launcher应显式配置独立私有hydra.run.dir，并验证实际只读cwd入口、日志元数据及pre-Ray guard，避免仅凭配置组合测试推断训练能启动。

- 用户追问“到底问题出在哪里”时，不能用进程存活、无traceback或初始化快照回答训练健康。每次状态核验必须同时读取当前operator终态、日志时间、最新step/checkpoint和API；标注查询时间。r12实际25分钟冷启动、单步1135秒采样/60秒更新，原生logger在整步结束才写history；无history不能推断卡死，也不能宣称正常。训练结束后空GPU与启动期空GPU必须明确区分。

- 用户明确A5是错字后立即取消该澄清依赖。双卡目标不能悄悄降成单卡对照；先查项目memory与实跑证据，区分学生+教师双卡、actor+rollout分卡、FSDP双rank。模式切换失败与旧链路成功须分开报告；已有C4不跨rank强行resume，独立fresh测试要明确告知。

- recipe中的runner参数可能被prepared launch.environment覆盖。r13虽通过配置fixture测试，实际prepare继承max_concurrent_sessions=1使最终并发仍为1；预检正确拦住。修改吞吐参数时必须核实际prepare输出→build_overrides→最终compose整个绑定链，不能只测缺少覆盖字段的手写launch fixture。

- r14 的双卡模型已初始化，却因手动controller PATH误指到共享root/bin、实际cloudflared在/root/mimo-private/bin而在首次注册失败。GPU预检与unregistered健康检查都不覆盖延迟启动的外部二进制。所有controller启动必须在最终子进程环境中解析ssh/cloudflared，校验现有binary/hash/version；在GPU前执行有界真实HTTPS nonce探针并清理，main缺依赖时禁止创建资源。不得把这类操作遗漏归因于GPU模式，也不能在用户睡觉后只留下running表象。

- R15 暴露训练侧 sessions=2 并不意味着环境服务可并发：worker 的 unfinished-task 检查和 SQLite ledger 都硬编码单任务，第二请求 HTTP409，导致整组失败。变更并发必须核完整 producer→HTTP→worker→ledger 链，并用真实两 HTTP 请求、第三拒绝、独立取消/清理回归；未确认清理的任务继续占位，不能为吞吐绕过隔离。此类服务容量不匹配不能归因双卡 FSDP 或模式不适合。

- R17 主train.log延迟转发，实际TaskRunner Ray stdout已存在完整step1、同步与更新指标。状态判断应同时核原始worker日志、checkpoint完成marker与原生Prom/API；不要误报保存后卡住。异步预取的新job可早于checkpoint创建，须用后续轨迹policy版本判断权重反馈，不能仅凭新job运行证明已使用新权重。
