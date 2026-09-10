# Core r4：WS01 独立reload结果

已完成原511环境的正式after_run母来源/文件hash复核与消费审计：两项均通过。run `core-r4-reload-ws01-r1`，task `work-state-memory-core-v1-ws01-v1-s2001`，记录时间2026-09-10T07:37:50.349415+00:00。进程exit0、535.015秒；CPU核验禁CUDA/线程1，未操作GPU或清理并行WS03运行。

## 加载与母工件

实际加载 `/workspace/uni-agent-g1/checkpoint/core-train-r4/global_step_16`；不仅根据配置推断。train.log第1124行记录Resuming/global step16，第1129/1130行确认model/optimizer，第1133/1134行确认rng/lr_scheduler。原文及完整日志hash见JSON。

`check(manifest, after_run=True)`重新计算checkpoint_origin并与准备时逐字典比较通过；母run/plan/dataset与checkpoint文件清单均保持原摘要。绑定checkpoint identity：`sha256:59e06b5d333cecb528e8171f44ccb074ef376b362f5c4ecc7fee877c55b0529b`。此核验不意味着本次再次独立证明训练参数发生变化。

## 真实A/B与唯一消费

chain `memory-8410865727564b128bddfe4f5bf24f81`，A/B均fresh=true、finished=true、eligible=true，原reward均0。消费审计passed=true、consumption_verified=true：1个val组、2条唯一A/B消费，dump uid与crosswalk.tq_key集合精确相等，目标task身份匹配，无未知/重复/交叉消费。此题是n1公开dev，不是封存效果测试。

实际输出 config={capacity:100, schema_version:1}，plan=[config.json]；目标配置2869/8，合法计划应覆盖build_schema/build_cache后switch→verify→finalize。业务失败如实保留，不把进程/消费通过称为任务成功或能力提升。

## 原始证据与持久化

正式报告原位置 `/root/runs/core-r4-reload-ws01-r1/final-audit/`；after-run-check.json、consumption.json以及整合result.json已复制/保存到 `/workspace/reports/core-r4-reload-results/ws01/`。这里只持久化审计摘要，尚未打包该reload的全部原始轨迹。母训练归档不含本reload。

本地JSON收录原审计/回执/crosswalk内容、全部关键原件路径/hash、加载日志行、实际产物和validation身份。以下为关键源文件SHA256：

| 文件/角色 | SHA256 |
|---|---|
| after-run-check.json | `sha256:c72cb65175506ca6c2e69336dfe54d83f7a10c65d2184038bcd9d2276407a4f0` |
| consumption.json | `sha256:e8b24fd9c6c12cc241dd31b07107f02ccf0a18e29635483e00faf023cfdb218f` |
| prepare_manifest | `sha256:e8cdd90b83563075586a4144f9916f7ba77cd6ad1235c97bc57d2b4eef5a66d1` |
| checkpoint_origin | `sha256:5379213a01c75f83d0efad633b7f78d199dcda9e7e6b064ff30f6aa5aa076589` |
| run_manifest | `sha256:4c7ea04a466adc810395760d6413225a46faca103811d42d317b06e18384aa34` |
| supervisor | `sha256:ea858fe545ccd882e140a9bbe957f9b3be910222efca3824bb6fb93c676539aa` |
| train_log | `sha256:722b07ace1f0832179a923c1e08be56aa38cdb04a2c175508e0bbe8a1364464f` |
| validation_dump | `sha256:93f8948850bce1bdfbf44c22efb44f82df22d60785782e94041786f74479b07a` |
| crosswalk | `sha256:99e98d592d50277463d67b60a369075c897e20d63a6daa3e75841558da0c3955` |
| frozen_bundle | `sha256:658913bf3ca402ff8c4ecafe559a0bb9b554aabda6545343597ac7a8d1ce56f0` |
| frozen_manifest | `sha256:cc31a963c048d8288bf2bb517d5a178939c773663eefb66e45c1f4ae0f259a5d` |
| writer原receipt | `sha256:b394bfede05c807dd1c7652469750c55a96f5db8bd5884b01be59cb28b28659a` |
| reader原receipt | `sha256:51b6f4597a9f01a86025dfae1a7b64bd778d5f75d5c5df8e74f9a195bdc02972` |

执行源码、母checkpoint、DSH/VERL、数据和预算沿原511清单校验，没有采用尚未部署的累计生成token预算修复。`fresh/finished/eligible`通过与业务reward0并存；不改变原奖励或完整消费合同。
