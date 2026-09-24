# 跨 benchmark 验证方案（2026-09-21）

## 当前结论与新结果

同一 eval-set-v1 78题×4次、framework resolved 口径：原版64.10%；OPD12补齐后43.27%；RL20补齐后50.96%；RL40为47.76%；RL60为46.15%。所有训练版本相对原版的配对95%区间均低于0。OPD12/RL20补测驱动于14:43:23 UTC退出0，两个aggregate的validation均complete、errors为空；各只补一次infra缺失，不重试已有有效失败。

这支持“本次12步OPD→48步RL配置在此评测预算下显著退步”，不能推广为所有OPD/RL方法无效。RL阶段分数有回升但未恢复原版；未计算OPD12与RL版本之间的直接配对区间，不能宣称回升显著。当前缺同数据/预算、原版直接起步的纯RL对照。训练批次成绩和训练后评测不可混用。

## 候选与选择

1. Terminal-Bench 2.1：最低接入成本。远端data/tb21-full/harbor_terminal-bench_terminal-bench-2-1.parquet存在，已有文档记录89题。使用eval_val_only.sh及原LoRA加载方式；旧eval_tb21.sh要求合并模型，不采用。固定2.1版本，不称最新版本（官网当前展示4.0）。终端任务可检验工具使用、环境操作和长程执行。
2. SWE-bench Verified：官方500个人工筛选实例，适合检验真实仓库issue修复。仓库已有Harbor preprocess适配入口，仍须物化、验证镜像/评分器及数据重叠；不能称已经端到端跑通。
3. EvalPlus HumanEval+/MBPP+：补充函数级代码生成控制组，用于区分基础代码能力与长程Agent执行问题。需要单独评测入口，不能当软件工程Agent整体能力的替代指标。

官方来源：https://www.tbench.ai/ 、https://www.swebench.com/ 、https://evalplus.github.io/ （本日通过gstack browse读取）。

## 最小可解释实验

- 新benchmark首轮固定原版、OPD12、RL60三模型；原有全checkpoint评测继续。三点分别识别蒸馏后的变化与RL后的变化；不按新集得分临时挑选checkpoint。
- TB2.1先做固定少量任务的环境/加载冒烟，成功后全89题×3次×3模型=801轨迹。冒烟用于验证链路，不据其分数选择任务。若去污染导致移除题目，公开子集清单和实际分母，不再称官方完整集。
- 先核对本次实际训练500题与新集的instance ID、repo及近重复。已有上游23集合去污染记录，但不等于本次独立复核。当前78题的零重叠审计不自动覆盖新集。
- 同一benchmark内固定Agent、工具、thinking、token/轮数/时间预算、采样与判分。先审计现有3000秒任务上限、3600秒沙箱生命周期与任务合约是否兼容。与官方榜单不同的运行设置必须说明。
- 基础设施失败单列，只补缺失，不反复刷有效0分。报告逐题配对差值、置信区间、tokens、超时及成本。
- 现有队列仍运行；此文为可行性方案，未新增大规模benchmark作业，也未预留/扩容GPU或提高费用上限。正式排入新全量前复核剩余沙箱额度与现有任务排期。
