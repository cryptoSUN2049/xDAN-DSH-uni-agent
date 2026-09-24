# 当前验收与下一次启动条件

2026-09-15，代码节点9143d95；PR #3已合并。此表区分代码、组件与完整训练。

| 要求 | 已有证据 | 未完成部分 |
|---|---|---|
| Uni-Agent/VERL配对与Teacher接线 | 固定a9f2985，CPU Teacher/TQ/loss合同 | 真实Teacher参与完整GPU训练 |
| Harbor/Modal执行 | 可选后端、Controller入口、任务准备代码；真实两个sandbox命令及清理 | 正式DSH镜像发布/拉取、完整Trial/verifier |
| LoRA实际更新/导出 | 4B r2真实144 adapter更新、base不变、merged导出及恢复 | 9B目标模型复验 |
| 保存/独立恢复 | r3保存10个文件；r4新进程model/optimizer精确恢复并继续更新 | trainer/data/TQ恢复与独立rollout加载 |
| 全异步训练 | separate_async recipe、生成版本证据门 | 双卡实际rollout与训练并行、更新发布 |
| 高性能 | 已避免base-only错误，使用merged完整权重同步 | adapter-only增量同步实现及吞吐/成本测量 |
| OPD与任务奖励 | 原生CPU hybrid梯度相加、工具mask测试 | 多角色GPU、真实Teacher+Harbor reward更新 |

## 当前选定方案的启动准备（不是已证实的故障归因）

1. 双卡SSH与型号/显存。当前唯一已核硬件是单张RTX PRO6000 96GB；不能虚增Ray GPU数。双卡先做纯separate_async RL；当前独立Teacher hybrid需要第三GPU角色。
2. 验证 Modal sandbox 到 Gateway 的可达路由。当前自建 Controller 选择了 HTTPS hostname + named Cloudflare Tunnel，因此该实现需要相应配置；这不是 Modal 平台必须使用专用域名/Tunnel 的证明，也未通过实际失败证明是训练卡点。先审查可复用入口及更简单的部署路径。其他项目 Tunnel 不直接复用。
3. 可拉取的DSH任务registry image@digest及真实runtime校验；现有本地image ID不能当registry manifest digest。
4. 用现有prepare_t2_task→冻结RunSpec/policy→prepare_m2_training生成私有launch/data；再用真实模型执行合并后的--preflight-only，检查有效rows及绝对step/epoch。
5. 注册/Worker/Ingress实际连通后进行训练；真实group/receipt/TQ/梯度/发布/新session数值及最终checkpoint一起留证。

## 本轮观测限制

本地/private/tmp搜索未找到可复用launch.json/train.parquet。对远端独立目录的两次SSH读取均在banner阶段超时（含沙箱外重试），因此**远端文件是否存在、GPU当前占用均未被本轮确认**。不能把观测失败当作服务器停止或作业终止，也不应声称远端没有这些文件。

上一成功观测中save-r3/resume-r4均结束且GPU compute-app为空；它仅是历史观测。下次连接恢复后先查PID/结果/目录，再启动，不重跑已经完成的组件验证来代替缺失的端到端实验。

此前曾将双卡/域名缺失合并判为阻塞并将平台 goal 标为 blocked；域名部分归因证据不足，现予纠正。总目标未完成；先恢复运行观测、准备真实训练输入并验证路由，不再将提供专用域名作为唯一恢复条件。单卡不能验收 separate_async 分卡并行，但不能据此否定单卡 colocated 训练验证。
