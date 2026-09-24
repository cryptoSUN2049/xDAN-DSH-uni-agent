# 固定三模型跨集评测

用户2026-09-21批准：先TB2.1，再SWE-bench Verified；原版、OPD12、RL60同工具同预算；GPU0旧全checkpoint队列继续，GPU1供新队列。

## 冻结范围

| 集合 | 题数 | 每题次数/模型 | 三模型轨迹数 | 整次trial上限 |
|---|---:|---:|---:|---:|
| TB2.1 | 89 | 3 | 801 | 25200秒 |
| SWE-bench Verified | 500 | 1 | 1500 | 8400秒 |

总2301条正式轨迹，另每集合每模型固定3题×1的加载/环境探针，以及每集合1题的nop和oracle评分控制。探针只验工程，零分允许通过。Verified首轮优先覆盖500道不同题，每题1次；TB题数较少，每题3次。同一集合内部三个版本n完全相同。所有模型同样terminus-2 JSON、32K episode token、单次4K输出、50轮、T=1/top_p=1、no-thinking、并发8。保留每题自身agent/verifier时间，不用总上限替代它们。

旧3000秒trial配置不能完整覆盖TB的最长24600秒（build+agent+verifier），也不能覆盖Verified的7800秒。新外层上限分别额外留600秒；沙箱生命周期分别25800/9000秒，idle12600/3600秒覆盖长命令。资源使用任务声明，不统一加配。这里是内部同条件对照，不声称官方榜单复现。

## 数据证据

- 两套parquet与实际S2训练500题做规范化instance ID、repo、题面哈希、词7-gram Jaccard>=0.5检查，均无交集/命中。词相似度检查不等于语义和patch近重复证明。
- 每个task文件SHA在`*-audit.json`，数据/配置SHA及预选探针ID在manifest。Verified本日下载解析latest后冻结本地内容，不让后续远端latest更新改变本次数据。
- 500个Verified测试脚本均含SWE-bench `FAIL_TO_PASS/PASS_TO_PASS`和`ResolvedStatus.FULL`判定；实际nop/oracle运行收据另存。

## 启动与恢复

远端根：`/workspace/verl-uni-agent-harbor-opd-rl/runs/cross-benchmark-20260921`。

```text
python eval_benchmark_matrix.py <root>/manifest.json --benchmark tb21 --probe-only
python eval_benchmark_matrix.py <root>/manifest.json
```

前者只做TB三模型探针。后者按TB→Verified跑探针及全量，完整探针复用，不重复已有有效0分。每run只做一轮，基础设施缺失只补一次，仍不完整则阻断并留证。STOP文件只阻止新作业，不强杀已有任务。旧GPU0队列不变。

## 预算边界

15:43 UTC查询Modal：metered802.94美元、billed856.04美元。现有交接记录共享累计上限900美元，旧队列仍在消耗。已向用户确认是否调高；尚未答复前只做有界小规模验证，不启动2301条全量。不能把“用户授权评测”解释为自动上调既有费用上限。

此前短任务0.023–0.05美元/条只可作历史参考；新集合耗时/资源不同，不能用它承诺总价。当前GPU已租用，以上Modal账单不包含GPU费用。
