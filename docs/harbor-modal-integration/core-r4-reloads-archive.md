# Core r4 reload 与参数审计归档

2026-09-10完成。归档 `/workspace/reports/core-r4-reloads-and-parameters-20260910.tar.gz`，834,802 bytes，12,228个文件，SHA256 `318c95e9f50fbc2b689534896dabb5c6141dbfc04f6023727ac3cd0cc84e0b68`。

覆盖四个已终态 `core-r4-reload-ws01/03/05/06-r1` run目录及 `core-train-r4-parameters` 审计目录。包含原失败报告，WS06没有被改成成功。跳过符号链接及training.env；不含prepare目录、checkpoint和活跃core-budget-val-r1，不是从零部署的完整独立安装包。

在归档创建后逐成员读取，验证SHA256和成员集合，再复读源文件确认未变化。旁置清单 `core-r4-reloads-and-parameters-20260910.tar.manifest.json`；核验摘要 `core-r4-reloads-and-parameters-20260910.tar.verification.json`。这与母训练先前的归档互补。

复查可在云端使用 `sha256sum /workspace/reports/core-r4-reloads-and-parameters-20260910.tar.gz`。恢复时解包到新证据目录，保持实验根目录不被覆盖；模型checkpoint仍按既定 `/workspace/uni-agent-g1/checkpoint/core-train-r4` 路径保存。

归档校验只证明证据持久化完整，不代表业务任务成功、有效学习或完整复现验收通过。
