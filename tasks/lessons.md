# 项目经验

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
