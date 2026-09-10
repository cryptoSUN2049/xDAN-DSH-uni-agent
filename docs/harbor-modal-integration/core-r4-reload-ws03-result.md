# Core r4：WS03 独立reload结果

已完成原511环境的正式after_run母来源/文件hash复核与消费审计：两项均通过。run `core-r4-reload-ws03-r1`，task `work-state-memory-core-v1-ws03-v1-s2001`，记录时间2026-09-10T07:55:01.388442+00:00。进程exit0、490.014秒；CPU核验禁CUDA/线程1，未操作GPU或清理并行WS05运行。

## 加载与母工件

实际加载 `/workspace/uni-agent-g1/checkpoint/core-train-r4/global_step_16`；不仅根据配置推断。train.log第1114行记录Resuming/global step16，第1119/1120行确认model/optimizer，第1123/1124行确认rng/lr_scheduler。原文及完整日志hash见JSON。

`check(manifest, after_run=True)`重新计算checkpoint_origin并与准备时逐字典比较通过；母run/plan/dataset与checkpoint文件清单均保持原摘要。绑定checkpoint identity：`sha256:59e06b5d333cecb528e8171f44ccb074ef376b362f5c4ecc7fee877c55b0529b`。此核验不意味着本次再次独立证明训练参数发生变化。

## 真实A/B与唯一消费

chain `memory-fe6496c47acd4487803bc54c3b0e8826`，A/B均fresh=true、finished=true、eligible=true，原reward均0。消费审计passed=true、consumption_verified=true：1个val组、2条唯一A/B消费，dump uid与crosswalk.tq_key集合精确相等，目标task身份匹配，无未知/重复/交叉消费。此题是n1公开dev，不是封存效果测试。

实际输出 config 的 encoder/transport/storage 为 catalog_option_1/2/3，均不是本题合法候选ID；plan=[]合法。目标组合为 encoder=option-c、transport=option-b、storage=option-d。业务失败如实保留，不把进程/消费通过称为任务成功或能力提升。

## 原始证据与持久化

正式报告原位置 `/root/runs/core-r4-reload-ws03-r1/final-audit/`；after-run-check.json、consumption.json以及整合result.json已复制/保存到 `/workspace/reports/core-r4-reload-results/ws03/`。这里只持久化审计摘要，尚未打包该reload的全部原始轨迹。母训练归档不含本reload。

本地JSON收录原审计/回执/crosswalk内容、全部关键原件路径/hash、加载日志行、实际产物和validation身份。以下为关键源文件SHA256：

| 文件/角色 | SHA256 |
|---|---|
| after-run-check.json | `sha256:6e8f94f9584083f549b4dc23abdc5e65a229e7cf3c5d3088ea256bc36aba3e4b` |
| consumption.json | `sha256:23403539a4b5f0ca6fa5bea10ccf1f3fc800f2daeb4511b01f0bd774117a91f5` |
| prepare_manifest | `sha256:ef57e9e58addc650d230a8579c86365cf0ff14a4eaceabd676917bb3e54ef7e6` |
| checkpoint_origin | `sha256:5379213a01c75f83d0efad633b7f78d199dcda9e7e6b064ff30f6aa5aa076589` |
| run_manifest | `sha256:1eb2a262ea300a3de3217605c3d2799e71fb6bf586d70461f70fc138ea8a35ae` |
| supervisor | `sha256:28444cb3d7cfcc518b56cd72a25b1bcab368283da3259c30f779ec5a442048df` |
| train_log | `sha256:643a4073eeeda354833a0411c88d6e33f9a97e1b494dd6a1f4fcdc5ce7a3c596` |
| validation_dump | `sha256:4ddb9c5abdd8fe6020ac75d7033e24076edc115bf7a05fbc54d71c46eb93364e` |
| crosswalk | `sha256:800712db423bc597099c360bab608fb0cd0a33de20276ce078ea3c431154ce26` |
| frozen_bundle | `sha256:7a0ec75158ae51cf7d353574ddaf7e4935995ce12e8ff6a7a889ab1a2b5b672c` |
| frozen_manifest | `sha256:3162ef26722c20ab18d20ff82c7d382508b0beee19339a7aab0f9be5d12a5af1` |
| writer原receipt | `sha256:b43e3b312edb43455d973cf00d71a254bfc7506b18b3db62252e40f388fb35c3` |
| reader原receipt | `sha256:924d37b1e2d4199a082bc9319daf24ffcd7f4c8808d63e443eb30e2c79626655` |

执行源码、母checkpoint、DSH/VERL、数据和预算沿原511清单校验，没有采用尚未部署的累计生成token预算修复。`fresh/finished/eligible`通过与业务reward0并存；不改变原奖励或完整消费合同。
