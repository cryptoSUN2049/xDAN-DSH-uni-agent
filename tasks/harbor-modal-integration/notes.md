# 工作区过程记录

## 2026-09-09 工程评估收尾前历史快照归档

以下running/旧目录/旧下一步仅供溯源，不覆盖当前handoff。

## 1. TL;DR

- **最终四题隔离补验已完成收尾（10:44:40UTC）**：suite/root/runs/ws-r4-isolated-eval-r1，source9dea127，exit1但all_attempted=true、stop_reason=null。WS01/03/05各1组2unique A/B消费审计通过，共3组6行，业务A/B奖励全0。WS06 A max-tokens，fresh=true/finished=false/eligible=false，未B、未消费，原失败保留；不是4/4通过。GPU0%/0MiB。E1—E4执行层完成；W5逐题结果复跑完成，原W4非零更新仍未完成，禁止把全goal标done。最终报告与归档见work-state-independent-evaluation-r1-result.md/json及其archive。

- **独立reload首题通过**：10:17:18UTC WS01 child270480 exit0/490.011秒，1组2unique A/B实际消费，原audit passed=true；真实加载母step8的model/optimizer/RNG/scheduler，post-run母hash与GPU清理核验通过。WS03继续运行，不能称四题已完成。首题证据work-state-independent-evaluation-r1-first-task.md/json。

- **当前四题独立补验运行中**：source9dea127已push，部署/workspace/rebuild/uni-agent-work-state-singletons-r1，原venv。driver270247，/root/runs/ws-r4-isolated-eval-r1/summary.json；Linux追加3项after_run通过。10:12:39UTC首题WS01权重加载，尚无消费结论。完整命令见work-state-rl-runbook.md，启动记录work-state-independent-evaluation-r1-execution.md。不要重复启动或更新运行中checkout。

- **最新selected-r1已失败结束**：source726d1c0，child264469 exit1/685.015秒。WS05 A 78工具调用（72view）后max-tokens，finished=false；WS01/03已提交但整批dump缺失，2groups/0消费，原audit=false。加载model/optimizer/RNG/scheduler及母11文件未变已通过；Linux74项回归通过。见selected-r1-result.md/json。正实施固定四题各自独立reload/审计，保留失败并继续，禁止伪造消费。
- **证据已保存云盘并回读通过**：/workspace/reports/work-state-r4-engineering-evidence-20260909-r1.tar.gz，18,128,085字节，168670源文件，SHA256 1d19e4f757a8d9df8610a9f3e3f6d52957a5ac3ea141c06ef85f2bee13b86093；未打包3份training.env。
- **零奖励根因已独立核验**：32个B的业务重评均与原回执一致；0/32配置正确，仅1/32尝试读取index，不能通过放松评分凑非零梯度。原课程W4仍未通过。

- **最新验收：E2/E3通过，E4尚待评估结果完整落盘。** r4最终8组/64唯一消费、289原生成段EOS通过，实际6unique任务/3拒组；模型4→8完全相同、base399不变、LoRA B252张量全0，8步grad0，无有效学习。原报告work-state-train-r4-result.md/json。独立reload child258242 exit1/545.014秒，已实际加载step8，第四个val未准入导致最后汇总未写（3crosswalk、0validation dump），GPU已释放。母checkpoint无改动；后续最小任务隔离补验，不重训，不改原VERL或奖励。

- **最新：r4母训练8/8步exit0，独立reload已启动待验收。** child243079/1920.038秒；8步消费文件、CK4/8保存，8步grad/reward全0。最终CPU消费与参数审计进行中。reload launch PID258133，14:56:46 UTC+8，新/root/runs/work-state-train-r4-reload与-data/manifest.json，固定原5b4b01b源码、原venv，母step8绑定/val-only预检通过。不要因exit0宣称有效学习；以下旧进度保留作历史检查点。

- **最新r4已启动，尚未验收**：2026-09-09 14:18:35 UTC+8，launch PID242996，源码5b4b01b1d0ab656e960d3514d0a3630210913022已push；独立/workspace/rebuild/uni-agent-work-state-r4，原venv。预检通过：8steps/n4/save4与8，关闭初始与周期val。日志/root/runs/work-state-train-r4/supervision/train.log；清单/root/runs/work-state-train-r4-data/manifest.json。54项独立recipe+audit回归及Ruff双门通过，详见work-state-train-r4-execution.md。以下r3/r4未启动文字是上轮检查点。

- **当前状态：r3已失败，r4尚未启动。** r3 child232331 exit1/1275.026秒，global_steps4周期val WS06 writer A尝试写只读source被拒，未进入B；原始报告`work-state-train-r3-result.md/json`。step1–3记录reward/adv/grad全0，step4 CK存在未验收有效更新或独立reload。主线程interim audit11groups/7consumed/32rows，无errors；不能据此标整轮passed。
- **用户当前优先级：工程运行→有效更新证据→能力效果。** 合法全0不主动停止；原安全/证据拒绝仍不放宽。本地调度修复已通过27项recipe回归：work-state train关闭`val_before_train`、`test_freq=0`，保留8steps/n4/save4与8；独立严格val/reload保留，单个评估任务被拒不再通过内嵌周期val拖停训练。待主线程提交/推送、固定新manifest后再启动r4，不能沿用旧r3数据清单。
- **可复用固定部署**：r3源码`17b6e5589abc8d5a77c6238d0971a129135aa9b7`，protocol3，VERL fef+preserve-finish-reason-v1显式补丁；DSH SDK/runtime已0.1.3a2/b236且私有Release/lock存在。旧截图“runtime未发布需重建”已过时；不重装GPU环境，先核新checkout/venv/runtimehash。
- **已通过工程证据**：固定Linux DSH工具canary8结构/106请求、finish canary4/4与vLLM环境30项HTTP/解析测试。它们不替代学生训练验收。手工入口`docs/harbor-modal-integration/work-state-rl-runbook.md`；r2/r3 failed原产物不修改，W4学习证据仍独立待验。

以下为此前检查点，时间与身份保留，不覆盖上述当前状态。

- **12:41:38 UTC+8检查点**：work-state-train-r2真实GPU45%/38928MiB；初始4dev已返回全0，step1/2已生成并被训练器消费（rollouts/1、2），每组n4 terminal B全0、advantages全0、grad_norm=0。因此没有本课程有效学习验收；继续查工具parser/任务理解与实际消费边界。
- **协议审计纠正**：固定VERL合并length/stop为completed，DSH completed不足以证明自然结束。r1 WS01 A原NPZ到16384且非EOS，撤回“不是token耗尽”。新增只读generation-boundary audit（19项CPU回归）核已消费原token各生成段EOS，不改原回执，不修改运行中的12902fb源码。

- **当前GPU作业：work-state-train-r2**，2026-09-09 12:26:17 UTC+8 launch PID221508；源码`/workspace/rebuild/uni-agent-work-state-r2`固定`12902fb8849d9fdfa118686207669bbedfcfec37`。任务protocol2只澄清A交接角色/停止条件/相对索引，80CPU回归通过；复用旧venv，初始严格val→最多8步RL，日志`/root/runs/work-state-train-r2/supervision/train.log`。尚无本课程更新或checkpoint验收。
- **work-state-val-r1已失败结束**：主运行12:05:05→12:23:31 UTC+8，exit1/1125.024秒；WS01/03不准入，WS06未完成；WS05真实合法A0→B0仅写TQ，独立audit1group/0消费，无更新/CK。原receipt不改。详见`work-state-val-r1-result.md/json`；旧work-state-train-r1-data未启动，不得沿用。下面“val-r1正在运行”属此前快照。


- **最新执行状态（2026-09-09 12:04:27 UTC+8）**：已启动GPU学生`work-state-val-r1`监督PID214082，独立源码`/workspace/rebuild/uni-agent-work-state-r1`固定`801083579318ed5268cc92caf45c3ce04ef6d099`；复用旧venv/模型，4公开dev、val-only。启动不等于模型加载；须继续查`/root/runs/work-state-val-r1/supervision/train.log`与最终消费audit，不按PID报通过。母训练尚未启动。
- **W1完成**：core6085a13、recipe/audit8010835均已push；229Python+6Node核心回归、31recipe/audit组合通过。Linux真实DSH canary8结构/106请求通过（无模型），报告`work-state-runtime-canary-r1-result.md`；手动全流程`work-state-rl-runbook.md`。W2学生基线进行中，W3—W6未完成。下面旧“在制/未提交/GPU释放”描述为此前检查点。


- **当前执行goal已按用户双目标更新**：有价值的工作状态任务 + 用同一批任务验收原生在线RL，按`active-engineering-goal.md`的W0—W6推进。W0设计和W1合同/真实canary完成；W2数据基线、W3真实消费、W4有效更新/CK、W5独立reload、W6复跑交付仍未完成。提分另行对照，Harbor/异步/从零安装后置。
- 本次goal文档交付：`tasks/harbor-modal-integration/active-engineering-goal.md`（92行，双目标与退出条件）、本`handoff.md`（277行，当前状态与冷启动）、`tasks/todo.md`（513行，当前可勾选计划）、`tasks/lessons.md`（198行，双目标纠偏）。文档链接/节点状态、Ruff check/format、diff检查通过；本次未启动GPU。提交身份用本次docs(goal)提交核验，未提交实现保留在工作区。
- **本地在制实现，不是GPU结果**：work_state任务/评分35项、verifier19项、stage14项新测试；bundle/profile及Node权限测试、框架A0+B0→TQ组合回归已由独立代理通过。新bundle消费审计、recipe和真实DSH/GPU验收仍待补齐。各测试组重叠，不累加为总通过数；当前代码未随本次goal文档检查点提交或部署。
- **用户最新能力目标已细化**：训练模型适时管理goal/tasks/handoff/memory/index，执行offload、获准compact并可靠恢复长周期工作；不是仅A/B文件问答。完整设计 `docs/harbor-modal-integration/dsh-memory-context-skills-plan.md`（17节、12个开发种子规格、信息矩阵/数据schema/reward/验收），HTML为概览。下一能力批次先WS01/03/05/06；模型自主compact需真实工具与request变化验收，不能从实验ABI推断可用。
- **最新GPU已退出，无运行作业**：memory-resident-train-r2，主训练2026-09-09 10:28:34→10:34:37 UTC+8，supervisor child196565 exit1/380.009秒，GPU已释放。仅initial val A，finished/fresh/eligible但reward0：同轮预生成view与create，未看到源就写key1/key2；原writer质量门拒绝，B/n4/消费/更新/ckpt均0。空TQ keys是后续错误，报告memory-resident-train-r2-result.md/json。不要循环重跑或放宽旧门追认成功。
- **独立reload入口CPU完成**：prepare_memory_training新增mode=reload/resume-from/mother-run，绑定母实验证据和完整checkpoint SHA，强制val-only不删除原CK；组合89项/主线程19项回归通过。train-r2无CK，因此尚不能GPU reload。

- **最新GPU验收通过：memory-resident-val-r2**，2026-09-09 10:12:25启动（UTC+8），385.009秒exit0；源码 `/workspace/rebuild/uni-agent-memory-resident-r2` c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0。真实A/B各reward1、独立freeze/新会话；专用消费审计passed=true，1完整val链/2 keys各消费一次，policy0各3/3段完整，unknown/duplicate=0。无训练更新/checkpoint，GPU已释放。报告memory-resident-val-r2-result.md/json。train-r2同源码CPU准备已通过，后续train-r2已失败，见顶部；旧train-r1不可启动。

- **上轮GPU任务已失败并停止**：memory-resident-val-r1，源码4168b628，supervisor exit=-15/540.012秒，owned child185194。NativeMemory构造误拒VERL默认非空reward handles，A/B尚0stage；主线程核PGID后SIGTERM该组，GPU已查无残留。原run-manifest仍running为外部终止留下的真实不一致，不能当活作业。局部修复及生产默认注入回归已完成，316项组合通过，主线程38项复核通过；修复后必须新commit/new prepare/new run，不能启动旧train-r1清单。

- 人工SSH复跑入口：`docs/harbor-modal-integration/native-training-human-runbook.md`；逐节点E0—E5标准：`native-engineering-acceptance.md`。工程正确闭环为当前重点，提分/扩量非前置。

- 当前worktree `harbor-modal-integration` / 分支 `worktree-harbor-modal-integration`。Goal工具当前usageLimited；文档目标仍未完成、继续执行。四能力与结果复现优先，Harbor后置，SFT不属本轮。权威目标active-engineering-goal.md，总方案uni-agent-system-plan-v3.html。
- **当前 reload**：`context-v2-curriculum-r1-reload-step12`，监督重试PID178933，plan/supervisor-retry1.log，wall3600秒，原d3084f2+已验收venv。前监督178761在启动前断言失败，未加载模型：PRINT_COMMAND已创建run目录。仅两份打印证据已原样移至同级 `context-v2-curriculum-r1-reload-step12-print-command-evidence`，无删除。重试已exit0/470.012秒、实际加载step12并产出4题dev指标，GPU已释放；最终4/4 fresh消费与无更新审计通过；母课程optimizer6→12专属审计通过（1008 moments变化且有限）。报告context-v2-curriculum-r1-reload-result.md及配套JSON，云盘审计归档已保存。母12步exit0/1000.024秒，48消费覆盖11题（D3拒绝/D2补采），6步非零梯度，dev strict0/4。
- **最新完成第二族**：`dsh-memory-updates-r1` A/B均exit0、reward1，finalize passed，旧eu-west-test被当前ap-south-test正确替代；独立CPU复核与云盘归档通过，training=false。报告native-memory-updates-r1-result.md/json。
- **已完成记忆第一族**：`/root/runs/dsh-memory-constraints-r3`，reader监督PID152851；remote checkout `/workspace/rebuild/uni-agent-native-n0-r1` 固定 `d3084f2a771804f011c4e641ecf0986c7166bc86`，旧已验收venv，writer prompt revision2 已282.038秒exit0/score1，freeze严格通过；B已326.049秒exit0/reward1，主线程finalize整链passed。该run已完成，无训练。
- **context独立reload已完成**：`context-v2-train-r1-reload` 415.009秒exit0，model/optimizer/RNG/lr_scheduler真实从step2加载；4/4fresh评估组被消费，无新增训练更新。reward均值.241875、严格准确率0；与训练dev均值.255不同，只证明结果重跑，非精确数值复现或效果提升。报告context-v2-train-r1-reload-report.md/result.json。
- 母context训练595.014秒exit0：实际2个训练任务/n4，step1非零梯度，step2零adv；CPU审计14/14组消费通过，252 LoRA变化/399 base冻结，dev严格准确率0。step2一阶/二阶moment分别精确等于step1×.9/.999，不能称新增任务学习信号。
- 使用已验收venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5`，absolute PYTHONPATH指当前checkout；不要重装环境或修改运行中源码。checkpoint `/workspace/uni-agent-g1/checkpoint/context-v2-train-r1/`；运行日志 `train.log`/`supervisor-result.json`。禁止全局Ray清理。
- context v2 **r4四题真实strict准入及TQ回读通过**：290.008秒exit0，reward .1/.1/.1/.72，strict准确率0，无optimizer。报告native-context-v2-baseline-r4-result.json。r2曾误拒合法view_range；r3是root启动相对PYTHONPATH错误，均保留失败。新版本已83项回归通过。
- memory writer r2：4steps/3工具调用，拒绝一次后成功创建正确memory；因一次越权硬拒，未freeze/B。初始操作协议revision2已`5867fcf`推送、57项回归通过，r3已真实两工具调用成功、无越权、fresh receipt=1，独立重评分及冻结摘要通过。reader152851已成功，A/B独立身份及读取/回答复核通过；training=false，不能复用r2或追认通过。
- M1 v2-r4既有两步真实RL、504 LoRA更新/399 base冻结、optimizer与消费审计、独立reload已通过；两公开题原本满分，不能宣称能力提升。RSI固定Linux父/子/回滚18工具调用通过，但synthetic选择不计学生训练；未晋升候选隔离评估入口已208dfcb推送，46项CPU通过；真实学生开发比较未实现。
- 数据审计native-data-coverage-audit.md：context12 train/4 dev；memory两固定模板；封存能力测试已验收数0。独立任务、采样尝试、实际消费分开报告。最新诊断云盘归档摘要见native-diagnostics-archive-through-context-v2-r2.json。
- 下一步：constraints-r3及updates-r1两族A→冻结→B已整链通过（固定诊断题，无训练）；12步context消费、参数/optimizer及独立reload已完成；下一步补齐NativeMemory recipe/真实消费审计并做GPU resident A/B训练路径，后续RSI学生评估。context训练/reload日志、数据、审计与metrics已归档 `/workspace/reports/context-v2-train-r1-reload-20260909.tar.gz`，摘要见context-v2-train-r1-reload-archive.json；checkpoint已在/workspace。清单驱动inference launcher已补齐，避免手写相对PYTHONPATH；后续使用精确checkout配套清单。

### 最新 N0/N1/P1 检查点

- runtime-grounding-r1于340.01秒exit1：模型max-tokens，finished=false，严格组拒绝；结果在 `/root/runs/dsh-capability-grounding-baseline-r1`，无训练或checkpoint。保留失败；trace仅61个生成token，错误查询Service大目录后容量耗尽，非2048单轮输出截断。
- 新venv `/workspace/venvs/uni-agent-native-n0-r1` 已安装完成：257 packages、pip check、固定runtime摘要及隔离import检查通过。仅CPU安装验收，不替代GPU复建/能力结果。
- 原M1 optimizer独立CPU复核通过：2→4，504 active/37 empty，1008 moment tensors变化；报告 `native-r4-optimizer-result-replay.json`。不是新增训练。
- 记忆freeze/load合同已通过；新closed policy及Mac SDK canary14真实工具调用通过。固定Linux runtime canary14请求通过；尚无模型A/B记忆训练验收。
- 上下文两族四例与准备器已落盘，独立verifier/manifest/严格runner接线通过。本轮复核22项测试，Ruff双门通过；真实r1结果见native-context-baseline-r1-result.json。四例仅文件证据诊断，不证明泛化。
- P1 sync/colocate_async入口已实现，GPU异步对照尚未执行。
- 用户已澄清无其他会话占GPU；保留运行前占用核验，不再据过期歧义阻塞。禁止全局Ray清理。优先真实任务与独立结果重跑，不重复安装。
- 用户提醒数据量；四例仅调试入口，正式RL必须覆盖各能力场景、独立训练/评估身份，并报告有效组与奖励差异，不能将重复采样当任务多样性。

以下 M2 段均为历史证据；其中“下一步”不覆盖上述原生优先顺序。

### 最新检查点：M2 r1 失败与清理修复

- Harbor v2 已完成真实 Docker 正例、部分分、合法零分、篡改拒绝四模式；镜像已发布私有 Release，见 `docs/harbor-modal-integration/harbor-evolution-v2-image-release.json`。
- M2 r1 GPU 源码 be8237e，前四个 job 成功；第五个学生 max-tokens 未完成，正确拒绝。随后发现 cleanup 事实丢失，旧 job 卡 cancelling，新 job 反复创建。不是 CUDA 未安装，也不是摘要损坏。
- 已停止本 run 专属训练进程组；supervisor exit=-6、835.18 秒。停止后 GPU 0%、0 MiB。M2 没有验收成功的训练更新或 checkpoint。
- 修复：只有实际 Docker 六项查空通过才报告 CleanExecutionRejected；worker 封存 cancelled/空 artifacts 并释放 slot；ledger 在插入前拒绝活跃或未确认作业。685 项组合回归通过，真实清理失败→后续正常 job 验证进行中。
- 下一步：真实 Docker 负例恢复验证 → 新身份 M2 sync → 数值审计与独立 reload。通过后现有单卡有界 colocate_async 对照已获授权，不新增 GPU。

## 5. 下一里程碑清单

**当前只执行active-engineering-goal.md的W1—W6。以下旧M1/Harbor checklist作为历史保留，不可据此启动旧run。**

- [ ] 读v2准入设计和本检查点测试记录；远端新checkout/HEAD固定后，不沿用旧run目录。
- [ ] 从`/root/runs/dsh-redact-execute-r1-data`发布v2新目录，源manifest SHA`3e75ccb8973a5e2703a97a12ee88638ebb6e11b567dde97d836c14dc3e5c4fe0`。
- [ ] 使用生成task-config.yaml及新4/2parquet，复用redact-m1-r1-launch-manifest.json预算，新run两步；保留真实0分失败与全部拒绝明细。
- [ ] 验证非零有限梯度、真实LoRA数值变化、optimizer状态、消费审计；未过不声称更新成功。
- [ ] 独立进程reload、同预算两条公开留出前后评估；结果可能不提分，照实报告。
- [ ] Harbor新单题包从原16/8 source准备（不能传4/2派生manifest），构建新agent/verifier image并pin与归档。
- [ ] 执行新Harbor scripted正例/部分分/拒绝/篡改，再执行新spec/凭据/目录的学生验证和M2有效更新。
- [ ] 明确原生v2与Harborv1准入差异；若迁移，独立版本、测试和发布，不静默替换。
- [ ] GitHub固定commit可复建验收、最终锁与运行手册更新，G1全部必需项通过才complete。

## 6. 分支/部署状态

- 本地分支worktree-harbor-modal-integration；本次检查点commit在当前HEAD，用git rev-parse HEAD与origin核验。主目录main未修改。
- 远端`root@216.243.220.178:14465`、key `~/.ssh/id_ed25519`；RTX PRO6000。已停止的是训练进程，不代表Pod停止计费。
- GPU repo `/workspace/rebuild/uni-agent-g1-v2`已2df91d7；venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5`；模型`/workspace/models/Qwen3-4B-1cfa9a7`。
- v2数据=/root/runs/dsh-redact-execute-v2-r1-data；评分bundle SHA60f49dcb519576bbe09839371ec3220775aa42aaf5e780a7f5d843c71552ea82；训练完成后必须归档/root证据并核数值/消费，再考虑独立reload。
- `/workspace` MFS不执行chmod私有权限；凭据和运行临时目录放`/root/runs`0700。Pod更换会丢/root，因此无凭据证据归档到/workspace。
- 本地Harbor完整测试环境必须CPU site-packages优先，再Harbor site-packages；单独CPU环境缺Harbor会skip，顺序反过来会tokenizers冲突。
- push前必须ruff check .与ruff format --check .通过。CI远端状态另查，不从本地测试推断。

## 7. 冷启动 checklist

1. 先读本handoff顶部 → active-engineering-goal.md的W0—W6 → docs/harbor-modal-integration/dsh-memory-context-skills-plan.md及三份work-state review。
2. 核对git status、当前branch/HEAD、origin、VERL子模块；查远端GPU进程，不复用旧run。
3. 查看memory-resident-train-r2-result.md确认本课程之前没有可用memory训练checkpoint；不能拿context更新抵扣新课程验收。
4. 核对在制work_state模块、NativeWorkStateFramework及memory_credit合同；先补新bundle消费复核、recipe和真实DSH canary，再固定提交启动新GPU run。
5. 按W2—W6执行真实基线、完整组RL、有效更新、独立reload及人工复跑交付；每节点验证后commit/push。保持旧合同/失败证据不变，Harbor与性能后置。
6. 更早历史按需读handoff-history-20260908.md；其中running/旧地址/旧pin均为历史，不覆盖本页。

## 本次提交补充

- 新增evolution_scoring_v2.py、Task/audit绑定与24项测试：调用原固定verifier CLI，不复制准入规则。
- 新增acceptance-tracker.md、checkpoint-storage-layout.md、v1 Docker与SSH探针报告；版本锁保留GPU实际代码2df91d7，提交版本与运行版本分别记录。
- r3监管启动引号错误，未进入训练；r4已修正。下次启动应确认train.log和持续存活，而非仅PID。

### r4真实训练更新验收

- 两步梯度0.1337890625/0.2119140625；step1→2全部504LoRA变化、399base不变、张量有限；optimizer2→4且动量非零。
- trajectory audit eligible=true：10组全部准入，0拒绝、0异常消费，2个奖励方差组。
- 证据：docs/harbor-modal-integration/redact-m1-v2-r4-audit-bundle.json。GPU保持2df91d7，未同步本机新增Harbor代码。
- 独立reload：/root/runs/dsh-redact-m1-v2-r4-reload，supervisor78419，1800秒，仅评估，继承r4完整环境。未验收，不宣称G1完成。

### 独立数据会话工作包

任务委托见data-curriculum-session-brief.md：D0先24个设计样本，设计批准后A/B首批40个pilot；记忆与RSI明确接口前提，不改当前G1/GPU。当前只创建委托，尚未启动第二会话或生成数据。

### M1最终证据与M2边界

完整reload报告：docs/harbor-modal-integration/redact-m1-v2-r4-reload-result.json；训练和reload原始日志已归档到/workspace/uni-agent-g1/reports/dsh-redact-m1-v2-r4-and-reload-evidence.tar.gz，SHA见报告。该归档不含大checkpoint，checkpoint保留指定云盘路径。当前同题公开留出基线满分，未证明能力提升。

### Harbor v2完整接线检查点

新增examples/harbor/evolution_verifier_v2.py，更新executor/isolated_trial/trace_artifacts、prepare_evolution_task/prepare_m2_training/registration和scripted smoke。原三份DSH verifier源码不变。668项组合测试通过、Ruff双门通过。实际Docker v2尚待构建与四mode验收，尚未跑M2学生训练。手动说明见docs/harbor-modal-integration/manual-gpu-runbook.md。

### Harbor v2真实Docker通过

代码a17940d已同步GPU，最终TaskRef=evolution-redact-train-01/v2/sha256:3cf73f11ef23772c61c243f830e04e095914573740c52be2176c75c68716c3ef。四mode真实Docker通过：1/.25/0/篡改拒绝，分别8/7/3/8次真实DSH请求，全部清理核验通过；报告docs/harbor-modal-integration/harbor-evolution-v2-docker-r1-result.json。本轮脚本策略无GPU学生，不代表M2训练通过。GPU任务包/root/runs/harbor-evolution-v2-package-r1；本机同名包位于/private/tmp/harbor-evolution-v2-docker-r1。正在准备新controller身份与学生两步训练。

### 检查点纪律与下一阻塞

用户要求每个完成环节commit/push。Harbor v2 Docker四mode已通过，本次先保存；M2学生尚未启动。CPU启动预检发现train_m2_online_rl._hydra拒绝source_sha256s路径键，需局部修复及真实Hydra parser回归。私有准备目录/private/tmp/harbor-evolution-m2-v2-r1，deadline有时效，启动前重新核验。

### M2启动器修复

_hydra允许经过白名单校验的相对路径键；仍拒绝分隔符/插值等。66项定向测试通过，v1/v2实际prepare→build→Hydra parser回归通过，真实print-command通过。修复独立提交后更新GPU代码身份再启动。异步后续方案见docs/harbor-modal-integration/async-followup.md，未启动异步。

### Harbor学生r1已提交启动

代码be8237ed9b8d22d06bc28195441aa7a28a23a8a0，GPU/root/runs/harbor-evolution-m2-v2-r1，supervisor85930；Mac控制器69461，私有目录/private/tmp/harbor-evolution-m2-v2-r1。2steps/2700秒，4条同题工程重复train+1同题eval，n4/batch2，base Qwen3-4B新LoRA16，无SFT。checkpoint=/workspace/uni-agent-g1/checkpoint/harbor-evolution-m2-v2-r1。不能当独立泛化评估；初始化/训练验收仍待确认。

### 视觉验收与异步授权

两HTML移动端长词溢出及旧进度已修复，实际浏览器桌面/移动复验通过，45本地链接有效，console无错；报告g1-visual-audit.md。用户允许同步M2完整通过后，在已有单卡上有界colocate_async对照，无需再次确认；不改当前run、不新增GPU。

### 进行中的下一批实现

- context提示修订：只列本题存在源，完整citations.source ID；原评分不变，独立r2待部署。
- 真实学生记忆链设计native-memory-student-chain-design.md经主线程审阅，CPU实现进行中：A回执验真→freeze→独立B，先评估，不伪造跨session训练credit。

- 已结束诊断归档 `/workspace/reports/native-capability-diagnostics-r1-r2.tar.gz`（不含context r2），135398 bytes，SHA256 e99f85967faef859b1f229eaba9fe2b6f8ee2d6208f3755ae01a7cdf5903844d。

- RSI候选持久化a0aa392已推送，27新增测试通过；真实DSH overlay/canary实现中。持久选择不等于runtime已采用或学生已学会RSI。

- 固定Linux RSI canary c5acd30已通过，18真实工具请求4.66秒；独立checkout/worktree不影响GPU源码。晋升比较标synthetic，不是学生收益；报告native-rsi-policy-linux-c5acd30-r1.json。

### 最新上下文v2主线

- daa7073已推送，12train/4dev结构课程、独立v2奖励及现有RL启动接线，root30项测试通过；v1评估不改。
- GPU context-v2-exploration-r1在参数解析阶段exit2（不支持--temperature），未加载模型；修复后新run context-v2-exploration-r2，复用r1-data固定输入，16采样来自4个公开dev结构，每题4次，非trainer GRPO组。最终PID见远端supervisor.pid。
- 当前使用committed sampler配置，CLI默认温度0.8；runroot/root/runs/context-v2-exploration-r2，最长3600秒，每任务900秒。禁止更新运行中checkout；源码daa7073。

### 最新已推送实现补充

- 00e4bc5包含首个memory整链审计与HTML视觉状态；5ef4e07修复未来stage短Ray目录，尚未部署当前d3084f2链。cef2f19为纯CPU跨session credit合同，不是Framework训练接线。
- 后续context 12题完整课程覆盖计划见context-online-rl-v2-runbook.md末节；12步/n4计划48尝试，实际覆盖与有效组必须审计，不能宣称已执行。

- 最新本地/push实现：2f1995a新增Gateway实际生成版本完整性（108 CPU）；7c37cb2新增RSI配对准备/监督入口（root74 CPU）。均未部署当前d3084f2训练，不以新代码覆盖旧run身份。

### NativeMemory 接线复核：训练步数与权重版本

固定VERL sync初始化发布weight0，fit先把训练step增为1后采样；每步更新后发布该step权重，再验证。因此训练prompt step=s对应实际weight=s-1，val step=s对应weight=s。新接线必须分别记录调度step和expected_policy_version，真实generation版本仍需完整且相等，禁止缺失时补写。主线程已发现并修正原接线将二者等同的问题，固定源码时序/CPU反例和281组合回归通过，d620d62已推送。当前4168b62已包含该修复并部署新GPU checkout，真实版本合同仍待此次val检验。
