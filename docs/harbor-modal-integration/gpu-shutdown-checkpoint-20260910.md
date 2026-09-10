# GPU 关机前检查点 · 2026-09-10

## 已保存

- 新预算修复执行源码`5e6b326885fa7d881f7aab987fa205e9f0ed7552`；当前文档分支worktree-harbor-modal-integration，GitHub cryptoSUN2049/xDAN-DSH-uni-agent。运行checkout不随文档commit升级。
- 三条预算val作业均终态，无新作业发起。normal-r1 exit0，A/B正常完成且1组2条消费；业务reward0，无参数更新。
- 云盘归档 `/workspace/reports/core-budget-evidence-20260910.tar.gz`：1,326,794 bytes，7,025源文件逐成员哈希核验且源未变化。SHA256 `b3eb67fe4d57f1a0f0bc7e1233aeab88238f55b9848702d7effd38b5c33ac3bb`。含三个run、准备资产及审计报告；排除3个training.env。不包含checkpoint，这三条均val。
- 归档内`archive-manifest.json`含逐文件hash；旁证`/workspace/reports/core-budget-evidence-20260910-verification.json`。
- 母训练归档 `/workspace/reports/core-train-r4-engineering-evidence-20260910.tar.gz`，SHA256 `0a0f6826ae28fe2bd40a448e89055ae921f601b2f6c2c39d5cb5d142cffff54c`。
- 四族reload与参数审计归档 `/workspace/reports/core-r4-reloads-and-parameters-20260910.tar.gz`，SHA256 `318c95e9f50fbc2b689534896dabb5c6141dbfc04f6023727ac3cd0cc84e0b68`。
- 母checkpoint `/workspace/uni-agent-g1/checkpoint/core-train-r4/global_step_8`与`global_step_16`仍在云盘；母训练16步全零任务梯度，不是已提升模型。

## 下次恢复顺序

1. 获取新SSH地址，确认同一网络云盘挂载到/workspace；不要把旧IP/PID当当前机器身份。
2. 先读tasks/harbor-modal-integration/handoff.md和active-engineering-goal.md，再核上面归档SHA、模型、venv与checkpoint存在。
3. 复用 `/workspace/venvs/uni-agent-rebuild-cf2d3f5`。解释器位于 `/workspace/tools/uv-python/cpython-3.12.3-linux-x86_64-gnu/bin/python3.12`；不要仅凭/root临时解释器丢失就重装全部依赖。
4. 核新GPU/MIG/CPU配额和进程所有权，按gpu-reconnect-runbook.md、pod-recovery-design.md恢复宿主依赖；旧MIG UUID不能照抄到新卡。
5. Git获取本分支文档；需要复跑原预算实验时固定5e6b326与配对VERL overlay。归档用于取证，恢复解包到新的审计目录，不覆盖已有/root/runs。
6. 新训练/评估必须重新prepare新run身份及环境文件，再check/launch；不能直接重用包含旧绝对路径、MIG配置或旧目录的manifest。环境变量/密钥重新注入，不从Git恢复凭据。
7. 下一业务工作是零奖励分层诊断，reader配对设计尚待明确批准。不要盲目重复16步全零训练，也不启动Harbor/异步支线。

当前GPU上的/root/runs可随容器消失；上述云盘归档是恢复证据入口。GitHub保存代码/文档而非模型权重。预算修复通过不等于P1有效学习已完成。

## 已完成本机第二份证据备份

三份tar均已下载到本worktree的`outputs/gpu-shutdown-20260910/`，每份SHA256与上述云盘归档一致，总计51,176,549 bytes。`outputs`被Git忽略，原始轨迹不推送GitHub；本地路径/hash清单见gpu-shutdown-local-backup-20260910.json。即使容器已关闭仍可离线取证；checkpoint未下载，仍需保留网络云盘。不要误删此worktree的outputs，除非已迁移该备份。
