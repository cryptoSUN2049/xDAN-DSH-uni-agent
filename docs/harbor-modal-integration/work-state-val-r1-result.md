# Work-state GPU baseline r1：失败保留

实际运行2026-09-09 **12:05:05→12:23:31 UTC+8**；外层launch12:04:27。`work-state-val-r1`，固定源码`801083579318ed5268cc92caf45c3ce04ef6d099`，监督child214159，exit1/1125.024秒。已正常退出、GPU释放，未修改原回执。

GPU确实参与：4.06B权重、FSDP/NCCL、vLLM均实际加载，观测12:14:54 GPU53%/60968MiB。该瞬时值不是性能基准，也不代表有效训练。

| 公开开发任务 | 原始结果 |
| --- | --- |
| WS01 v1 s303 | A finished=true/eligible=false/reward0；75steps/74calls；正确view源后企图修改只读schema3→4，被权限拒；无B |
| WS03 v1 s303 | A finished=true/eligible=false/reward0；37steps/36calls；无B |
| WS05 v1 s303 | A0→冻结→B0，双方finished/eligible/fresh；A99steps/98calls、B5steps/4calls；合法低分链获准写TQ |
| WS06 v1 s303 | A finished=false/eligible=false/reward0；86steps/85calls；无B |

独立消费审计：passed=false，1组crosswalk、0 consumed groups、0 consumed rows。严格val adapter把3条失败的原始理由返回训练器，没有再用空TQ keys掩盖首因；唯一已提交链也未被消费。此次val-only，无n4训练、无梯度更新、无checkpoint。不能将A0/B0准入或GPU使用视为RL完成。

**结束语义补充纠正**：表中finished/eligible是原回执记录，不是独立证明自然结束。后续核查发现固定VERL会合并length/stop；WS01 A原始NPZ总长16384且末token非EOS。因此此前“不是token耗尽”的判断撤回；WS05的准入也须保留协议不确定性。不能恢复的原始finish_reason不补写。详见[在线协议审计](work-state-online-protocol-audit.md)。

原始摘要：[work-state-val-r1-result.json](work-state-val-r1-result.json)。完整证据远端`/root/runs/work-state-val-r1/`，失败与WS05合法低分均保留。后续按[protocol revision2](work-state-protocol-revision2.md)澄清A只做交接、可选文件非必填、索引相对路径，不改变权限/真值/评分。原生Gateway/history/结束原因另核查，尚不能只据表面行为归因模型能力。

新版`work-state-train-r2`采用固定`12902fb8849d9fdfa118686207669bbedfcfec37`、独立`/workspace/rebuild/uni-agent-work-state-r2`，12:26:17启动外层PID221508。训练入口先严格初始评估，通过后才进入最多8步RL；此文撰写时没有已验收更新。旧prepared `work-state-train-r1-data`未执行，不能再作为本次默认入口。
