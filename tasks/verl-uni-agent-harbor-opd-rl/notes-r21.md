# R21 当前r20f独立验收执行笔记

## 目标与边界

用户已授权专属双卡Pod六小时真实闭环；本笔记只记录当前新run，不把旧R19成功、CPU探针或启动等同训练成功。

- Pod vo6u0t8x398bnm，SSH157.157.221.30:51913；allocation1790791473，固定deadline1790813073，清理预留180秒。
- 当前run mimo9b-002549-r20f，W&B xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/mimo9b002549r20f。
- runtime run-src-r20/manifest99ac03f5/source1ccc164；world2/FSDP1/colocate_async/n4/sessions2/32K与273依赖不改。
- parent精确R19 C4 seal40f25db0，独立本轮目标C5。共享路径BASE=/workspace/mimo-dsh-rl-20260928，PRIVATE=/root/mimo-private。
- 私有当前日志仅PRIVATE/operator-r20f.log及PRIVATE/launch-r20f/train.log；不privateJSONglob、不输出token或隐藏test正文，不重启/并行训练/宽化门。
- supervisor11436 ticks355636029、launcher11494 ticks355649735、native11566 ticks355661221、controller10217 ticks355574636；停止前重新核PID/startticks。

## 已完成的当前前置证据

- [x] 真正生产原Python3.10.18的当前新任务校准0/0/1，独立API校准资源全部结束。
- [x] 当前六文件控制bundle6c2d5175，Gitb053bde7，完整Ruff/push完成。
- [x] 实际CPU prepare c1aba583与preflight c8aa4b6a；新Parquet be5a3e73，实际native恢复probe UID mimo9b-002549-r20f-train-0，273依赖、parent不变、source imports正确。
- [x] 当前supervise plan c2619166，nonsecret公开摘要b58992ea。

## 终态后验收计划

- [x] 当前supervisor/native真实exit0与原生C5；两rank model/optimizer/RNG/scheduler成功日志另存c3b1。data只报告冻结控制流及当前probe，不造独立成功日志。
- [x] 冻结audit_m2_training.py SHA a4ad470d：当前consumer5四唯一TQ、奖励[0,1,1,0]、实际100次generation版本均policy4，另3条未消费prefetch明确分列；报告c7b2244d。
- [x] 冻结token_journal_audit.py SHA e59c1b64：四显式session全部通过真实token/logprob/mask/NPZ重放；报告d1d42234。
- [x] 冻结sharded_checkpoint_delta.py SHA ea905588：LoRA496/716变化、760 base不变、全finite；两rank optimizer实际4→5、各992 moment tensor变化，报告941259e1。
- [x] 独立mimo_world2_acceptance_r21.py SHAc7c12a1（原33cd保留）：当前run/spec/step5/原parent40f25全hash绑定，有差异reward、正负advantage、非零有限grad、原生world2更新实物全过；新报告ac82943e。
- [x] 独立本run W&B API原生finished/唯一step5、77/77 console指标对账，无写操作；报告eb8aa042。
- [x] 当前Prom三scalar各1次真实scrape，Tempo明确时间窗154 traces、三类各1真实payload tags回读；报告5ebfe333，不复用CPUprobe。
- [x] 当前12个job的23个明确owned Modal sandbox fresh API poll全部终止，active0，f04d6585。controller10217精确SIGINT、六端口关闭、仅所属key移除/其他bytes保留，831a7631；当前Ray session无剩余所属进程，f043ea9b；没有Pod stop或全局ray stop，costguard仍在。
- [x] 当前已完成证据均以非秘密小报告归档本地evidence，4.89MB逐参数原审计及全部模型/原journal留云端；不Git/push、不改混合handoff/todo或他人dirty。后续新版复合重审报告待归档。

## 观察记录

- observed1790797568.59：四个原生owned PID/startticks身份一致；train.log166994B，最后修改1790797483.89，未见Traceback/RuntimeError/OOM/step5/terminal ack，supervisor终态及C5尚不存在。两GPU各929MiB、0%瞬时采样。仅表明初始化进行，不标PASS，也不据瞬时0%判训练失败。
- observed1790798041.84：两TP1 engine真实safetensors2/4，随后4/4完成；GPU各20380MiB。actor/ref和reward loop已初始化。
- observed1790798424：本run独立W&B API为running，关键字段scan_history0行，无任何写操作。公开报告SHA33b544298eeb8fccbea596e4875e8fbb1bb3731d3470dfe82b5dbc80d1a1eca3；此时没有step5，不能称有效训练完成。
- observed1790798510.46：当前native11566独立Ray session下十个成功证据齐全（两rank各model/optimizer/RNG/scheduler，initialstep4、fit）；原生fit19:57:34.949，两卡各41080MiB。当前新native resume报告c3b12538871c6def8622be8344fb4548c7701c57f1d0f7b7c542e274c9c67ddf，完整原始worker日志仅存云private snapshot，小公开行证据入evidence。data loader只披露冻结控制流/当前CPU probe，不编造独立成功日志；effective update尚未验收。
- 初始两job遭HTTP524、DSH error terminal，严格拒绝为evidence-rejected-after-cleanup而非reward0；纯只读冻结collector复现10908e18，明确失败组ecb73f41保留。原生之后独立采样获得有效完整组，不能将两初始失败冒充训练消费，也不能据它们判整个run失败。
- 当前native结束1790799798.88、exit0/C5、两卡0MiB；W&B finished与实体更新通过。旧复合world2工具33cd真实FAIL 871130d6，唯一已触发原因是父40f中的裸spec SHA5951与工具仅prefix格式不兼容，未放宽门或改父证据。最窄审查方案见docs/verl-uni-agent-harbor-opd-rl/r21-world2-parent-sha-compat-review.md；新独立auditor只执行已授权闭环必要的离线审计兼容修复，回归与同实物重审进行中；旧资产不动。
- C5十五个原生文件19,151,369,958B已另做完整stream SHA，latest5/world2/FSDP1/noTQ均通过，58.89秒，报告b4399b1171d0ef796d78e270b4a765457e35d449616a952be8992fa0e8f4ffe4。
- 当前联合证据2e83d5db306705bff0dece9913b13582af7357fe9ebfc3956b72ae8a68372140仍诚实passed=false/status native_evidence_and_cleanup_complete_composite_format_pending。独立只读审查确认最窄父字段格式修复；新增独立r21 offline工具与CPU回归委托prep，旧33cd/父40f/runtime99ac/旧FAIL全部保留，不修改训练生产core或启动GPU。

## 审查原则

任何constant rewards、非有限指标、LoRA未变化、缺actualstep5/当前API证据均保持FAIL或pending并反馈root。checkpoint比较证明变化，原生日志证明restore，batch证明消费，token证明语义，观测后端证明当前上报；各层证据不得互相冒充。

- 当前四条消费另经实际SQL job/request、当前Parquet/immutable instruction逐项绑定，全部新task002549，父task001661明确区分；新报告e39dc0214afb92ebc520920e6a11f3536769d4cd4191fd9d5481bbada10f9ae6已归档，仅小公开字段、不输出payload。

- 独立新offline world2 auditor c7c12a1d7226d54e9cf1342ac2b1920c7150f90b53a84de0a622b1f58009b3db 与旧33cd严格仅父spec正则一行差异；云CPU181tests通过、coverage98.68%、Ruff双门通过，测试报告e0da0d97已实读。1790802919.323起，对原40f/C4与当前C5执行全hash复合重审，新O_EXCL输出r20f-world2-acceptance-r21.json，cpu_only=true；尚未将此运行标PASS。

- 1790803032.823：新独立审计对同实物执行113.5秒，exit0/effective_update_verified=true，复合报告ac82943ebc59464329bc3822efed914e6b1ee095c01a5f535f91cf6ef839fee0；源c7c12a1/test e0da0d97逐SHA核验，旧33cd与父40f字节未改。
- 最终联合验收r20f-current-joint-acceptance.json SHAe02da33777c32b86bc0c73498061767e1f7cc483f0f77b69010c70f73d7a60dc，新O_EXCL/read-all-reference-SHA核验，19项当前门全过。旧pending2e83/FAIL8711/524ecb7保留。仅新002549一次有效更新，无heldout/五域配方/模型forward概率重算/inflight TQ恢复能力声明。所有小公开回执已归档；模型/逐tensor原审计/private仍云端。

- 最后轻量资源读1790803297.976：costguard5571/ticks355278877与encryptedbackup8370/ticks355382868仍精确存活，两GPU各0MiB/0%，Pod未stop，固定截止1790813073没有重置。当前训练已完成而非后台继续运行；后续课程须另由root明确绑定新parent/run，不冒用本run。
