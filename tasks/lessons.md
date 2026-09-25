# 项目经验

## 2026-09-21：跨benchmark真实控制与沙箱命名

- Harbor trial_name会成为Modal共享app内的sandbox名字；不同benchmark并行控制不能都叫nop/oracle，需加入数据集/输出路径唯一摘要。目录不同不代表云端名字隔离。
- 依赖数据下载成功和CPU回归不足以放行模型评测；先用nop/oracle检查实际任务和verifier。build-cython-ext本次oracle出现10通过1失败，不能算模型退步，也不能悄悄删除该题或改评分。
- SSH/scp会偶发Connection closed，依赖部署的后续命令必须等上传exit=0并核SHA，不能把session_id当上传完成。

## 2026-09-15：用户指定交接即停止重复执行

- 用户选择“PR＋handoff，由对方会话执行”后，保持PR开放并交付明确接续入口；不继续替对方合并、部署或启动GPU。
- 任务移交不代表长期目标完成；记录剩余验收与执行归属，不为停下而假报complete。

## 2026-09-15：临时验证worktree必须明确收敛出口

- 用户质疑新增worktree与本会话目标。隔离并行修改时，先说明唯一产品主线、临时分支职责、具体交付提交与回收方式。
- 独立验证分支不演变成第二条集成主线；交叉测试可使用临时合并，验证后保留修复提交供产品分支挑选，不反复整体同步。
- 目标保持原生RL/OPD真实闭环；修复/CPU通过仅是节点，不能替代GPU更新、恢复和效果验收。

## 2026-09-15：按可审核节点交付，避免只汇报进展

- 用户要求合理节点 commit、push，并同步 handoff、tasks、goal。独立验收、修复回归、真实GPU验收各自形成交付节点，不积压到总目标结束。
- 每次push前执行 Ruff lint/format 双门；记录测试范围、未通过门槛和远端回读结果。
- 平台goal若为paused，只如实记录；工具不支持恢复状态，不假报active或以complete代替暂停。

## 2026-09-09：工程执行与学习证据分开，评估调度不冒充安全豁免

- 用户明确工程执行、真实消费、保存和独立reload先完成；有效更新证据其次，任务效果最后。合法零奖励/零梯度是诊断，不主动停有界训练，不以反复调prompt代替工程交付。
- r2/r3均因step4内嵌periodic val的WS06 A越权写只读来源而使训练退出。调度修复将训练和独立评估分开；单条评估被拒应保留独立failed结果，不能伪造TQ或把安全错误降为合法样本。训练自身安全/证据门保持原样。
- 关闭训练内val不等于取消验收：独立val/reload仍核真实会话、回执、工件、token/version与消费。只有流程完成可称工程节点通过；非零任务梯度/参数变化/提升幅度分别留证。
- r3失败、step4 checkpoint存在、r4尚未启动必须同时明确；禁止把进程启动、GPU加载、保存文件或历史canary当作新训练成功。
- 当前DSH SDK/runtime已0.1.3a2/b236并发布私有Release、固定runtimehash。遇旧截图“未发布”先核lock/产物与真实版本，不重复重建已有可用环境。

## 2026-09-08：跨仓库职责与唯一训练集成主线（用户已确认）

- `xDAN-DSH-uni-agent` 是训练集成开发主仓：负责 DSH adapter、Gateway、
  轨迹与奖励准入、训练入口、Harbor / Modal 接入，以及训练项目的统一进度与验收记录。
- `xDAN-DSH-Exp` 负责 DSH 本体、runtime / SDK / 插件与 Harness 内部能力，
  并保留历史实验、原始研究和验收协议；`dsh-official-training` 不是另一套训练实现主线。
- 当前训练实现由 `dsh-v3-live-smoke` 承接，Harbor 增量由
  `harbor-modal-integration` 承接；worktree 名不是永久架构边界，合并后以实际 Git 状态为准。
- 跨仓修改：DSH 内部能力在 DSH 仓库实施；训练主仓引用明确的 commit / artifact
  identity 并验证兼容性。不在两边重复实现 adapter、数据合同或训练入口。
- 文档只保留一个可编辑权威来源。训练主仓引用 DSH 的原始研究与历史证据；
  必要快照注明来源、revision、日期和证据范围，不复制成两套独立推进的完整方案。
- 状态冲突时先核对实际代码、run manifest 和日志，再更新训练主仓的当前状态；
  不凭目录名、最近文档修改时间或旧 todo 判定谁领先，不追认历史实验合格。
- 冷启动先读本节和当前 worktree handoff，再查两边 Git 状态；发现 DSH 侧旧
  “等待实现”记录时先核对 Uni-Agent，避免重做已交付工作。
- 本决策由用户明确确认；只确立职责，不代表批准云资源、训练运行或新增方法实现。

## 2026-09-06：项目记忆必须能在所属仓库恢复

- 用户指出训练交接仅保存在 sibling DSH worktree。本仓库须保留自己的
  `tasks/<branch>/handoff.md` 与 `docs/<branch>/project-status.md`，使新 session
  无需先猜测外部仓库路径就能确认分支、证据、目标和最近阻塞。
- 跨仓库原始设计、论文和实验账本保留其所有权；本地状态快照注明日期、来源
  revision 和证据范围。更新实验状态时同步本仓库快照，避免维护两套完整资料。
- 当前 `dsh-adapter` 是独立 Uni-Agent 仓库的开发分支。位于 DSH
  `.Codex/worktrees/uni-agent-dsh-adapter` 的旧 clone 不代表最新实现。
- 单测/trace replay、真实 process smoke、optimizer update、checkpoint reload、
  held-out uplift 是不同证据。后续代码修复不得追认旧 run 合格；远端状态须带
  查询日期，不能把旧 `status=running` 或历史停止记录当作实时状态。

## 2026-09-07：先比较全路径成本，再选择是否使用 GPU

- CPU 可连接模型 API，不等于能直接复用要求真实 Gateway ID 的训练 Agent/Task。
  评估成本时计入新增预算、receipt、隔离适配；不要仅按 GPU 小时费判断路径更省。
- DSH turn 不等于模型请求次数；SDK 的逐请求 max_tokens 与 RPC timeout 不等于
  总 token / episode wall-clock 上限。用源码与可执行测试证明预算实际在哪一层生效。
- `sdk-minimal` 的临时 cwd 不是宿主隔离，Cordis node:vm 也不是 containment。
  无模型初始化成功不授权在本机全权限环境运行模型生成的 host code。
- 本机 Ruff 通过不等于 CI 固定版本通过；显式声明本项目 first-party imports，
  避免两版 formatter 反复改动同一空行。
- 当前 runpodctl 2.12.0 help 不含 skill 示例的 terminate-after / stop-after。
  创建前验证真正可执行的停止机制，不把负载退出当作停止 GPU 计费。
- 导出卡住不能延后停费截止；停止后的存储费、补导出和资源删除也必须有截止条件。
- 独立 Pod 只隔离本机；同 UID 的模型代码仍可能修改 Pod 内 verifier/fixture。
  digest 复核可发现变化，但不构成不可篡改或候选权限隔离的证明。

## 2026-09-07：区分本地适配状态与上游生态能力

- 用户要求继续搜索 Uni-Agent / VERL + Harbor，并指出官方新闻、教程和 Hub。
  本地 eval-only 只能说明当前适配范围，不能推导整个生态没有 RL 方案；需核查
  上游代码、PR 是否合并、官方 recipe 与依赖版本，并区分作者实验和独立复现。
- Harbor 任务格式复用、原生 Trial 接入、训练 DSH Agent 是三个层次；Tinker
  Bash Agent 训练成功不能追认为 DSH 已打通，未合并 VERL PR 不能写成 main 能力。
- 长流程的环境连续、会话记忆与权重学习要分别解释。Harbor 多步骤默认新对话；
  resume 依赖 Agent capability，旧依赖版本不能自动享有新版功能。
- 面向入门用户先解释角色和证据，再讲 API。起步命令应限制单任务；latest 任务
  集可能包含 GPU / 多容器任务，不能把完整 benchmark 当作无成本入门检查。

## 2026-09-08：承认历史训练闭环，区分新增集成验收

- 用户提醒此前 DSH → Uni-Agent → VERL 已在 RunPod GPU 真实运行。介绍后续计划时必须先承认已有 64 rollouts / 4 optimizer steps / 独立 reload，不笼统说整个项目尚未跑通。
- 当前 H0 未执行、八类新 smoke 0/8，仅针对新增验收范围；后续工作是恢复复建、修复验收和扩展 Harbor / 教师学习 / Harness，不从零重建已有训练底座。
- 用户记忆的 RTX 5090 型号尚未在本轮历史运行记录中确认；GPU 价格表中的型号不能作为实际运行硬件证据。

## 2026-09-08：Harness RL是明确目标，先审计已有能力

- 用户明确4B终局：熟练DSH调用与调度、记忆/上下文管理、受控RSI行为、终端任务能力。Harness RL不能从范围中淡化成可有可无；分阶段实现而非删除目标。
- 先检查Uni-Agent已有MemAgent、Gateway多轨迹与异步recipe，避免重复建设。当前teacher_client不支持，不能声称OPD配置即用。
- ContextPilot保留专题原始资产，训练集成以Uni-Agent为主；树分支partial rollout与异步partial rollout分开设计。

## 2026-09-08：用户确认三阶段主线

- 第一阶段工程贯通：恢复复验历史DSH/Uni-Agent/VERL，接通Harbor/Docker最小增量；建立可信数据、更新/reload和评估，不把能力提分作为工程完成条件。
- 第二阶段任务效果：围绕DSH专长、记忆/上下文、终端与RSI任务，按缺口选择SFT/OPD/Harness RL，以独立同预算评估证明收益。
- 第三阶段性能与规模：全异步、并发和按需Modal云端环境；验收吞吐、成本、稳定性和质量不退化。使用必要云GPU不等于提前开展第三阶段。
- S0—S11为交付物编号，不是严格顺序；不能把Harness RL/RSI推迟到Modal之后，也不能让OPD或Modal阻塞第一阶段。

## 2026-09-08：工程贯通包含安装部署与真实服务接线

- 用户指出只有适配代码和 CPU 测试不够：第一阶段必须包含可复建安装、服务连通、真实执行与 GPU update/reload。
- deployment/ 统一负责环境与服务；examples/dsh/ops/ 保留实验入口，不复制启动器。
- 文档目录和脚本规划不等于安装器已实现，更不等于整条链路已部署。

## 2026-09-08：按用户的能力递进选择工程任务

- 用户明确先最简单原生Uni-Agent训练，再带DSH真实轨迹的记忆/上下文能力，再扩展后续层级。
- 原生诊断仍是短步骤；M1的优先任务应围绕真实DSH记忆动作和观测证据，区分训练合同跑通与能力提升，不长期停留在无关toy任务。
- 复用MemAgent机制但保持DSH唯一执行循环，跨会话奖励与事实保真需独立实现/验收。

## 2026-09-08：RunPod网络盘与私有源码复建

- 网络卷上root也可能无法chown；解包官方已校验tar使用--no-same-owner，不把所有权恢复报错误判为文件内容损坏。
- 本地研究commit未推送时，先检查已发布祖先与runtime源码是否一致；只读Deploy Key限定单仓，比向GPU主机复制个人PAT更合适。

## 2026-09-08：DSH 架构升级必须审计真实消费者

- 用户提醒旧 Session API 转换器依赖；不能仅比较 Python SDK 签名就宣称 runtime 兼容。必须追踪 converter、ContextPilot runner/exporter、事件坐标与 flush/snapshot 生命周期。
- 版本以精确源码 catalog 为准，README 可能滞后；聚焦测试与完整构建分别记录 revision、退出状态，不把旧失败日志归因于新 HEAD。
- 已通过的固定 runtime 继续工程验证；候选版本单独迁移，不直接改变进行中的训练基线。
- 跨会话截图中的“本项目”必须回到绝对路径和commit核实。DSH-Exp离线converter修复不等于Uni-Agent在线SDK需要复制相同改动；先查调用链，避免重复适配。用户要求先验新版再继续时，更新执行顺序，但保留旧pin作为对照。
- 用户明确“统一切换0.1.3-alpha.2”后，新版应成为后续默认目标；不能继续将旧版作为M2默认路线。历史备份不等于并行主线；区分目标配置、已安装版本与已验收运行三种状态。
- 新版fs-ext触发node-gyp下载headers，网络盘fchown会EPERM；仅修外层tar --no-same-owner不够。构建时npm_config_nodedir指向已校验Node发行包（自带include/node），避免再次解包另一套headers。该修复需真实Linux重跑，不能凭CPU输入测试宣布构建通过。

- 2026-09-08 RunPod 网络盘真实权限：本 Pod `/workspace` 的文件创建 mode=0600、chmod600 均仍报告0666，目录0700仍777。严格私有凭据和审计运行证据必须放本地 `/root/runs`，读取前验证实际stat；checkpoint可继续在持久盘。不得为适配网络盘删除所有权/权限检查。运行结束应把不含凭据的证据归档并记录摘要后持久保存。

- 2026-09-08 单卡M2入口必须显式保留已验证M1的ROLLOUT_LAYERED_SUMMON=False。仅复制LoRA/显存参数而沿用底座layered=True会使collect_lora_params空收集fallback调用offload_to_cpu=True，Torch NO_SHARD拒绝；ACTOR_PARAM_OFFLOAD=True本身不是该异常的充分原因。必须把实际生效配置与参考run逐项比较。

- 用户确认旧Runpod停止并换新Pod：云盘保留不代表/root、SSH部署key、Ray/运行凭据保留。先验持久资产与venv，再重建本地身份/节点IP；最终日志应排除凭据后归档到持久盘。handoff顶部“当前状态”必须更新，不能让旧优先覆盖段与后文新事实冲突。

- 用户再次明确：全异步、Modal和云端沙盒扩容属于后续性能阶段，当前不急、不推进。优先固定版本工程闭环、真实更新/reload/评估，再讨论能力效果与性能。不得因可选基础设施研究分散主线。

- 用户明确要求跑有价值的真实任务。文件写入仅限连接诊断，trim仅是字符串工具练习，不可包装为上下文/记忆能力训练。后续任务必须定义真实DSH动作、独立可核验结果和留出输入；奖励全相同应停止堆训练步数，记录无学习信号。

## 2026-09-08：失败样本准入与实际学习信号

- finished且证据可信的任务失败与不可信/越权证据分开记录；旧verifier把无define归missing_pre_define_inspection并拒绝，整组重采样可能只保留成功，导致GRPO全1奖励和0梯度。先审计被淘汰组，不靠增加步数解决。
- 修复准入必须独立版本、绑定父源码与新数据身份，失败仍得0；不改旧reward/receipt或将安全门整体放开。
- exit0、保存checkpoint与有效参数更新不同；逐张量检查无变化时明确失败，不能因留出基线满分宣称训练提升。
- 短SSH探针成功不能代表训练周期的长连接稳定；记录完整观测窗和断后证据，有限抖动容忍不等于根因已解决。

- GPU checkpoint按用户指定持久目录`/workspace/<project>/checkpoint/<run>`保存。配额不足先实际write+fsync核验，不能用共享文件系统df推断用户配额；不能只迁checkpoint而遗漏Hydra等写入，或静默切换到易失/root。

- SSH远端heredoc须对整个远端命令作正确shell引用；内嵌Python引号可能被外层shell吃掉。后台PID返回不代表训练启动成功，必须检查supervisor.log、train.log及持续存活。

- 用户已将新增数据生成安排另一会话；本会话继续M1收尾与Harbor M2工程，不再重复建数据生成器。跨仓数据协作由Uni-Agent定义训练验收，campaign负责生产，不能混改当前固定课程。

- 用户再次确认：本会话只推进G1工程与Harbor Docker增量；完整打通后再考虑异步性能，SFT不在范围内。生成服务async与trainer模式必须分别说明。

- 用户要求每个环节验收完成立即commit/push：先更新证据、Goal和handoff，再Ruff双门和相关测试，推送并核对。未通过环节记为阻塞，不等待整条G1完成才存档。

## 2026-09-09 原生优先纠偏
用户明确把Harbor训练后置，先完成可复建原生链路及DSH/记忆/上下文/RSI。旧M2计划不得继续驱动GPU启动；及时替换active goal并归档历史，而非只在聊天改变顺序。四类能力覆盖不等于四类能力提升，异步不成为训练效果前置。

- N0复建不能从旧pyvenv.cfg home推断解释器存在；用command -v与readlink实际核验。第一次错路径失败必须留日志，再有证据地重试。

- uv pip的显式版本可能被当前项目tool.uv.override-dependencies覆盖；lock之外的已批准overlay须--no-config隔离，并实际pip check/import验证，不能只信命令参数或Audited日志。

- 用户确认另一会话共享同一GPU：本会话新venv/checkouts不等于GPU隔离。未协调前禁止启动CUDA探针/模型/train/reload；只做本会话CPU安装准备。不得自动ray stop、pkill或通过一瞬GPU空闲推断有独占权。

- 用户澄清无人占GPU，现场也无计算PID；应撤销基于早先歧义建立的GPU阻塞，不再重复询问使用权。优先四类能力真实完成，“独立复建”近期解释为固定条件独立重跑任务结果；从零安装不是能力训练前置。

- 用户强调充分利用GPU及数据量：CPU准备与有价值的GPU任务并行；四例诊断不是正式能力训练集。按有效任务覆盖、奖励差异和更新证据判断进度，不能靠重复采样或显存占用宣称有效训练。

- max-tokens不是必然生成上限：先查每轮input/output及工具观测。grounding-r1仅61输出token，Service大目录耗尽轨迹容量；未定位前不能直接建议只增加生成预算。

- parallel_infer_verl没有--temperature CLI；采样温度从任务model配置或固定默认0.8解析。启动前用真实_parse_args/init_config校验全部argv，不从其他入口猜参数。context-v2-r1因此CPU参数解析exit2，保留该失败并用新r2身份重启。

## 2026-09-09 — 训练数据量与工具 API 准入

- 用户要求数据量足够：统计独立实例、结构族、尝试次数及优化器实际消费，不能把重复行/新UID当作数据覆盖。先使用现有课程验证有效信号，再按失败场景扩充，拒绝虚构统一行业最低样本量。
- context v2 GPU 16条会话被误拒：verifier只允许command/path，却未对照固定DSH的合法view_range/null语义。工具消费者适配必须读固定版本源码，并加入真实调用形状回归；范围参数合法与实际完整读取证据分开验证。
- 反事实重评分只用于定位错误，不能覆盖历史回执或当作送入优化器的真实轨迹。新verifier闭包需新prepare、新run和真实评分。

- context v2 r3启动错误：不要手写相对PYTHONPATH=.:verl给会切cwd的runner/verifier。直接使用prepare manifest.environment的绝对PYTHONPATH；GPU前在任务data cwd导入实际verifier，并核bundle摘要。r3作为部署失败保留，不归因模型。

## 2026-09-09：Ray短路径与GPU初始化证据

- root手写`RAY_TMPDIR=/tmp/dsh-memory-constraints-r3-reader`导致Ray MetricsHead Unix socket总路径超过107字节；dashboard失败不等于训练/推理失败，当前vLLM仍完成加载。
- 后续监督入口用run摘要构造短且独立的/tmp目录，记录实际值并拒绝复用；不要把完整业务run名层层拼进Ray socket路径。
- 将初始化、采样、参数更新的耗时分别记录。不能凭某一时刻GPU 0%判断CUDA未安装，也不能把显存驻留当吞吐提升。

## 2026-09-09：工程闭环范围与启动实证

- 本阶段首先验收真实执行、轨迹/奖励消费、有效参数更新、checkpoint保存、独立reload及评估产出；提分和数据扩量不作为工程闭环前置条件，但不得用异常更新冒充正确训练。
- 拿到 supervisor PID 不等于模型启动。必须继续核监督日志、训练日志、子进程和GPU状态；启动断言失败应明确报告。
- ops启动器即使PRINT_COMMAND也会创建RUN_ROOT/command.txt和run-manifest.json，并标completed。这只是打印命令成功，不能当作训练结果。打印预检使用独立scratch RUN_ROOT；正式run必须全新。保留失败证据，不删除或改写旧回执。

### PRINT_COMMAND目录冲突：已核实案例与处理规则

- 案例：context-v2-curriculum-r1-reload-step12。外层ops先建RUN_ROOT并写manifest，内层PRINT_COMMAND打印后exit0，外层误把打印结果记为completed；正式supervisor因目录已存在拒绝启动。根因是预检副作用，不是CUDA故障。
- 处理：确认目录仅含command.txt/run-manifest.json后，原样重命名为独立print-command-evidence目录保存；保持正式新目录检查，不设置ALLOW_REUSE、不删除证据。随后重新启动，实际step12 reload已470.012秒exit0，4/4新鲜评估消费通过。
- 防复发：预检使用独立scratch身份与所有输出路径，优先只读JSON命令清单；首次PID后继续核真实训练日志、模型加载、GPU和最终消费证据。打印模式的completed绝不能计为训练完成。

## 2026-09-09：默认worker句柄不等于实际奖励路径

- memory-resident-val-r1真实GPU构造失败：VERL默认传入reward_loop_worker_handles（8个worker），但DSH已有verifier reward时原Gateway优先使用TaskResult.reward。新NativeMemory仅因句柄非空便拒绝，混淆了对象存在与实际数据流。
- CPU factory测试必须模拟生产默认依赖注入（非空handles且custom_reward_function=None），验证A/B原奖励不变、worker没有调用；不能只用None替身。NativeMemory显式禁止额外reward通道，同时保持strict verifier门，不改默认Gateway或VERL。
- 已确认不可恢复的框架构造失败无需等待一小时预算：先核具体child命令和pgid，仅停止该run拥有的进程组，再检查GPU释放。外部SIGTERM可能使内层run-manifest仍running，终态以supervisor-result与活进程交叉核验，保留原始不一致而不伪造正常完成。

### 2026-09-09：进展必须带运行身份和时间

- 用户追问“上一轮失败是什么时候”：不能只说上一轮/已经跑通。每次故障或成功明确 run-id、Asia/Singapore时间、阶段、影响范围，与历史已通过实验区分。
- 原始日志UTC保留，面向用户明确换算UTC+8；PID/显存/初始化与真实任务完成分别报告。

### 2026-09-09：记忆/context目标不能缩成固定A/B问答

- 用户明确要适时handoff、goal/tasks进度、memory、索引、offload与compact。必须把“何时、存什么、怎样找回、如何继续行动”列为训练决策。
- 原生MemAgent多context方法、DSH实际会话状态操作、文件持久化、跨会话回读分别验收；共有训练底座不等于完整移植原生recipe。
- 以重启/上下文切换后的真实任务完成和证据保真评分；不能以多写文件、压缩token更多或固定问答成功替代用户的能力目标。

### 2026-09-09：真实任务与工程贯通共同驱动goal

- 用户明确双目标：设计有价值的工作状态任务，并用它们推动原生在线RL闭环。不能把任务设计变成无限研究，也不能反复用过简诊断题替代真实任务验收。
- 当前工作包独立列任务合同、实际消费、有效更新、checkpoint与独立reload证据；旧context梯度或旧memory val成功不能抵扣新课程节点。
- 能力提升幅度通过后续同预算对照实验衡量，不作为首阶段工程退出前置；合法低分是学习样本，越权/篡改/基础设施异常则按合同拒绝。

### 2026-09-09：工作状态课程角色与终止条件

- work-state-val-r1首WS01 A正确读取来源后试图把只读schema3改4，被policy拒。74工具调用后DSH报告completed，但不能据此认定自然结束：后续原NPZ核验发现16384容量边界且末token非EOS，固定VERL又合并length/stop。原先“不是token耗尽”的结论过强，已纠正；原回执不改。交接角色和业务执行也应在提示中分清。
- 在线RL必须核验原始生成结束边界；框架completed不等于backend自然stop。若结束原因已丢失，只记录可复核EOS/容量与不确定性，不能补造finish_reason或将合法低分当作完整执行证明。升级协议须新版本、新run，运行中源码不可改。
- 训练任务先审公开输入输出合同：评分要求的业务字段名和类型必须对actor可见，不能让模型猜隐藏schema。新空记忆目录要明确可create，最终聊天不是已保存的文件；否则全零可能反映任务说明缺口。修复只公开合同，不提供本实例答案，不追改旧奖励。
- step4 checkpoint可先于定期评估/指标落盘；评估失败时只有step1–3 metrics或rollout dump，不能据checkpoint目录推断step4存在非零梯度或完整消费。分别记录保存事实、实际可审计消费和有效学习。
- 用户明确工程链路优先：不要因复杂任务暂未成功而无限优化prompt、延后完整训练/保存/reload。合法全零可先完成工程诊断，诚实标记尚无学习信号；将执行完整、有效更新、能力提升分别验收。真实安全/数据完整性错误仍需修复，不能为跑完而降准入。
- A明确只保存有来源的恢复状态，B才执行配置/计划；可选文件不是必填列表，完成有用交接即可停止。工具使用绝对路径，持久索引用相对路径，不能指向B无法访问的A来源目录。
- 提示语义修订必须新source摘要/新run；原权限/奖励/真值不变。提示改善与参数学习分别报告，保留r1原失败与合法低分链。

## 2026-09-09 评估收尾与零梯度诊断
- 固定VERL评估整批结束才写dump；跨题传播异常会让之前TQ提交没有最终消费证据。用独立任务边界保留结果，不能事后补造dump或靠删失败题宣称全通过。
- finished=false/max-tokens是未完成任务；eligible=false是项目合同拒绝，两者不能混同CUDA故障或合法零奖励。保留原回执，分类报告。
- 全零奖励先独立重评分并查真实业务产物和工具读取。r4 32条配置全错、1条读取index，不能放宽评分或用文件数/固定常量造学习信号。
- 操作指南的历史状态必须及时移出当前入口；脚本存在、新环境安装通过、完整新主机复跑是三种不同证据。

- 工程评估的完成应按用户已明确的标准核验：固定题有终态、成功题有真实消费、失败有原始原因、母状态与清理可信。不得另外增加“四题必须全部准入/业务成功”门槛；all_verified=false保留为严格统计，不能伪报4/4，也不抹去已完成的工程收尾。

### 2026-09-10：工具格式失败先检查真实模型输入

- core r4四个Reader输出裸tool JSON，但实际prompt_ids已包含完整工具schema与原生<tool_call>示例。不能从输出失败推断输入缺少示例；先反解真实token并核模板/source身份，再设计单变量实验。
- 成功旧课程也包含“index may be missing”，不能把共享措辞称作新增回归。区分相关现象、可测试假设与受控对照证明的因果；不通过自动执行裸JSON或放宽评分掩盖协议失败。

### 2026-09-10：监控DSH运行时原件，不盯结束后导出文件

- `uni_agent/agents/dsh/runner.py`在harness.run返回后才写`traces/*/session.jsonl`。该文件不更新可能只是上一条已结束stage，不能判定当前长生成停滞。
- 活跃监控使用`chains/memory-*/*/run/homes/*/sessions/*/*/session.v2.jsonl`，结合runtime PID/父进程与当前input路径；导出trace用于终态审计。Session v2原件与训练导出消费格式是两个层次。

### 2026-09-10 诊断执行边界

- 调整共享测试助手参数（如budget）后，搜索所有直接调用并执行消费审计回归；不能只验证定义所在文件。
- runtime声明哈希必须与实际SDK resolve结果绑定；inline父环境才会进入DSH子进程，给vLLM设置变量并不能控制DSH。PYTHONPATH必须是绝对路径，避免branch cwd改变导入位置。
- view调用次数是尝试，不是成功取回或使用事实。报告字段必须准确命名，避免把失败读取算作记忆能力证据。

## 2026-09-15：架构所有权
用户要求以Uni-Agent为架构主线。不能因Tinker P0成功就改用Cookbook trainer；先查所有worktree和Uni-Agent adapter/TQ/VERL接口，区分算法复用与框架替换。

## 2026-09-15 全异步LoRA RL目标澄清

用户再次明确目标是全异步高性能LoRA RL，OPD是同一通路的可组合学习信号。不要把目标缩减成Teacher评分demo，也不要将colocate_async的阶段切换说成独立训练/rollout同时运行。验收要覆盖LoRA同步、版本滞后、有效吞吐与任务奖励；先完成现有单卡验证，在真正需要时通知用户开双卡，不提前空等资源。

## 2026-09-15：长任务按验证节点持久化

- 用户明确要求合理节点 commit、push、handoff、tasks、goal 更新。完成一批可独立验收的代码后即保存与推送，不让后续实验阻塞已有交付物持久化。
- 每次 push 前执行全库 Ruff check 与 format --check；handoff 记录实际提交、测试、远端环境和下一步，区分CPU、GPU组件、训练闭环证据。
- goal 工具仅在真实完成/持续阻塞达到规则时改变状态；进行中的里程碑细节更新到 tasks，不能为“更新进度”误标 complete。

## 2026-09-15：跨会话交付合并后由唯一产品会话执行

- 用户交接PR #3并明确verify-native-training-closure停止重复实施；后续合并、GPU训练和恢复由verl-uni-agent-harbor-opd-rl统一执行。先读recipient-handoff、核最新HEAD/checks，再合并，不再复制另一套训练入口。
- 合并时保留本会话未提交的独立组件验证增量，不把它与已交付启动器修复重复实现；以当前代码/进程结果纠正handoff中的旧状态。

## 2026-09-15：不得把方案缺项当作运行根因
- 用户纠正：要求证明 Modal 是否为训练卡点。
- 自建 HTTPS/named Tunnel 配置约束不等于 Modal 平台要求；缺少配置不等于已经发生该阶段故障。
- 报告卡点必须附真实启动命令、失败阶段和日志；无此证据标记“尚未验证”。SSH 观测失败不得推断 GPU/作业状态；单卡资源限制只约束指定的分卡拓扑。

## 2026-09-21 checkpoint 评测
- 311/312仅有基础设施缺口时，不应每次整套重跑312条；固定source attempt，仅补明确缺失的task/sample，保留所有已判0/1结果与infra原始记录，组合后重新做全集校验。
- GPU瞬时利用率0%不是空闲证据，需结合显存、进程、队列日志；恢复/沙箱等待阶段也可能0%。

## 2026-09-23：Performance-9B 研究范围与归档

- 用户要求主参考采用2026年材料；不能以旧论文的新修订日期冒充2026年新工作。
- 用户将数据保存目标明确为 Hugging Face；优先归档到当前账号私有数据仓库，保留原始文件、来源 revision、许可证和哈希，不把归档等同训练准入。

## 2026-09-23：保留用户MOPD主目标
- 用户明确目标为全面能力多教师在线蒸馏。不能把数据筛选擅自收窄为SFT＋单教师OPD主路线。
- 区分静态多教师轨迹、在线token级MOPD与黑盒judge RL；同族标签不能替代tokenizer和评分接口兼容性检查。

- 2026-09-24 核验上游OPD文档：明确要求teacher共享student tokenizer/vocab。回答应先说这一硬约束，不能用“没有同族名称检查”造成支持任意异族教师的误解。

- 2026-09-24 用户纠正：训练启动前显式激活VERL专用uv环境并验证sys.prefix，核查Ray worker继承；区分“队列启动”“模型加载”“实际更新”，不可混称训练已开始。

## 2026-09-24：产线目标不能缩成一次OPD训练
- 用户明确核心目标是科学、完整、专业、可观测和可分析的训练产线；1000条实验只是首个验收载体。
- 总纲必须覆盖核心指标定义、证据入口、故障定位、受控修复和效果验证；保持唯一HTML入口与项目记忆索引。
- 按实际执行路径区分原生文本OPD与Uni-Agent工具任务；纯OPD不套GRPO有效组门，mock接线不等于真实后端上线。

## 2026-09-24 产线与阶段目标必须双维组织
用户纠正：长期产线架构之外，还要显式展示OPD/MOPD/Verifier/Curator/观测分析/大规模RL等阶段性专项。规则：架构按职责与接口组织，专项按目标、依赖、产物、验收与状态组织；不能将安装组件当作专项完成。研究来源只作辅助导航，不占用阶段目标维度。

## 2026-09-24 高性能目标必须落在用户工作能力
用户澄清“接近Opus4.6”主要指日常工作与Agent能力。规则：用交付物、工具操作、约束保持、恢复及人工介入定义目标；数学/知识榜单仅作护栏。无工具短文本试验不能代表Agent能力，教师发布成绩不能代替同预算优势实测。

## 2026-09-24：Distill命名不等于OPD

- 解释蒸馏模型时先核对训练目标与采样归属：离线示范SFT、学生采样OPD、环境奖励RL分别标注。
- MiMo公开9B是SFT起点；旗舰MOPD2和表6分别训练的领域RL成绩不得归到该公开权重。

## 2026-09-24：APUS模板名称与继承边界

- 用户已确定允许继承MiMo权重，模板名统一apus-chat-v1，不再使用APUS v2.6模板名。
- 中立数据/API/模型token序列分层比较；ChatGPT公开API不等于内部训练模板。

## 2026-09-24：强教师母本与坏派生库不可一并排除

- 用户指出Fable5/GPT5.6/GPT6覆盖不足。数据画像的同名local X/HF S可能是去重维度与母本优先级冲突，须按revision/来源解析，不能只看tier做整族裁决。
- 优先验证强教师原始/独立轨迹；教师名、无CoT、难以回放分别与身份/完整性/质量分开。
- 累积前缀数据只监督目标下一步，不能把之前assistant重复算loss；任务/session与行数分别统计。

## 2026-09-24：通用保留的教师约束

用户明确通用保留也用Fable/GPT5.6系列。不得默认以Nemotron替代；数据不足应标缺口。最终清单集中一份权威版本，旧配方标历史，来源轴/能力轴分别统计。

- 用户指定MoreThought具体数据集时逐库核验，不按组织或旧衍生库整体排除。混合教师数据不能按仓库标题计为纯Fable；GPT-5.5不能充作GPT-5.6。

- CodeFlame必须作为独立加工批次，用户明确排除Gemini 3.1系列。过滤依据教师/来源证据及轨迹组，未知身份隔离；文档规定不等于已完成全量过滤。

- 用户要求能力/场景分布优先引用README：发布者已有说明不重复全量统计，未披露比例明确留空。与必要教师过滤、污染隔离、去重、最终发布计数区分，不能借此跳过训练准入。

- 数据规划必须按原始资产台账→原版数量/分布→覆盖与准入审计→抽样配方→20K派生→训练的顺序交付。用户指定源即使需隔离仍保留原版路径及计数；禁止用候选配额代替库存，也不能让清洗结论覆盖源记录。

- 用户重发来源列表时先按完整repo_id去重，与JSON资产台账做集合差；明确原始链接数/唯一库数/新增数，不以文件名中的5500推断实际5469，也不因近名断言子集。

- 用户明确不需要俄语：原版台账保留RU/EN分布，所有派生训练版本排除俄语，连同reasoning/答案检查；原库总量不能充作英文可用量，过滤规则不冒称已执行。

## 2026-09-24 数据清洗与身份观测

- 用户强调谨慎严谨：适配器漏解析与原始结构损坏必须通过原字段证据区分，禁止编造tool名/参数/返回结果来凑训练量。
- 原版归档、结构候选、训练ready分别记录；跨源镜像/同源任务关联后再隔离heldout，val别名和冲突teacher字段都要覆盖。
- 数据处理改在Runpod，Mac只保留代码和小报告；大中间产物写入前预检空间。
- 用户关注MiMo名称残留而非完整品牌迁移：未暗示名称与诱导测试分开，模型自述不能证明训练数据内容、权重来源或来源不可识别。测试完成按用户要求回归数据主线，不无限扩展身份测试。

## 数据准入与环境复建

- 用户要求谨慎修复、质量验收：结构通过、README语言、row model声明不能代替语义质量、逐条语言或教师鉴真；不得自动给training_ready。
- 原始含thinking/缺reasoning都不能直接决定loss mask；逐模型模板验收独立执行。
- uv环境文件未成功lock/sync和回读之前，只能称重建草案；uv sync须显式绑定目标环境，不能创建A却安装到B。

- VERL SFT 的最小事实核对：原生入口是 `torchrun -m verl.trainer.sft_trainer`，FSDP 是 engine、SDPA/FlashAttention 是 attention backend；不能把后端、engine 和 trainer 混称。自定义启动器只应包住数据适配、workspace 和日志，不能掩盖监督 mask 尚未验收的事实。

## 2026-09-25：双卡 Blackwell 的 CUDA lane 隔离

- RunPod 页面显示的可用 CUDA 版本不是容器实际 toolkit；本次镜像实际是 Torch 2.8.0+cu128 / CUDA 12.8，而项目主 lane 仍是 Torch 2.11+cu130。必须使用独立 venv、freeze、`CUDA_HOME` 和 `UV_CACHE_DIR`，不能把新镜像当作自动解决版本匹配。
- `flash-attn` wheelhouse 只下载成功不等于 ABI 兼容；本组合的 wheel 曾出现 C++ undefined symbol。最终验收采用与 Torch/CUDA 对齐的源码构建，并要求 import、CUDA forward、双卡 FSDP smoke 三层证据。
- 原生扩展的 uv sdist 缓存必须按 lane 隔离；cu130 和 cu128 并发复用同一个 build 目录会把错误 ABI 带入另一 venv。脚本 `setup-performance-9b-sft-cu128.sh` 默认使用 `/workspace/.../cache/uv/performance-9b-sft-py312-cu128`。

## 2026-09-25：Qwen3.5 SFT adapter 必须完整渲染后按 offsets 做 mask

- Qwen3.5 的 chat template 会检查最后一个 user turn；对多轮轨迹逐消息渲染并拼接，不能假设 token prefix 稳定。出现 `chat template prefix is not token-prefix stable` 时，根因是 adapter 算法，不是训练器或 GPU。
- Qwen3.5 tokenizer 路径可能暴露 vision processor。把已经渲染的文本作为 processor 的位置参数，会被当作图片输入并触发 image decoder；文本 offsets 必须显式使用 tokenizer。
- 可复用实现是“完整渲染一次 → character offsets → assistant body mask”，并把纯 mask 逻辑放到无框架依赖的小模块中测试。pilot v3 证明该路径可以在双卡 FSDP 上真实 forward/backward、验证和保存 checkpoint。

## 2026-09-25：rl-insight logger 不等于 SFT trace 已采集

- 原生 `torchrun -m verl.trainer.sft_trainer` 若未初始化 Ray，会明确记录 `Ray is not initialized; monitoring is disabled`。即使 rl-insight server、logger 配置和端口都存在，也不能宣称 trace 已进入后端。
- 训练报告必须把 W&B、本地 `metrics.jsonl`、`train.log`、checkpoint 与 Ray/OTel trace 分开列证据；没有后端事件就标记“服务可用、trace 未验收”，不能用服务启动代替数据到达。
