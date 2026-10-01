# R21 当前 r20f 真实训练验收

当前新 run `mimo9b-002549-r20f` 已原生正常结束并保存 C5，下面各层使用本轮实物和后端 API 取证。独立复合格式兼容审计也已对同一批实物通过，最终[联合验收](evidence/r20f-current-joint-acceptance.json)19项门全部PASS（SHAe02da337），旧FAIL继续保留。

## 训练与实物

| 验证层 | 当前真实结果 | 本地小报告 |
| --- | --- | --- |
| 任务身份 | C4父任务001661；本轮新Parquet和四条消费job全部002549 | [实际消费任务绑定](evidence/r20f-actual-consumed-task-binding.json) |
| 原生恢复 | 两rank各model/optimizer/RNG/scheduler成功；初始step4后进入fit | [原生恢复](evidence/r20f-native-resume-proof.json) |
| 四轨迹消费 | consumer step5，四唯一TQ；奖励[0,1,1,0]；实际generation均policy4 | [实际batch](evidence/r20f-final-batch-audit.json) |
| Token语义 | 四个明确消费session，真实token/mask/有限logprob与NPZ逐项一致 | [Token审计](evidence/r20f-consumed-token-audit.json) |
| 参数与optimizer | 496/716 LoRA变化，760 base不变；全finite；两rank optimizer4→5，各992 moment tensor变化 | [实物更新摘要](evidence/r20f-native-checkpoint-summary.json) |
| checkpoint | C5实际15文件完整SHA，19,151,369,958字节；world2/FSDP1/latest5 | [Checkpoint文件](evidence/r20f-native-checkpoint-files.json) |
| W&B | 本run API finished/唯一step5，77/77 console指标一致，无审计写操作 | [W&B API](evidence/r20f-wandb-final.json) |
| Verl Insight | 当前原生ack、Prom三scalar实际scrape、限定窗口Tempo154条trace | [真实观测](evidence/r20f-native-observability-final.json) |
| 原生退出 | supervisor exit0/training-exited | [Supervisor终态](evidence/r20f-supervisor-result.json) |

当前梯度范数0.1611328125，policy loss -0.2480442225933075，advantage min/max ±0.8660238981246948，reward mean0.5。检查内容包含有效非零更新，不能仅以global step增加判成功。

## 失败保留与复合审计

最初两个job遭HTTP524，严格拒绝为非budget错误，没有纳入reward或本轮消费。之后原生独立采样的完整组通过。[初始失败报告](evidence/r20f-http524-terminal-failure.json)保留。Cloudflare origin等待超时是与错误结构一致的推断，未经独立请求耗时测量，不作已证明根因。

旧复合world2工具SHA33cd6593要求父spec SHA带`sha256:`前缀；不可变父manifest40f25中的同一字段是严格裸64位SHA。[旧FAIL](evidence/r20f-world2-acceptance.json)保留。独立新工具只兼容此父字段的两种严格表示，训练runtime99ac、父manifest、checkpoint、既有审计工具全部不改，详见[独立审查](r21-world2-parent-sha-compat-review.md)。独立新版c7c12a1已通过181项真实云CPU回归，覆盖率98.68%；再次对原40f/C4与当前C5完整文件SHA和更新实物审计113.5秒，exit0/effective_update_verified=true。[新复合PASS](evidence/r20f-world2-acceptance-r21.json) SHAac82943e；[测试回执](evidence/r21-world2-parent-sha-compat-test-report.json) SHAe0da0d97。训练/父checkpoint未变，旧审计FAIL不被改写。

## 资源与结论边界

本轮12个job的23个所属Modal sandbox已经fresh API终态查询，active0。精确当前controller退出、六专用端口关闭、仅本轮SSH授权行移除、其它字节保留；当前独立Ray session无所属残留进程。没有全局ray stop或提前stop Pod。[Modal终态](evidence/r20f-modal-terminal-api.json)、[控制资源](evidence/r20f-owned-control-cleanup.json)、[Ray资源](evidence/r20f-owned-ray-cleanup.json)。固定预算截止1790813073（2026-10-01 00:04:33 UTC），costguard保持。

这些证据证明固定DSH+Harbor+Modal+双GPU原生verl的一次新任务有效更新闭环。它们不证明未见任务泛化、五域MiMo完整配方复刻、模型能力整体提升、原始model-forward logprob重算或inflight TQ恢复。4.89MB逐参数审计、模型、私有token journals和原始trace仍在云端；Mac只有小公开摘要。
