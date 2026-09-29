## 2026-09-29 18:16 UTC：R17 实际预检通过，双卡运行已启动

- R17 actual preflight exit0：273环境、CUDA未初始化、fresh三步/world2/two replicas、上下游容量2和唯一framework绑定通过；实际入口覆盖87.74%。公开prepared/runtime-preflight/actual-preflight-coverage均已落盘。
- driver370638与timeline370639于18:15:41UTC启动；supervisor370673，operator18:16:00UTC running，预算3474秒；controller108342、archiver108370。当前仅初始化，step/checkpoint与W&B未验收。
- runtime4a499cf不变；run/spec/manifest详前段。W&B目标mimo9b001661r17。recipe只读监控，review等待稳定checkpoint做双rankdelta，preparation等待batch/receipt+world2operator验收。审计使用已验证独立stage，因历史freeze未包含optimizer_delta.py，不改运行代码补文件。
- 待续：首次真实注册→两job实际同时running+两replica请求→三步及checkpoint→严格有效更新和W&B全history/RLInsight→所属资源归档清理。原19:16:41UTC截止、180秒reserve、保留Pod继续有效。

## 2026-09-29 18:13 UTC：R15 下游并发失败已修复，R17 预检中

- R15 未完成训练：worker 和 ledger 仍单任务，第二并发 HTTP409，step/checkpoint 均0；W&B最后API仍running/history0。所属controller/driver/archiver/Modal已确认清理，两GPU0MiB，Pod保留；r15-cleanup-final报告保留843 incomplete。
- R17 runtime4a499cfcf8e5fa361b20f009d2c1472e7b49dd73已push；938files freeze manifest SHA698a954da76230c18210ba52803c371f9ec5a027581f978f4191775085d7252f。RunSpec→worker→ledger严格容量2，真实HTTP两接受/第三拒绝回归；68tests覆盖86.50%，R17准备61+最终26tests，完整Ruff663files通过。
- 实际prepare18:12:53UTC exit0；spec sha256:cba3a3b4dfb5454b0533169588be1b4ef7b11aaedff01f3c1a7a5fb1ca07cf8c。controller108342于18:13:09启动，正确privatebin PATH，GPU端health healthy/unregistered。CPU-only实际preflight进行中，GPUdriver尚未启动。
- R17 fresh三步/save1，world2 actor+两TP1 replicas、sessions2/n4，原MiMo/DSH/32K/20480不变。R16草稿未提交、R15无C2，不能运行；R17 source不包含R16代码。
- 仍截止1790709401/19:16:41UTC，180秒清理；Pod不得停止。待实际preflight exit0→driver/timeline/archive→真实两job/replica→C1/C2/C3和W&B/Prom/Tempo。world2 checker和world2 acceptance已存在，若C1零moment优先C2→C3；不伪造单rank schema或恢复证明。

## 2026-09-29 17:36 UTC：r15 正式双卡重跑已启动

- 实际prepare/preflight均exit0，273依赖/fresh/world2/两replica/并发2通过；entrycoverage96.15%，public r15-prepared/runtime-preflight/actual-preflight-coverage。正确cloudflared PATH与真实HTTPS入口已验证，controller health通过。
- controller107570(CPU11621)、driver344153/supervisor344192/timeline344154(GPU11403)、archiver107586(CPU)。operator17:35:33UTC running/初始化，预算5906秒；尚无训练step/checkpoint，不能验收完成。
- 源码9a133cd、920文件manifest a659d70870756b37a8101303ced33cf2486a45439079ddbea1b364f33f186736固定。run/W&B分别mimo9b-001661-r15/mimo9b001661r15。所有private/shared日志沿r14路径替换r15；controller PATH=/root/mimo-private/bin:$PATH。
- 用户睡觉后要求继续完整跑通及真实W&B API核验。当前分工：recipe只读startup+W&B/Prom/Tempo；review等C1/C2完整后cloudCPU sharded_checkpoint_delta；preparation准备真实batch/receipt/grad与双rank证据组合。现有effective_update_audit仅single-rank，禁止将sharded证据伪造该schema。
- 仍截止19:16:41UTC，180秒清理，GPU Pod保留。r14失败证据与旧r12C4完整保留；不要修改运行freeze、共享uv或其他用户业务。

## 2026-09-29 17:28 UTC：r14控制器PATH失败，r15已修复冻结待启动

- 用户准备睡觉，明确要求自主完成全链路并真实W&B API确认。不能以running或初始化替代验收；继续到有效更新、checkpoint及指标对账或留下真实阻断证据。绝对截止仍19:16:41UTC/新加坡03:16:41，Pod保留。
- r14已失败exit1：双rank FSDP及两vLLM/初始naive同步成功，17:09进入warmup；17:10:41首次gateway注册时controller找不到cloudflared，supervisor按健康保护SIGTERM。完成step0/checkpoint0，W&B最后查仍running/history0，不人为改finished。
- 根因是root手动controller PATH误指共享root/bin；实际binary/root/mimo-private/bin/cloudflared。已核SHA77e26d8d900e0b8469f416239d14b5f296525fdf79fee6f511ef55609e3fbac2与version2026.9.3，并真实HTTPS nonce探针PASS且cleanup。controllermain已增加ssh/cloudflared failfast，27测试/82.81%覆盖率通过。
- r14controller/所属SSH/监听/archiver均结束，两GPU0MiB；worker尚未创建，无Modal训练任务。public r14-controller-failure与startup-termination保留。
- r15 runtime9a133cd已push，920文件manifest a659d70870756b37a8101303ced33cf2486a45439079ddbea1b364f33f186736；bundle audit-code/r15-preparation，52tests PASS。fresh双卡配置不变，ports38710–38713，W&Bmimo9b001661r15；actualprepare/preflight由separate_preparation执行中，root负责后续controller/driver，尚未启动r15GPU。
- 下次controller必须PATH=/root/mimo-private/bin:$PATH并核shutil.which解析到同一binary，再启动fixedpy/source-r15。严禁再用不存在的共享bin。r15driver通过MIMO_R15_MODE=fresh及SOURCE_COMMIT9a133cd，前置实际preflight exit0。

## 2026-09-29 16:52 UTC：r14 双卡 colocate 已启动，等待实测验收

- 实际prepare及CPU-only preflight均exit0：最终sessions2，273依赖通过，CUDA未初始化。预检实际入口coverage96.15%，无排除行；公共证据r14-prepared/runtime-preflight/actual-preflight-coverage。
- 冻结runtime c2f9d36，897文件manifest81c39e8870e1ccc8f9b8ff66625b5be4a64a30802ca2276cbe5d5c82e55049c1；独立双rank checker另随f9d0c68推送，不改冻结运行代码。
- run mimo9b-001661-r14，controller106972/driver328518/supervisor328544/timeline328519/archiver106988；16:51:58UTC operator running，仍初始化，不等于双卡训练验收通过。
- fresh固定SFT→2steps，actor world2+两TP1 replicas，sessions2/n4、32K/20480、native naive、W&B+RLInsight。旧C4保留，不做world1→world2直接恢复。
- 私有日志GPU launch-r14/train.log、supervised-r14*、gpu-timeline-r14.jsonl；共享runs/r14/operator/status.json。CPU controller-r14/archive-r14/evidence-r14。截止1790709401/19:16:41UTC不变，180秒清理，Pod不关闭。
- 下一步：核真实两rank/replica请求路由→n4组有效更新/C1/C2两rank文件→独立cloudCPU sharded_checkpoint_delta→W&B全history与Prom/Tempo对账→所属资源归档清理。不要把r12结果冒充r14结果。

## 2026-09-29 16:36 UTC：r13准入拒绝，最小修正转r14

- r13训练未启动。CPU prepare exit0；GPU-host CPU-only preflight因最终sessions=1退出1。根因旧prepare模板显式max_concurrent_sessions=1经launch.environment覆盖recipe2，不是GPU或依赖故障。失败报告已落evidence/r13-runtime-preflight-failure-20260929.json。
- r14实施同一用户授权双卡fresh方案；只修prepare参数2并断言输出，独立身份ports38700–38703。原r13freeze83dd8f7/e3cb358c、inputs和失败证据保留。当前R14代码/真实prepare回归正在测试，尚无R14freeze或GPU训练。
- 双GPU native naive IPC v2已4case PASS/188.63秒，源文件与operatorhash固定，清理后两GPU0MiB；无需为r14重复跑同一未改transport测试。
- r13模块unit覆盖率实际74.22%：helper99%、preflight28%，不能冒充80%以上。r14将对实际CPU-only preflight入口测量coverage，独立工具包不改273环境；此前全仓Ruff646文件通过、运行代码83dd8f7已push。

## 2026-09-29 16:17 UTC：用户已授权双卡 colocate，新r13准备中

- A5是用户错字，已明确忽略，不再等待该澄清。用户要求尽快双卡正常运行，并回查历史经验；按最新指定colocate_async落实。
- 历史核对：旧pipe-r1单卡4B/T2，旧双卡OPD为学生1卡+Teacher1卡，双卡SFT另一cu128 lane；MiMo r9单卡colocate、r10/r12双卡separate。未找到MiMo actor world2已验收事实，不能混同。
- r12全部验收报告已提交b09c2cd并push：有效更新与独立恢复passed，496/716 LoRA张量改变，760 base不变；W&B89指标对齐、真实Prom/Tempo通过。controller/archiver及所属Modal已清理，GPU Pod保留。
- 新r13设计docs同名mimo-dual-colocate-design.md：从固定原始MiMo9B fresh两步，actor world2共享两卡、TP1两个rollout replicas、native naive、n4/sessions2/max_num_seqs2。旧C4不改，不冒充跨rankresume。
- 任务分工：separate_recipe实现recipe/tests；separate_preparation实现r13freshoperator/preflight/tests；separate_review跑原生IPC两GPU×2case有界探针；root负责freeze/部署/启动/最终验收。当前还未启动r13训练。
- 最晚截止1790709401/19:16:41UTC/新加坡03:16:41保持，保留180秒清理，不自动关闭Pod。仅11403 GPU和11621 CPU；Mac轻量编辑/Git/SSH。

## 2026-09-29 15:28 UTC：r12已exit0，此前初始化状态已过期

- 真实终态：14:56:23UTC退出0，C4已保存；不是仍在初始化。GPU两卡0MiB，Pod保留、不自动关闭。
- W&B API已确认finished、完整history一行step4；grad0.1513671875、pg_loss -0.3034908869303763、reward mean0.5、lr1e-6。RL-Insight真实Prom回执passed，Tempo真实run trace已检出，最终公开审计待agent落盘。
- 耗时根因：启动至采样约25分钟（含trainer后standalone rollout/Gateway）；单步1258秒中gen1135秒占90.22%，更新60秒、保存23秒。原生logger仅整步结束后上报，产生长时间无指标窗口。详见docs同名r12-diagnosis-20260929.md。
- 本轮正在补model/optimizer/effective/resume验收及所属controller/Modal/archive清理；不得在报告返回前宣称这些已经通过。专项agent separate_preparation负责参数验收、separate_recipe负责W&B对账、separate_review负责观测与所属资源清理。
- 不改只读run-src-r12、不动共享uv/其他业务、不启动新付费训练。19:16:41UTC预算上限仍保留，但当前验收运行提前正常完成，预算上限不是要求持续跑满。

## 2026-09-29 14:11 UTC：r12 已启动，等待实际训练验收

- 当前运行：mimo9b-001661-r12，controller105384、driver296871、supervisor296872、archiver105400；controller健康及spec身份已校验，尚在初始化。
- source29c0cf7，859文件manifest f085c12...；r12真实preflight exit0（SHAf5c658dc...），C3→4；W&B预期xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/mimo9b001661r12。W&B只在fit之后创建，初始化期无run不是学习失败证据。
- 日志：GPU /root/mimo-private/launch-r12/train.log、supervised-r12*、ray-r12/ray/session_latest/logs；shared runs/r12/operator/status.json；CPU controller-r12与evidence-r12。
- 待验收：真实C3恢复、两卡资源映射、消费policy v3、step4有效更新/C4；原生W&B完整history与console一致、RL-Insight实际metrics/trace。不要拿synthetic probe或r10结果替代。
- 截止仍19:16:41UTC/翌日03:16:41新加坡，GPU服务器不自动关闭；结束后只清理所属进程/沙盒并保留Pod。

## 2026-09-29 14:02 UTC：r11 启动失败已修复，r12 冻结完成

- 当前不能称r11正常训练：13:44:57UTC exit1，Hydra向只读source写outputs触发PermissionError；Ray/模型/新checkpoint/W&B均未开始。controller104848与archiver104864已清理，0worker jobs，GPU服务器保留。
- 修复：显式private launch/hydra输出；90云端回归和真实0555 cwd入口验证通过。RL-Insight Hub保留修复已通过真实CPU Ray/Prom/Tempo synthetic probe；该探针不是训练。
- 最新已推送commit `29c0cf73502fdd6d7778f5abfeb0f6eed84d6a49`，Ruff双门禁639文件通过。r12新frozen source859文件，manifest `f085c12d986513c76427ace010db1cfd2b70f33a1fb7e096d9bee258430666a0`。
- r12：`run-src-r12` / `audit-code/r12-preparation`，ports38680–38683，W&B ID `mimo9b001661r12`；仍r10 C3→绝对step4。当前正在CPU prepare/preflight，尚未启动controller/GPU。
- 现行deadline仍1790709401 /19:16:41UTC /翌日03:16:41新加坡；不因失败重计，不自动关闭Pod。下一步先核真实preflight exit0和hash再启动，随后原生W&B/Prom/Tempo/参数更新对账。

## 2026-09-29 13:08 UTC 用户授权更新：继续六小时，保留GPU服务器

用户已明确追加六小时。**现行固定截止1790709401 / 19:16:41UTC / 翌日03:16:41新加坡**；替代下文旧截止，不改旧运行证据。不自动关闭或删除Runpod Pod。r11 C3→C4使用新`audit-code/r11-preparation-v2`，旧v1 stage及13:03准入拒绝记录保留。controller仍有21600秒per-run上限，最早13:16:41UTC可启动；重启不延后新绝对截止。

当前已完成observed recipe/唯一实验名/原生终态指标等待；云端recipe+launcher90项、v2准备32项、观测helper21项测试通过。正在验证真实CPU Ray/Prometheus/Tempo通路，尚不能称r11训练或W&B history验收完成。下一步：commit+source freeze→真实tokenizer/恢复/依赖预检→启动双卡r11→API原始指标对账。

## 2026-09-29 12:13 UTC：r10 已验收，推进原生观测 r11

- TL;DR：r10 separate_async 双卡从 r9 C2 独立恢复至 C3，batch/model/optimizer/effective 四项检查 exit0。W&B API 确认该轮只有 console，观测尚未验收；当前在实现 r11 原生 W&B + RL-Insight。
- 交付物：`docs/verl-uni-agent-harbor-opd-rl/evidence/r10-acceptance-20260929.json`（347行）、`evidence/wandb-audit-20260929.json`（83行）、`mimo-observability-design.md`（46行）、`evidence/r10-cleanup-20260929.json`（清理小报告）。前三项随 c04cc99 已推送。
- 真实行为：r10 奖励 [0,1,1,1]，grad 0.1484375，493/716 LoRA 张量改变、760 base 不变；AdamW step2→3，992 moment 张量变化。4条消费轨迹皆policy v2。一次已捕获qwen3_coder解析ValueError未中断整轮，原日志保留。该单任务无heldout提升结论。
- 清理：controller103207、archiver103275已停；61归档文件逐hash/权限核对通过，118份worker文件另留私有目录；4成功+1取消prefetch。10个所属Modal sandbox实时poll137（显式终止），两GPU0MiB。Pod仍保留并计费。
- 设计约束：deadline仍1790687801 /13:16:41UTC，不得因r11重计。固定uv273项、独立CuPyoverlay与原生NCCL不变；不改r10冻结字节、不在Mac跑训练或测试。
- 下一里程碑：[ ] 独立r11 C3→C4原生logger；[ ] API逐指标对账；[ ] Prometheus与Tempo真实实验记录；[ ] 截止前归档清理。
- 分支/部署：同名分支，当前审计文档commit c04cc99已push；r11尚未启动，监控服务复用现有18080/9090/3200，不重启共享服务。
- 冷启动：先读本段及observability design→查agent最新代码/测试→核绝对时间与source manifest→读云端r11实际状态再行动；不得把r10通过与观测通过混为一谈。

## 2026-09-29 11:06 UTC 当前入口：r10 separate_async 独立恢复已启动

用户明确选择 separate_async，源码 aaae616 已 push。r9 两步 exit0、C2完整：第二组奖励[1,1,0,0]、grad0.1328125、adv±0.866、248个LoRA张量改变、760个base不变；C1 moments全零导致保守optimizer delta失败，C2独立有限/非零，整体验收仍未完成。读最新notes及evidence/r9-completion-20260929.json。

r10来源run-src-r10冻结796文件，manifest SHA8837215143bf7c725556d75a2dc030ae51054b67ed6966b3a2500dd93d0e8afa；固定273依赖不变，独立CuPy14.0.1 overlay。真实双GPU NCCL两种重建模式/各三版本全通过，实际CPU预检exit0。新run mimo9b-001661-r10从r9 C2→absolute3，actor1卡+standalone1卡、sync1、32K/20480保持。GPU driver264705/supervisor264718；CPU controller103207/archiver103275。11:05:57UTC快照operator running，GPU尚0MiB（初始化），必须实时核验，不得仅据配置宣称双卡模型已运行。

绝对截止仍1790687801=13:16:41UTC/新加坡21:16:41；不重计五小时，Pod保留计费。只用11403 GPU、11621 CPU；不要动213.192.2.76。冷启动先读同名docs/mimo-separate-async-design.md，再核runs/r10/operator/status.json、private launch-r10/train.log及controller/归档健康。下一验收：真实恢复日志、首组版本2、step3消费/梯度/参数/optimizer/保存；尚不能mark goal complete。

Modal清理已按用户纠偏扩展：累计132个旧App停止，Live Apps158→26；剩余14函数服务+11近期+当前r10依赖的__harbor__，实查活动Sandbox为0。截图点名三个旧App及verl-harbor/verl-eval均已停。读evidence/modal-cleanup-expanded-20260929.json；不再要求名称含日期。以下r9运行中及更早条目均为历史。

## 2026-09-29 09:06 UTC 当前入口：r9运行中，五小时绝对截止已部署

先读notes.md最新r9段和docs同名evidence/r9-launch-20260929.json。用户要求的截止为13:16:41UTC / 新加坡21:16:41，按08:16:41请求起算五小时，重启不顺延；训练预留180秒清理，实例保留计费。r8四条奖励[0,1,1,0]，在dense entropy OOM退出，零checkpoint。3e0e55d修复已push，r9新身份fresh两步/GPU0/32K，774文件+273依赖+实际tokenizer/IPC预检通过。GPU driver213662/supervisor213663，CPU controller101484/archiver101513。必须实时核状态；尚未完成更新/checkpoint/独立resume验收，真正C2续训改用r10。旧r8及以下状态为历史。

## 2026-09-28 最新 MiMo + DSH 9B RL 实施入口

### TL;DR
- 用户已批准真实推进并于11:14UTC明确激活goal：MiMo Code小样本 → 固定DSH → Harbor/Modal → Uni-Agent/TQ → Runpod VERL 9B有效RL更新、保存及独立重载续训；DSH-first，terminus-2后续加入同一policy。
- 当前worktree/分支均为verl-uni-agent-harbor-opd-rl，upstream/@{push}同名；HEAD至少4c572c6；后端修复、uv273约束一致、MiMo预检/IPC证据已提交，未push。
- **不增加Mac计算负担**：已停止本地Docker pull；镜像构建/CPU测试/数据处理均云端，Mac只编辑与调度。
- 全2698条Code转换合同审计、派生镜像构建/冷拉取、HTTPS及真实tokenizer预检通过；r4真实DSH已有18/21轮生成及19/22工具调用，但上下文截断且verifier入口缺失，零有效reward/更新。
- r4已终止并归档：3jobs取消、5Modal停止，GPU12:52:38提前删除确认，无checkpoint。Harbor注入修复96回归+native0/1校准已过；32K配置52回归+实际MiMo预检通过。下一fresh GPU运行仍待有效更新+独立reload。

### 本轮交付物
- docs/verl-uni-agent-harbor-opd-rl/mimo-dsh-integration-design.md：批准设计、API、架构与分阶段验收。
- docs/verl-uni-agent-harbor-opd-rl/mimo-dsh-integration-evidence.json、mimo-code-full-contract-audit.json：来源固定与2698行远端审计。
- examples/mimo_dsh_rl/{prepare_tasks,verifier}.py：任务转换与原始测试语义，traditional/binary/arbitrary-prefix边界已修；2698条均通过解析。
- deployment/harbor/mimo/：固定DSH lock、离线context、安装、回读binding、Modal VM CPU builder。
- uni_agent/tasks/harbor_dsh/mimo*.py及既有executor/task/registration/trajectory/isolated_trial增量：独立verifier与完整workspace快照。
- 修复核心isolated_trial.py现482行、新test_mimo_verifier_injection.py143行、原生Modal probe161行；32K recipe及回归、失败/清理/预算证据见同名docs目录。其余对应tests/uni_agent/{examples,deployment,tasks}/test_mimo*.py。

### 设计约束
- 复用已有DSH/VERL闭环，不重造harness/trainer。DSH源码b2369692ea530007075ebcd18d39fdba0bbd3982，SDK/runtime0.1.3a2，profile=sdk-minimal，无T2 patch，固定全部wheel/binary摘要。
- 数据revision639865fd3374018d6cb29b9fb82dd531406fcf5f；2698 Code，全部真实镜像映射。原测试patch、command和cwd保持。
- 隐藏测试只交独立verifier；可信base_ref必须在agent前捕获。保留untracked/deleted/binary/permissions/safe symlinks，不交.git。
- 不停止/挤占现有GPU业务；首轮单任务固定worker、sessions串行。工程同题评估不冒充heldout提升。

### 已踩坑 / 真实行为
- 全量审计发现000989合法traditional unified diff，002333/000547含binary patch；修复解析后才放行转换。
- 当前11403/11621/16358的GPU均有其他业务；Runpod API显示闲置不可采信，以nvidia-smi为准。
- 固定GitHubRelease/PyPI的7wheel与portable Python全部远端下载且hash通过。私有派生镜像ghcr.io/cryptosun2049/mimo-dsh-code-001661@sha256:15f588d627ce06e17d2904193c07100aa0b73c883269d70565ab59f36f6f2952已验证；4个Modal构建/验收VM均终止。
- 首题format-code-task-001661原图含base ancestry外可达commit；官方源码也要求history检查。不能仅删calibration断言，production与calibration必须同策略。
- MiMo9B实际qwen3_5架构/特殊模板，需要qwen3_coder工具parser；普通Qwen builder额外换行和reasoning丢失已由真实tokenizer测试复现。旧qwen3_4b wrapper不能使用。

### 下一里程碑
- [x] 完成binary/traditional patch修复、全量重新审计。
- [x] Modal VM真实Docker探针，原镜像+固定DSH派生层、私有GHCR回读及Modal私有拉取。
- [ ] DSH模型工具已实测；修复独立verifier入口注入和16K上下文截断后，新身份重跑完整轨迹准入。
- [ ] Runpod专用GPU有界GRPO、保存/参数差异/独立reload/续训。
- [ ] 独立任务同预算评估；节点commit、质量门、完整交接。

### 分支 / 部署状态
- 原旧同名分支归档archive/verl-uni-agent-harbor-opd-rl-20260928-2a3f595；performance-9b远端保留，无强推/删除。
- 已提交7e48aaa、cc372a3、67a5948、0f4f6f2、4c572c6；当前verifier/32K修复与r4终态证据待提交。预存脏文件和嵌套OpenCompass独立仓不得混入。
- 全仓Ruff此前被嵌套OpenCompass的9项lint/2文件format阻断，尚未通过push门禁；不得绕过。
- 远端CPU工作根/workspace/mimo-dsh-rl-20260928；SSH root@157.157.221.177:11621。Python为/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin/python。凭据只在/root/mimo-private/，不打印/提交。
- 原专属GPU pbpxdvlt9uruc8于11:24:54UTC提前deleted_confirmed（原期限11:38UTC保持且未延长）；旧SSH58129失效，估计GPU约$3.70非账单。证据evidence/mimo-first-gpu-cleanup.json；checkpoint没有产生，模型/源码/失败日志均留网络卷。勿动其他GPU。
- r4 GPU gqgtsz3pfov6tl已12:52:38UTC提前删除（204/get404/list absence），SSH51176失效；driver995/supervisor996已退出，controller80823停止，5Modal全部停。估计GPU窗口$1.94非账单。watchdog78224及archive83278/83279已停；原13:26:54deadline未改。
- 网络卷runs/r4/operator已存终态/脱敏log；CPU/root/mimo-private/evidence-r4保存launch/registration、3failed requests及37份未准入证据，0receipts。真实IPC首跑180sec超时、retry 1passed/203.53s；诊断probe曾core原因未立，保留全部失败。
- 专属HTTPS https://mimo9b-rl.xdan.work，tunnel04729718-cb6b-40bd-ab74-72967ce77abf；r1/r2/r3 controller均已SIGINT停止，均未注册模型/创建worker任务。r3 task hash603c1f65...、spec49928dfa...保留审计；新窗口必须新Pod/SSH/spec/凭据/运行身份。
- run-src-r4冻结不修改；修复在integration-check/source-v2进行CPU/Modal验证。下一GPU须新身份及固定新源码；模型/venv沿用持久卷。r4没有C2，mimo-r5-resume-wrapper仅草稿不可用于fresh retry。
- 续训必须新run/controller/Ray/session；当前TQ0.1.9.dev0无snapshot API，不会原生恢复旧队列。按同一步消费uid回查receipt、reward差异、advantage两端、有限非零grad及C1→C2/C2→C3参数差异；旧MECHANICS_ONLY不能验收有效更新。

### 冷启动 checklist
1. 先读本段、tasks/lessons.md和mimo-dsh-integration-design.md；下方SFT内容为独立历史主线。
2. 核git status/branch/upstream，保持现有脏文件；核三agent当前状态防重复覆盖。
3. 先核专属GPU lease/watchdog、controller和agent最新状态，保全网络卷工件；不能凭本段“运行中”推断成功。
4. 读取最新审计/测试证据，然后继续M1；全部计算留在云端。

## 2026-09-25 CPU 质量审计修订

- CPU 端口16358，quality-audit-v2 PID982791启动；须检查进程及终态manifest，不凭本行假设仍运行。
- quality-gate-v1错误放行16732条已撤销；manifest INVALIDATED_DO_NOT_TRAIN，approved_rows=0，原结果保留诊断，未训练。
- v2只回填/诊断，不授予training_ready；见docs/performance-9b/data-quality-audit-v2.md。后续需修正next-action工具前缀误报并完成语义、语言、污染、mask验收。

## Fable恢复后台已完成

- collection-v1 succeeded：70文件501430864字节，原版留Runpod；小报告`docs/performance-9b/fable-recovery-v1/`。
- PremiumV1 6365行含591Fable/5705unknown/69其他Opus；train仅526Fable声明，val33/test32不可用于训练。V2全标Fable不能继承。
- V2 base_v1 5381行source_row_hash与当前固定V1无匹配，未恢复逐行教师或split，保持隔离；下一步查哈希算法/历史revision/完整内容匹配。
- Armand18370事件行（63文件）、7431处Fable模型声明；Teich244行无model字段。数量不是独立任务或准入数量。

## 数据字段契约已保存（权威入口）

- 用户要求确定并保存columns设计；文档`docs/performance-9b/统一训练数据字段契约-v1.md`及`.columns.json`已落盘。
- apus-sft-v1固定27列，messages/tool_calls/supervision固定子结构；tools_json和function.arguments物理存为严格JSON字符串，校验时解析对象；thinking独立字段。
- 原版不改；中立母本保留完整审计；训练视图由固定任务manifest导出。数据schema与apus-chat-v1协议分离，不在母本自动注入品牌system。
- 当前仅字段设计冻结；screened-v2未完成schema迁移、HF回读、mask与tokenizer验收，不得称正式母本或training_ready。

## 当前后台任务：Fable证据恢复

- Runpod `/workspace/apus-data-cleaning/recovery/collection-v1/manifest.json` 查看status/current_file；日志`collection-v1.log`，脚本`collect-recovery.py`。禁止重复并发启动。
- 固定inventory下PremiumV1三split单一Parquet、Armand/Teich原始JSONL，只归档与schema/model声明审计，无训练准入。
- 下载上限2GiB，本轮约500MB。17项回归通过；不同inventory复用目录在任何写入前拒绝，原始文件SHA核验。
- 下一步先取终态manifest与audits小报告，Mac不取原版大数据。HF额度仍未解决，不能称已发布。

## 最新：身份测试结束，回归数据主线

- 用户明确不再扩展身份测试，回到数据处理。MiMo9B已下载Runpod并完成88身份请求/2工具请求；原始结果在docs/performance-9b/mimo-identity-test。未在输入暗示MiMo的54请求没有MiMo/小米输出，但不能证明训练数据无该名称或衍生来源不可识别。
- 测试vLLM服务1059369已发SIGTERM释放GPU；权重保留。启动需VLLM_USE_FLASHINFER_SAMPLER=0避免CUDA12.8/SM12.x采样JIT失败。不要因此改共享训练环境。
- 数据v2已SUCCEEDED；293074行输入，62030结构候选，26757关联组件。候选无Fable，不能启动原定20K；各来源原因与报告见screened-v2-evidence。
- 下步恢复Premium来源：base_v1 5381/crownelius59先追原始证据；manusagents79560教师混合继续隔离。Krazy1000仅54提示、调用字段缺失，不是模板问题，不能猜测修复。
- 开始在Runpod恢复源inventory（premiumV1、已有清单Armand/Teich），不在Mac下载大数据。

## 最新：Runpod 后台处理脚本

- 入口 `examples/performance_9b/background.py`，操作文档 `docs/performance-9b/后台数据处理操作.md`。
- 当前运行 `/workspace/apus-data-cleaning/reports/screened-v2-background`；用 background status 查询，勿启动重复运行。冻结代码、配置、SHA；10秒心跳、失败留证、不自动训练/上传。
- v2 已修复 val 划分漏检、同层teacher/model冲突遮蔽、孤立tool结果、同源任务及跨源相同prompt联结。v1只保留诊断，不用于最终统计。
- 84项回归通过，全仓ruff双门通过。当前并不代表20K或训练ready。

## 最新：Mac 清理与 Runpod 原始数据副本

- 设计已获用户“开始处理数据/好的开展起来”批准；当前先归档，训练适配后做。不要沿用下面历史“未批准”状态。
- 本轮清理失败处理产物约8.04GB，另删除3个无打开文件的可重建HF Arrow缓存约3.69GB；uv缓存39GiB因占用锁超时未清理，未强制删除。
- 原版8库17文件共3,992,734,383字节已复制至Runpod `/workspace/apus-data-cleaning/apus-source-archive-v1`，逐文件大小/SHA256全部核验一致。本机原版仍保留。
- HF私有归档上传失败：403 Private repository storage limit reached。不能称已上传或擅自转公开；待解决额度后从远端续传。
- 证据：`docs/performance-9b/mac-cleanup-and-remote-archive.json`、`source-archive-upload-manifest.json`。
- 处理器76项测试通过，仍未提交；第一次本机全量处理磁盘满，失败输出已清理，无有效20K版本/训练。后续在Runpod CPU上继续处理，勿回Mac生成大中间文件。

## 双框架数据适配设计

已核ms-swift官方messages/Agent roles/loss字段和本地VERL源码，新增docs/performance-9b/ms-swift-verl数据适配方案.md。统一母本后两导出，不重复清洗；当前VERL需custom_cls支持target_message_index。尚未实现。用户已明确确认“从CodeFlame数据中去掉Gemini3.1”，不存在取消限制；未知/冲突来源隔离。

## 最新语言约束：排除俄语

所有派生训练版本排除俄语；HelioAI原版5,469 RU+EN仍登记，英文子集数量未知。检查prompt/reasoning/answer，不改写俄语冒充原始英文。文档/JSON规则已更新，尚未执行语言过滤。

## 来源补漏完成：15个原始库

用户重列11个链接，去重7库，旧台账覆盖5库；新增HelioAI/Claude-Fable-5-5500x（卡片5469、license unknown）和KrazyKitty/Fable-5.1-Max-Reasoning-Filtered-1000x（卡片1000、与MoreThought重叠待核）。原始台账MD/JSON及分布/索引已更新至15唯一库；新增两库仅README和元数据，未下载正文，未改20K配额。

## 最新交付顺序：原始台账先于抽样

用户要求先完整登记所有原版路径、各库分布/数量，再规划抽取，最后20K训练。已建docs/performance-9b/原始数据资产清单.md及JSON，共13唯一仓库（近期指定5+原方案8），原版声明与实测分开。project-index已按此排序。五个近期库主训练文件下载完成，其他8库本轮仅刷新固定README/API，不误称全量落盘。QwenAgent下载24910已成功结束。四库审计JSON与能力缺口表齐备；尚未实现正式清洗/上传/训练。

## 20K目标与真实供给对比已完成

权威规划docs/performance-9b/20k数据规划与能力缺口.md：建议7K代码/3K推理数学/3K办公/2.5K数据/1.5K翻译/1.5K写作/1.5K通用。是建议目标非ready数量。新增QwenAgent固定rev fbe918e...；下载session24910需核。四库实际审计JSON已完成：Fable5.1工具名/参数损坏，Superior污染1587test，CodeFlame90K未知身份，Premium混合来源却统一Fable标签。不能按原始卡片总量启动训练。设计批准和20K选全池/三教师池两问题仍待答复。

## 当前主线：完整数据、三教师子版与20K SFT

用户要求完整清洗/20K抽样/上传HF并训练；追加仅Qwen3.8+Fable+GPT5.6子版。设计在docs/performance-9b/sft20k-execution-design.md，AGENTS Human Gate明确批准尚待答复；20K从全池或子版抽样也已提问。尚未实现处理器、上传或训练。HF账号已核gump2049，沿用私有。当前两卡空闲，MiMo权重缺；VERL默认全assistant监督，必须适配target_message_index。

下载暂存/private/tmp/apus-sft20k/raw/。Superior固定版已完整扫描9640行（math6212/reasoning2151/code1277），证据sft20k-source-audit.json，只做结构检查非ready。Fable51/Premium/CodeFlame完整下载已完成（Premium为85K train parquet），均在同一raw目录。分布与准入证据正汇总至数据集能力分布清单.md及各sft20k-*-audit.json。不要覆盖现有未提交分析脚本变更。

## 数据清单v3.3：CodeFlame排除Gemini 3.1

用户要求独立处理CodeFlame，排除Gemini 3.1系列；未知/冲突来源隔离，跨前缀与轨迹组防回流。最终清单M1已写验收规则，尚未执行全量过滤。后续必须报告过滤后任务/教师/token分布，不能沿用原库190K当可用量。

## 数据清单v3.2补充

新增用户指定CodeFlame/SuperFusion聚合入口（卡片称190K/GPT5.6约50K），逐教师/原始来源筛选，未全量审计。详见最终清单M1；1K配额未暗增，通用保留仍限定Fable/GPT5.6。

## 数据清单v3.1补充

用户指定Fable-5.1-Filtered-5000x、SuperiorThoughts-1及Premium V2，已补入`docs/performance-9b/最终训练数据清单.md`。前两份明确要用；Fable优先既有160池，SuperiorThoughts扩展配额待审计冻结；Premium混合教师逐条筛选。仅卡片/元数据核验，未全量下载或训练。

# 全版本 checkpoint 评测交接

## 2026-09-24 当前最终清单v3

- 唯一配方权威docs/performance-9b/最终训练数据清单.md，原v1/v2降为历史。
- 用户要求通用保留也只用Fable/GPT5.6：80条改Fable20/GPT60；Cascade/Math/Science当前配额0。
- train1000领域不变：400/160/140/120/100/80。现成520+新生480；新生含保留80，实际来源不足保留缺口，未ready。
- 文档、HTML和索引已统一引用最终清单；当前没有新训练或批量生成。


## 2026-09-24 当前配方v2：强教师核心

- 用户明确Fable+GPT5.6为核心。权威入口docs/performance-9b/agent-sft-data-plan-v2.md。1000目标=代码/终端强教师400（GPT240/Fable160）+办公160+数据140+翻译120+写作100+保留80。
- 600现成示范+400新生产；core400仍待完整文件准入，不保证Fable160已存在。旧v1.1降为历史，不能混用440/560数字。
- 任务数/前缀行/loss token区分；whole-trajectory与next-action监督独立；建议首轮分层混训，阶段训练另设对照。
- 明确代价：代码从20%增至40%，须监测目标工作能力是否受挤压。dev100/sealed200相应分配，总规划仍1400独立任务。


## 2026-09-24 强教师配方修订

- 用户指出Fable/GPT基础示范不足；strong-teacher-sft-review.md核对画像冲突、官方卡、切片及GPT6搜索。
- 1K领域总配额不变；代码200改GPT5.6=100、Fable原始/独立池=60、OpenSWE=20、新生=20。现成440+新生560；均目标非ready。
- GPT5.6累积前缀仅监督最后assistant；Fable镜像model_attested必须实筛，当前切片不能证明合格子池存在。原始Fable无明文CoT不等于不可做动作SFT。
- GPT6搜索返回4个候选，暂无可直接纳入的通用Agent母本；优先规划真实自生产，不把评测答案当训练。


## 2026-09-24 文档目录统一与数据配方

- 用户要求文档统一到docs/performance-9b/；整个旧文档树已迁移，内部相对结构保留。worktree与tasks目录名不变。历史JSON原始运行路径保留为证据，不当新执行入口。
- 当前数据权威agent-sft-data-plan-v1.md：1000独立训练目标，代码200/办公200/数据200/翻译150/写作150/保留100。420现成SFT+80开源环境新生+500自有新生=1000；未构建ready。
- 校准100（含20）+train1000+dev100+sealed200=1400独立任务规划。Curator编排，Uni-Agent真实执行，verifier+独立rubric验收。
- 模板专项独立；未启动新训练或付费生成。未提交外来物料随目录保留，勿混入本次提交。


## 2026-09-24 主线收敛：数据生产与20种子

- 用户确认tool-call自有格式后续按独立小实验执行，不阻塞数据主线。
- agent-sft-seed20-plan.md列办公/数据处理/翻译/写作/代码各4题，输入→工件→grader负例；三档数据准入、20→100→1K门禁。当前规格不是fixture或真实轨迹。
- 先O01/D01/T01/W01/C01五锚点建设；教师API与硬费用上限待核，未发起付费执行。
- apus-chat-v1-tool-call.md已形成完整专项；本轮文档整合待校验/提交。


## 2026-09-24 APUS Tool Call专项

- 新权威文档docs/performance-9b/apus-chat-v1-tool-call.md，覆盖数据/API/token三层、MiMo/Qwen差异、ID/参数/流式、mask、迁移实验及验收。已接项目索引与MiMo HTML。
- 当前仅文档；尚未实现模板/parser或启动训练。v1建议先E1外部适配，保持MiMo模型可见序列；多调用/并行/多模态不自动放行。
- 下一步冻结支持范围和golden样例，再真实对照；上游模型来源保留。


## 2026-09-24 Agent SFT 数据与协议方案更新

- MiMo HTML扩至18章，增加用户数据画像准入、GPT6-sol候选教师真实执行、Curator工具选型、Qwen/Apus协议迁移和多harness受控实验。
- 新agent-sft-data-production-design.md保存架构/文件范围/接口/测试计划；portrait-audit.json为画像与目录抽查证据。
- 画像内嵌81本地条目/354HF候选，扫描2026-06-20，非当前ready库存。部分目录只有README，小样不等于全量。
- 后续用户已确认继承MiMo权重，名称apus-chat-v1；HTML #apus-chat-v1为最新草案，优先保留原生序列化+API适配。当前会话gpt6-sol标签不等于已配置批量API，provider/计费与额度待实查。
- Agentic-v2部分模拟环境，不计真实工具成功；画像多处静态SFT标on-policy OPD不予继承。保留原始报告不改写。
- 未下载新权重、未启动付费数据生成或训练；下一步是按设计合同做接口/数据准入小试点。


## 2026-09-24 MiMo Agent SFT 9B 专题

- 新报告 docs/performance-9b/mimo-agent-sft-9b-report.html，14章：SFT起点/数据/mask原理/轨迹/数据工厂/分域GRPO/多harness/复现边界/两卡路线。已接产线HTML与索引。
- 固定HF revision 2367e865d009c13ac81713a2878291d33ab28177；模型卡、元数据、PDF33–36页摘录及hash位于mimo-agent-sft-evidence/。
- 结论：监督SFT蒸馏不是OPD；公开权重不是表6各域RL模型。完整SFT超参与语料未核验，不能声称精确复现。
- 远端检查时两卡0MiB/0%，MiMo权重未下载；旧evaluate.py强制thinking-off、默认原版tokenizer且无工具，不能直接作为新Agent选型评测。下一步须冻结原生模板/工具/预算合同再运行对照。


## 2026-09-24 日常工作Agent目标与双线推进

- 用户收敛目标：接近Opus4.6日常工作/Agent能力，OPD有效性验证为主线，同时规划mid-training数据。
- 新设计与实测审计：docs/performance-9b/daily-agent-capability-plan.md；新HTML顶部已链接。
- 旧30题仅14条可评分、无工具；teacher只多过一条关键词，代码min_Jumps样本存在题面示例冲突，不可据语法通过宣称教师功能优势。
- Qwen卡片部分Opus比较非同口径；新100个工作任务规格为待构建开发诊断，非已完成评测。1K文本配额不冒充Agent课程。
- midtraining历史123GB画像不是当前可读库存：主要是小样；先核验来源/完整性/许可/token，再依能力缺口配方。
- 本次只读GPU时两卡0MiB/0%，未启动新训练/付费Opus/沙箱。下一步数据/评分与画像、控制门；不要因卡空闲跳过准入。


## 2026-09-24 独立产线HTML入口

- 用户批准独立于MiMo研究报告建立我们自己的科学训练产线。新唯一入口：docs/performance-9b/training-production.html。
- 双维导航：产线架构 / 阶段目标；研究来源辅助入口。Curator、Teich、Verifier、观测控制与OPD/MOPD/规模化RL专项均写明职责、状态和验收。
- 原MiMo HTML未修改，architecture.html保留历史并链接新入口。详细总纲与1K合同仍为权威设计，HTML不代替原始证据。
- 本轮仅文档/导航，无训练或infra部署；1000条尚未ready、云观测与质量止损仍待验收。
- 文件：training-production.html（16节）、production-portal-design.md；索引/总纲/历史架构/记忆同步。后续继续数据与grader、事件与控制建设。


## 2026-09-24 当前主任务：科学训练产线与1000条pilot

- 用户已确认：建立完整专业可观测、可分析、可诊断修复的大模型训练产线，1000条多领域单教师OPD为首个受控实验；长期MOPD目标保留。
- 先读 docs/performance-9b/project-index.md → training-production-charter.md → training-pilot-1k-plan.md；HTML唯一导航为training-production.html。
- 当前仅设计/盘点/项目记忆索引已更新；1000条未构建、未启动新训练。原始源足够多，但代码120条、科学旧40审计仅4保留、聊天头部240行均不能直接扩成高质量1000。
- 现有原生文本OPD链路已验收；不能说Uni-Agent/Harbor工具路线、W&B云端与真实verl-insight后端、质量止损已全部接通。按P0合同/评分→观测/控制真实验收→有界pilot推进。
- 最新新文档/已有修改位于既有performance-9b worktree，保留之前未提交变更；勿stash/reset或把旧纯RL提案作为本轮启动依据。

## 2026-09-24 夜间单教师 OPD（已完成验收证据）

- **完整测试执行完成，非全门禁通过**：统一入口 `overnight/index.html`，结论 `tokenizer-opd-compatibility/full-verdict.md`、机器门禁 `full-acceptance.json`。当前thinking-off文本OPD链路通过；thinking1024单例未闭合，原mode driver exit1保留，禁止称全部适配。
- 真实训练runs/opd-live-acceptance-20260924 exit0；2microbatch/8条/4455token，独立loss和grad误差0、mask外0、teacher ID错位0、coverage pass。248文本LoRA全部非零B，110视觉零B；导出/独立30题重载SHA一致，infra0。评分math4/5、IF5/8、knowledge1/1，code/chat未计正确率。
- 17案例9模式+8现场，6091response token；HF/vLLM mean0.00825642、P950.06524849、parser全通过。实际live teacher vsHF8/8通过，weightedmean0.00907492。工具原生mask5控制通过但生成传输mock。
- thinking2048独立诊断exit0，1751token闭合、正确391，原1024前缀完全重现；不替换原fail，新增尾部未评分。HF默认EOS248044/endoftext，而live VERL正常EOS248046/im_end；forced评分可比，不宣称生成停止等价。
- 本轮无需继续GPU作业；未启动扩量训练。后续是统一停止配置、合格数据扩量/固定验证/封存测试/代码聊天评分；不将兼容通过当高性能证明。W&B仍offline。




- 深度兼容验收完成：driver1037003 exit0，GPU释放。2736响应token五域文本重放+EOS，HF/vLLM mean0.008197/P950.064773，原生parser IDs全对齐。真实概率loss误差2.78e-17、grad4.34e-19；四组边界控制通过。证据deep-evidence/，结论deep-verdict.md，已整合overnight报告。只支持当前文本单轮关闭thinking；历史原始张量未保存，不能声称精确重建。新扩量训练尚未启动，用户允许考虑扩量，优先补合格数据/评分和固定验证。

- 后续新请求：用户要求进一步确认适配、定位VERL源码，并允许考虑数据不足时扩大训练。当前先做深度验收，不重复原122条冒充扩量。远端runs/opd-deep-audit-20260924，driver1037003；CPU实际loss独立损失/梯度/边界控制通过，HF五域文本重放+EOS已完成，vLLM对照运行中。原训练没存逐token张量，重放不是历史精确重建。文档tokenizer-opd-compatibility/deep-source-audit.md、deep-design.md。待结果完成后再定扩量与验证集。

- **最终：19:06:59 UTC全部队列完成，driver979002已退出。** 正式16步、四ckpt导出、五adapter独立重载均成功；7版本×30题=210输出，infra0。最终step16 math5/5（base4/5），IF5/8、knowledge1/1不变；仅幂塔题4037token内输出boxed0352改善，不能外推全面收益。
- **最终入口**：docs/performance-9b/overnight/index.html。final-analysis.json置顶结论；final-evaluation-audit.json逐条身份/重评分；final-weight-audit.json实际远端权重SHA与导出及eval一致；training-completion-audit.json全16步有限loss/grad；sampling-audit.json128轨迹覆盖121样本。最终summarize已显式重跑，medians与reload关联已更新。
- **页面验收**：桌面1280×720截图检查、手机390×844无横向溢出，7模型对照表，report-qa.json锁定HTML SHA。远端control-attempt2保留全部日志、权重和W&B offline run。无新增付费沙箱调用。
- **后续非本轮完成条件**：科学扩量、代码隔离执行评分、聊天质量评分、封存测试、近重复污染审计、W&B同步、性能触发止损、thinking/tool专项。不要把本轮有限验收改称全面高性能训练完成。此前时间线为历史快照。

- 19:00:08 UTC：step12 exit0、30/30、reload=true，math4/5、IF5/8、knowledge1/1，与base14条已评分逐题相同，code/math各1截断。最后step16 PID1035826运行。step12结果已同步本地。report.py新增可选final-analysis.json（paragraphs/columns/rows）置顶结论，数据尚未填写；最终应完成该文件、重跑summarize/report、全模型一致性审核与浏览器QA。

- 18:52:58 UTC：step8完成30/30、infra0、reload=true；math4/5、IF5/8、knowledge1/1，14条已评分与base逐题相同，step4关键词退步已恢复。step12 PID1035056运行，最后step16待跑。step8同步本地；最终必须运行更新版summarize.py，当前driver缓存旧版。

- 18:45:58 UTC：step4独立评测30/30、infra0、reload=true，math4/5、IF4/8、knowledge1/1；相对base IF退步1题，其他已评分逐题相同。step8 PID1034287运行，之后12/16。step4结果已同步本地。analysis-notes新增base/teacher逐题解释：IF唯一改善为双关键词要求；共同数学失败因4096截断，无最终boxed，勿事后改分。

- 18:39:10 UTC：teacher27B同预算30/30完成、infra0，math4/5、IF6/8、knowledge1/1；相对base仅IF改善1题，其余已评分逐题相同。step4 eval PID1033521启动，后续8/12/16。teacher结果已同步本地，全部正式reload与最终分析仍待完成。

- 18:30:40 UTC：base9B同预算30/30完成，infra0；math4/5、IF5/8、knowledge1/1，code/chat无正确率。smoke与base逐题14条已评分结果全部相同（improved0/regressed0）。teacher27B评测PID1032692活跃，四正式ckpt仍排队。base结果已同步本地models/base-9b；勿与旧diagnostics-v1比较。

- 18:26 UTC：export-full exit0，step4/8/12/16均exported，各权重SHA不同；原版9B独立eval PID1031927运行，后续teacher与四ckpt。完整sampling-audit已刷新16步128轨迹、121唯一样本、unmatched0，分域instruction34/chat33/code32/math26/knowledge3。report新增training-completion-audit展示，已部署；Ruff定向双门通过。

- 18:25:14 UTC：正式16/16步完成，train997761 exit0，最终验证结束；export-full PID1031707已启动。四个checkpoint step4/8/12/16均存在；training-completion-audit.json核对全16步loss/grad有限。driver979002将继续base9B/teacher27B/四ckpt评测。sampling-audit目前仅前15步120样本，最终须刷新加入第16步。目标尚未完成。

- 18:17 UTC附近：正式训练直接TaskRunner日志已step10，checkpoint tracker=8，driver979002/train997761仍活跃。新增sampling-audit.json：前9步72条rollout通过完整role/content渲染精确唯一匹配，unmatched=0；instruction20/chat18/code16/math16/knowledge2。仅代表生成，不代表对应更新已完成；训练结束须刷新到全部16步。report.py已部署展示此证据，HTML同步本地。环境主进程/TaskRunner/WorkerDict再次实测VIRTUAL_ENV一致，PYTHONNOUSERSITE=1。

- 18:06 UTC：正式step4 checkpoint tracker=4，已提前CPU导出到control-attempt2/adapters/global_step_4/lora_adapter，248模块非零B，SHA e77be511b0ad21dc88425a2ee1992cee3cf45377555a9bd15c57a1e72c09e846。export-step4-early.log exit0。后续driver全量导出可复用该adapter。训练997761仍运行，step4验证收尾，日志指标最后step3（验证后才输出step4指标），勿重启。

- 18:03 UTC：正式full已2/16，PID997761，TaskRunner1002227。step1 loss0.19377/grad0.60547/71.67s，step2 loss0.30731/grad0.76563/56.62s；actor/lr日志是scheduler更新后的下一步LR（5e-7、1e-6），step1实际LR0。下一保存step4。若主日志buffer延迟，读/tmp/ray/session_latest/logs/worker*1002227.out。
- 汇总脚本新增中位数及按hash关联generation_reload_verified；运行中的driver已缓存旧summarize模块，最终必须显式执行新summarize.py再生成report.py，勿忘。报告已加入源码/命令hash、W&B offline、原始checkpoint验收、分析快照。全仓Ruff双门通过；HTML桌面/手机无横向溢出（中间快照QA，最终仍需刷新）。

- 17:39 UTC里程碑：smoke训练→导出→独立重载30/30全部通过。248模块非零B，adapter SHA6735b4e27cc8a2d622692ee5944a4d989cd76f1b530b9b860447a4cef2083ff8与eval一致。smoke4096预算math4/5、IF5/8、knowledge1/1、code/chat未评分；尚无同预算base对照不能宣称提升。
- 正式16step train-full PID997761已于17:39:29启动，driver979002继续。目录runs/overnight-opd-20260924-attempt2，仍使用v2数据122/30。后续每4step保存再全部导出/评测。

- 17:32 UTC关键进展：attempt2 smoke训练exit0，step1保存完成；loss0.1948945、grad_norm0.671875、lr1e-6、step109.48s、response_mean456.75、clip_ratio0.125。原进程979006已退出；driver979002进入export-smoke，PID996760。仍需导出非零B与reload-smoke验收，full尚未启动。

- 17:18 UTC实际进展：attempt2 driver979002/train979006存活；TaskRunner983493环境继承已实测写environment.json。actor WorkerDict985141初始化成功；teacher vLLMHttpServer986661/Engine987113/Worker987452正在GPU1加载27B（6/18 shards，约53GB）。GPU0学生参数offload当前约1.3GB；尚未训练更新。Ray细日志/tmp/ray/session_latest/logs/worker*986661*.err，主日志缓冲不完整。无必要不要重启。

- 17:07 UTC最新：v2数据部署122train/30val完成，attempt2 driver979002已启动，使用新数据目录data-overnight-opd-20260924-v2。旧driver970046和teacher977897均已退出，旧40题两模型均完成。先查attempt2/state.json和train-smoke.log。
- v2严格排除math/science uncertain，science仅3train/1val；不能用于领域效果结论。完整80题审计quality-review-80.json/md保存。正式eval4096，训练1024。

- 17:02 UTC最新：attempt2 waiter977686已核对命令后停止（仍在等待，未训练），原因真实逐题审计发现3项验证数据问题；数据agent正在复审math40+knowledge40。旧driver970046/teacher977897继续评测不动。修订数据版本冻结后重新启动attempt2，勿误认等待器活着。MCQA parser已补<B>/Option Selected，需统一重评分旧诊断。

- 16:59 UTC：原版40题短预算1024评测完成，但数学7/8截断；attempt2正式所有评测统一4096（训练rollout仍1024，需报告限制）。旧结果保留为短预算诊断，不与4096混配。配置检查成功exit0，显式激活uv环境，Ray py_executable绑定同环境。

- 最新：attempt1 smoke因缺flash-attn失败，旧driver970046正在跑base/teacher评测，勿中断。attempt2 waiter977686等待其真实退出后启动；新control路径为旧路径加`-attempt2`。训练改sdpa+remove_padding=False，smoke warmup0确保非零更新，full保持warmup2。
- uv创建的Python3.12.3环境确认：torch2.11.0 / transformers5.8.0 / vllm0.23.0 / ray2.54.1；attempt2显式设置VIRTUAL_ENV、UV_PROJECT_ENVIRONMENT、PYTHONNOUSERSITE和PATH。仍需验证Ray worker实际继承。
- 评测return_dict=False实机list[int]通过；IF/code空响应误判已修复，禁止空答案通过。

- Goal active：用户睡眠期间继续真实训练、评测与HTML报告。今晚单教师27B→9B，五领域，非MOPD。
- 服务器 control：`/workspace/verl-uni-agent-harbor-opd-rl/runs/overnight-opd-20260924-control`；driver PID970046，smoke PID970050，16:48 UTC启动。先查state.json、driver.log、train-smoke.log，不重复启动。
- 数据160 train/40 val，各域32/8；code/chat无可靠正确率，不计综合。
- CPU tokenizer、HF/vLLM评分门通过；105响应token mean_abs_error0.01044，p950.07962，仅短序列关闭thinking试验。
- 修复vLLM sampler兼容：VLLM_USE_FLASHINFER_SAMPLER=0。用户授权的Decision Index PID897129已停止。
- 顺序：smoke1→导出/重载评测→正式16步每4步保存→base/teacher/所有有效checkpoint同预算评测。当前仅smoke启动，未证明更新成功。
- 脚本与HTML：`docs/performance-9b/overnight/`；后续同步远端state、index、models、metrics回本地。
- 自动报告10秒刷新；时限停止已实现，性能触发止损尚未实现；W&B offline。异常需保留日志并修复，不重复空跑。
- 当前分支performance-9b，已有未提交变更，勿覆盖。

## TL;DR
- **2026-09-24 当前目标/决策入口：先读 [MOPD项目记忆](mopd-project-memory.md)**。全面能力多教师在线蒸馏为主线；下方训练/评测状态均按历史时间理解，非实时报告。
- 用户要求每个版本 checkpoint 全量评测，取得整体结果。
- 本轮S2所有保留版本，加原版与S1 step12；GPU0全量队列持续运行。
- 已有完整结果：原版64.10%、OPD12 43.27%、RL20 50.96%、RL40 47.76%、RL60 46.15%；OPD12/RL20已补齐infra缺失。
- 新授权：TB2.1→SWE-bench Verified，固定原版/OPD12/RL60，GPU1。数据审计完成，正在验证沙箱/评分器。全量启动待核实既有Modal900美元上限；当前账单856.04美元。
- 先读 `docs/performance-9b/checkpoint-full-eval-design.md`；旧训练历史在该 docs 目录的 `tasks/handoff.md`。

## 本轮交付物
- `docs/performance-9b/checkpoint-full-eval-design.md`：候选清单、流程图、接口、费用、验证与拟改文件。
- 本文件：当前任务冷启动入口；文件行数可用 `wc -l` 复核。

## 设计约束
- 不把0题/exit0当成功；78题每题4条才是完整结果。
- 不合并bf16 LoRA；保持模型、数据、采样、评分口径可追溯。
- 不杀其他会话进程；训练结束的全局Ray清理完成后才开批量评测。
- 非平凡代码改动遵守用户提供的 AGENTS Human Gate，设计批准后实施。

## 已发现真实行为
- 原版与 OPD12 的相同0.6显存配置曾成功；失败step20初始化前额外占用约14.38GiB，checkpoint尚未加载。
- 静态路由检查未发现错卡，历史没有物理GPU UUID/占用PID证据；不能推断占用者。
- eval_val_only.sh 吞掉底层异常，0题结果仍退出0。
- S2保留 OPD10/11/12，RL20/40/58/59/60；58模型文件偏小，未证明完整。

## 下一里程碑
- [x] 清点保留文件、pinned去重与只读故障分析。
- [x] 设计落盘。
- [ ] 用户批准设计与范围。
- [ ] checkpoint完整性检查、显存/路由诊断与首题真实验证。
- [ ] 修复失败传播；实现可恢复队列与回归测试。
- [ ] 逐版本78×4，配对与行为统计，完整总报告。

## 分支/部署状态
- 分支 verl-uni-agent-harbor-opd-rl，清点前 HEAD fa2653a，工作区当时干净。
- pod SSH：root@157.157.221.177:11965，密钥 ~/.ssh/id_ed25519。
- 2026-09-20 12:37 UTC：第60步checkpoint已保存，最终验证4/8任务完成，GPU0工作，GPU1空闲。不能当当前实时状态。
- 本任务未部署代码、未启动新批次、未跑新CI；已写设计不等于已完成实现。

## 冷启动 checklist
1. 读设计与本交接，查看用户是否批准及范围答复。
2. 查git状态，保留所有已有改动。
3. 查训练收尾、GPU UUID/进程占用和Tinker排期、Modal额度。
4. 核查全部候选checkpoint文件，处理58异常。
5. 按批准设计完成首题真实验证，再运行全量队列。

## 2026-09-20 执行更新
- 训练12:53 UTC PASSED，最终60步保存；delta失败原因是损坏的step58，supervisor已完成退出。
- 新文件 eval_result_check.py：精确parquet任务身份、每题样本数、checkpoint加载证明、底层退出码；validation.json complete才通过。
- 新文件 eval_checkpoint_matrix.py：manifest哈希、数据/基线哈希、进程锁、GPU空闲检查、每版本独立目录、有限重试、0样本停止、配对/行为汇总。
- manifest：docs/performance-9b/checkpoint-full-eval/manifest.json；服务器 runs/full-matrix-manifest-20260920.json。
- Probe：runs/matrix-probe60，脱机sid2663882，GPU0，step60，1题1次，原推理配置0.6/36864，model-only加载；14:20 UTC开始。
- Queue：runs/full-matrix-20260920-launch.log，gate.json/state在runs/full-matrix-20260920；初次等待进程已停止并更新竞态保护后重挂。
- step58 archive损坏已确认；保留证据，标记unavailable。
- 测试：14项新功能测试通过，Ruff全仓双门通过；更广回归卡在本地pandas/parquet子进程，已终止，不能宣称全套通过。
- 本地改动尚未commit/push；服务器已单文件部署，后续必须核对身份再交付。
- 下一次先检查probe validation.json：只有complete才让全量开跑；失败时队列会停，不反复空跑。

- 15:20 UTC复核：probe于14:55:35 UTC完整通过，1题1样本，得分0；第60步成功加载。队列重新启动sid2686667，首版本step60全量；仍需检查status.json实际running。

## 2026-09-21 继续推进
- 13:46 UTC远端队列仍在运行，非全部完成。RL60 attempt2完整46.15%，差-17.95pp [-25,-10.90]；RL40 attempt1完整47.76%，差-16.35pp [-24.36,-8.65]。
- OPD12/RL20各两次后仍311/312，原队列标exhausted。固定以attempt2补缺，不能挑得分高的attempt。
- OPD12缺TL10836：tmux no server；RL20缺TL08999：verifier timeout300s。只补infra缺口，不改已有效0分；由eval_supplement.py新模块执行（实现中）。
- GPU0评OPD10，GPU1空闲可补缺；运行队列仍旧进程，不能声称新代码自动热更新。
- 新证据目录 docs/performance-9b/checkpoint-full-eval/evidence-20260921/。
- 尚未得到全版本整体结果；用户明确要继续推进。

## 2026-09-21 补测部署
- eval_supplement.py 与 test_harbor_eval_supplement.py：9项补测测试+5项队列测试=14 passed，Ruff全仓双门通过。
- GPU1补测驱动：runs/run-supplements-20260921.sh；日志runs/supplements-20260921.log。固定OPD12/RL20 attempt2各补1，输出各自-label-supplemented-20260921目录，原attempt不动。
- 源全量队列status仍会显示这两项exhausted，不自动改写其他进程state；查询必须额外读取新目录validation.json、pair.json。
- 汇总时保留缺失当0的source_coverage_adjusted_framework_rate与补齐aggregate_framework_rate；历史infra事件不抹掉。
- 校验主要口径为framework resolved，behavior脚本raw reward solve_rate不同，不能混用。

## 2026-09-21 补测完成与跨集方案
- 补测驱动14:43:23 UTC exit=0。OPD12/RL20 aggregate validation均complete、errors=[]，每题4次无缺失。
- OPD12补齐43.27%，相对原版-20.83pp，95%区间[-28.53,-13.14]；RL20补齐50.96%，差-13.14pp，区间[-18.59,-7.37]。pair已存到checkpoint-full-eval/evidence-20260921/。
- 用户询问OPD+RL是否无效、能否评测其他软件benchmark。新文档docs/performance-9b/cross-benchmark-proposal.md记录结论边界、TB2.1/Verified/EvalPlus可行性和三模型对照方案。
- TB2.1 parquet远端存在；Verified适配入口存在但未端到端验证。新benchmark尚未启动。不能将本次序列训练结果推广为所有OPD/RL无效；缺严格纯RL对照。

## 2026-09-21 新跨集评测授权与部署
- 用户明确要求完成TB2.1后SWE-bench Verified三模型同预算评测，原队列继续。范围/manifest/config/audit均在docs/performance-9b/cross-benchmark/。
- Verified500题已下载。两套与实际S2训练500题的canonical ID/repo/题面哈希/词7-gram相似度检查无重叠；任务内容SHA已存，不能称语义污染完全排除。
- Verified500个verifier均采用FAIL_TO_PASS/PASS_TO_PASS及ResolvedStatus.FULL。远端nop/oracle控制驱动sid3495293，日志runs/cross-benchmark-20260921/verifier-controls.log。
- 新driver eval_benchmark_matrix.py，base/OPD12/RL60各固定3题探针后全量（TB n3、Verified n1）；--probe-only只验证不启动全量；base补缺已支持。新20测试通过；旧gate/matrix14通过；全仓Ruff lint/format通过。
- TB每题声明时间最多24600秒，Verified7800秒；配置外层分别25200/8400秒，sandbox25800/9000秒，同benchmark三模型一致。资源随任务，不压缩官方题目为满足旧3000秒。
- full计划2301条轨迹；已询问用户是否调高共享900美元上限。未获答复前不能默认扩额或启动整个full队列。小规模验证继续，GPU0旧矩阵不停止。
- 真实控制已完成：TB cancel-async-tasks、Verified astropy均nop0/oracle1；build-cython-ext oracle在planarity1.0.0/networkx3.6.1组合缺pos，作为已知参考解问题保留89题主结果，不能算模型失败证据。
- GPU1 TB三模型probe-only已发起，日志cross-benchmark-20260921/tb-model-probes.log，状态status-tb21-probe.json；不自动进入full。后续查真实加载/样本状态，不能把启动当成功。
- 新旧针对性回归合并34项通过，全仓Ruff519files通过；源码和manifest远端SHA与本地一致。全量仍未开始，预算答复待收。

## 2026-09-23 HF 数据归档完成

- 三套数据已重命名保存到 gump2049 私有 HF 仓库；入口 `docs/performance-9b/hf-data-archives.md`，机器记录 `hf-data-archives.json`。
- 保留上游固定 revision、数据文件、许可证、README 与 provenance SHA256。远端内容核验完成。
- 下一步仍是训练准入审计；不要把 archived_unvalidated 当成可直接训练。
- 当前分支 performance-9b；本次归档不修改训练进程，不能据此更新实时训练状态。

## 2026-09-25 追加更正：VERL 原生 SFT 与实际 smoke

- VERL 原生 SFT 入口是 `torchrun -m verl.trainer.sft_trainer`；可参考 `verl/examples/sft/gsm8k/run_qwen2_5_0_5b_fsdp.sh`、`verl/examples/sft/multiturn/run_qwen2_5_0_5b_fsdp.sh`。本项目启动器只负责 workspace、数据 adapter、日志和可选观测，不替换 trainer。
- 独立 GPU pod `performance-9b-verl-sft`（SSH 端口 13595）已完成单卡 1-step smoke，exit code=0；W&B run 已同步，checkpoint 已写入 workspace。此前“仍未真实 forward/backward”的旧段落作废。
- 当前 adapter 的已知硬缺口：尚未实现 `target_message_index` 的目标消息监督，现路径对所有 assistant 输出计算 loss；不能据此启动全量蒸馏训练。
- 当前环境没有 `flash-attn`/`causal-conv1d`，所以 smoke 明确使用 `model.override_config.attn_implementation=sdpa`。SDPA 是 attention backend，FSDP 是训练 engine，Megatron 是另一后端；未证明 FlashAttention 不兼容，需另建匹配环境后做性能与 packed 边界对照。

## 2026-09-24 Qwen Max数据补搜

qwen38-max-sft-review.md固定3库revision、区分Max-Preview/27B，候选有真实用途与污染限制，当前配额0。v2强教师核心不变，未下载全量/训练。
## 2026-09-25 数据工程完整打通：结构母本已导出，质量准入未完成

- 当前 goal 已收敛为：完成 Runpod 原始归档 → 统一 `apus-sft-v1` 母本 → 质量/验证门禁 → 双框架导出 → 20K → 有界训练的可审计链路；不能用候选数替代 training-ready 数。
- Runpod `/workspace/apus-data-cleaning/reports/contract-v1/` 已从 screened-v2 导出 62,030/62,030 行，拒绝 0；流式校验 `bad_count=0`，文件 2,870,105,620 bytes，sha256 `c75aa7068031837f749d826e265c594e7fef657e10d0a47af5669d597e7dff37`。
- 分布：code 44,945、reasoning 13,121、general 3,964；teacher family 仅 gpt56 32,624、qwen38 29,406；train 59,164、validation 2,866；task groups 26,757。
- 这只是结构筛选中间母本：62,030 条均带 `teacher_identity_unresolved`、`language_unresolved`、`source_split_unresolved`、`source_license_unresolved` 中至少相应缺口，54,682 条 reasoning policy unresolved；`training_ready=false`。
- 本地证据：`docs/performance-9b/contract-v1-evidence/{validation.json,apus-sft-v1.manifest.json,export.log}`；导出器 `examples/performance_9b/export_contract.py`，测试 `tests/uni_agent/examples/test_performance_9b_export_contract.py`。
- 下一步：回读固定原始 manifest 补齐来源字段；固定 validation/sealed manifest；做任务组/污染/近重复门禁；再做 Arrow/Parquet/HF 与 ms-swift/VERL 导出。未达到准入前不抽 20K、不上传训练版、不启动训练。

## 2026-09-25 最新：v5 审计与 20K 缺口冻结

- quality-audit-v5 已完成：输入62030，provisional_candidates=10494，quarantine=51536，approved_rows=0，training_ready=false；候选全部为 code，teacher qwen38=10489、gpt56=5。
- v1 曾错误放行的16732条已明确作废；v2/v3/v4诊断结果不能转为训练池。
- Qwen3.5-9B tokenizer adapter v9 对全部10494 provisional候选渲染通过，error=0、tool_rows=5、token p50=7401；这不是 loss-mask 或语义质量验收。
- 20K目标与真实approved供给差距已冻结：`docs/performance-9b/20k-deficit-report.md` 和 `.json`。7K code、3K reasoning、3K office、2.5K data、1.5K translation、1.5K writing、1.5K general 当前approved均为0；不得抽样、上传或启动训练。
- 下一里程碑：完成候选机械语义审计、teacher/license/language证据、显式assistant/tool mask覆盖率验证；所有能力域形成approved pool后才生成固定seed的20K导出。
- 新提交：`5ae9cf9 docs(performance-9b): record 20k data deficit audit`。

## 2026-09-25 最新：VERL SFT 适配 smoke 通过

- 参照 `docs/performance-9b/uv-runbook.md`：workspace 是唯一持久资产根。此前失败安装产生的 `/root/.cache` 已清理，根盘由88%降至7%；源数据、模型、runs未删除。
- `apus-sft-v1` → VERL Parquet：62030/62030，拒绝0。动态工具列以JSON字符串保存，避免Arrow异构nested struct。
- 新增 `examples/performance_9b/verl_sft_dataset.py` 薄适配层：JSON解码、Qwen累计前缀tokenization、assistant header零mask、完整chat-template等价检查。
- 普通样本通过：1247 tokens / 48 loss tokens；真实assistant tool-call样本通过：1341 tokens / 135 loss tokens。
- 证据：`docs/performance-9b/verl-sft-adaptation.md`、`docs/performance-9b/verl-sft-evidence/export-manifest.json`。
- 尚未完成：GPU workspace SFT lane、真实forward/backward、W&B/VERL观测接线、validation/sealed split和20K导出。

## 2026-09-25 适配复杂度复核

- 不再增加 MIMO 专用转换层。`examples/performance_9b/verl_sft_dataset.py` 是唯一运行时适配边界：解码 JSON 动态列、累计 Qwen chat-template 前缀、assistant header 置零 mask，并用完整渲染做等价校验。
- 普通样本（1247 tokens / 48 loss tokens）和真实 assistant tool-call 样本（1341 / 135）均已在 CPU 共享环境通过 smoke；本地与远端适配器、启动器 SHA256 一致。
- 剩余针对性验收只有 GPU 两卡一步 forward/backward + checkpoint smoke，并核对 W&B、`train.log`、`exit-code` 和 checkpoint 同时存在。Runpod API 当前 DNS 失败，GPU SSH 11965 当前关闭，因此尚未启动真实训练。
- CPU 分片已固定：`train.parquet` 59164 行、`validation.parquet` 2866 行。格式适配已完成；质量审计中的 `training_ready=false` 仍是独立门禁，不被格式 smoke 覆盖。

## 2026-09-25 Runpod 账户纠偏与 GPU preflight

- 本机默认 Runpod key 属于 `xdanwork@gmail.com`，余额不足且看不到当前 pod；用户提供的 key 属于 `l98348740@gmail.com`。不得混用两个账户的 pod/volume 记录。
- 正确资源身份：pod `45ao3zsq6w7xck`（`apus-openjev-serving`），SSH `157.157.221.177:16358`，volume `72jdno5cuk`（`RL-Harbor-sky_volume`），1× RTX PRO 6000 Blackwell Server Edition，约 96GB。
- `sft_preflight.sh` 已同步到共享源码目录并后台运行，输出预期为 `/workspace/apus-data-cleaning/reports/verl-sft-v1/preflight.json`。完成后先读 `preflight.log/json`，再启动单卡 smoke。
- 全局数据状态详见 `docs/performance-9b/data-pipeline-status-20260925.md`。当前仍未取得真实 SFT checkpoint、W&B step 对账或 rl-insight 后端 trace。

## 2026-09-25 双卡 cu128 SFT lane 已验收

- 新双卡 pod：`157.157.221.177:11403`，镜像 `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`，2× RTX PRO 6000 Blackwell；`/workspace` 为持久卷。
- 独立 lane：`performance-9b-sft-py312-cu128`，Torch `2.8.0+cu128`、CUDA runtime `12.8`。环境重建入口为 `deployment/bootstrap/setup-performance-9b-sft-cu128.sh`，freeze 为 `deployment/versions/uv-lanes/performance-9b-sft-py312-cu128.freeze.txt`；两文件已保存到本地并同步到远端源码目录。
- `flash-attn==2.8.3.post1`、`causal-conv1d==1.7.0` 均在该 venv/CUDA 上源码构建，`fla-core==0.5.2` 与 `flash-linear-attention==0.5.2` 已安装；import/forward smoke 和 `uv pip check` 通过。
- 双卡 VERL FSDP SFT smoke：`runs/performance-9b-sft/verl-sft-smoke-cu128-2gpu-fla-20260925T033619Z/`，exit code `0`，train loss `2.134`、val loss `1.84526`、global tokens `2588`；W&B `https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/sh6t7dg6`。
- 该 smoke 只证明环境、native extensions、FSDP、W&B 链路可以运行；当前数据审计仍是 `training_ready=false`，监督 mask/20K准入完成前不得启动长跑。现有 cu130 lane 不得复用此 freeze 或 cache。

## 2026-09-25 最新：pilot v3 完成，两个运行时问题已修复

- 双卡 pod 已切换为 `157.157.221.177:11403` / `db7kewdkd71js6`，环境为 `performance-9b-sft-py312-cu128`。GPU 当前空闲，未留下训练进程。
- 全量尝试 `verl-sft-cu128-full-20260925T0432Z` 曾在真实第 1 步后因旧 adapter 的 Qwen3.5 多轮 prefix instability 退出；不是模型或 GPU 故障。pilot v2 又发现把 Qwen3.5 vision processor 当文本 tokenizer 会触发图片解码错误。
- 修复方式：完整渲染一次 chat template，使用 tokenizer offsets 标记 assistant body；新增无 VERL 依赖的 `examples/performance_9b/verl_sft_mask.py` 与本机回归测试，Qwen3.5 文本路径不再调用 vision processor。
- pilot v3：`runs/performance-9b-sft/verl-sft-cu128-pilot-v3-20260925T0508Z/`，2 卡 FSDP、FlashAttention2、LoRA rank16、512 train / 64 validation samples、16 steps，exit code `0`。第 8/16 步 checkpoint 均完整；最后 `val/loss=1.0285365581512451`，W&B 为 `https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/92602dg0`。
- pilot 运行日志与 W&B 均记录了 `train/loss`、`grad_norm`、`global_tokens`、显存、validation loss；`trainer.logger` 中虽包含 `rl_insight`，但原生 torchrun 没初始化 Ray，日志为 `Ray is not initialized; monitoring is disabled`。rl-insight 服务已运行，但本次不计 Ray trace 验收。
- 不得把 pilot 当作全量完成。旧全量配置按约 26.5 秒/step、29,582 steps 粗估约 9 天，必须先固定 20K 子集、确认数据准入与吞吐，再决定长跑；质量审计仍是 `training_ready=false`。
- 下一步：同步新 adapter 到远端；用固定 20K/validation 做有界训练；检查 checkpoint 可读性、loss-mask 与数据域曲线；若要使用 rl-insight，补明确的 Ray 初始化或独立事件发送路径。
