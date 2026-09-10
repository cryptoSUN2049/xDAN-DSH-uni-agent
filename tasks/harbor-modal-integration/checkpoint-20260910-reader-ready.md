---
status: in-progress
branch: worktree-harbor-modal-integration
code_revision: 2f3ea8688fc384ef437a3f8d0749edfedc58b9b7
saved_date: 2026-09-10
---

# 冷启动入口：GPU 关机，reader 诊断工程包就绪

## Summary

先读 `docs/harbor-modal-integration/stage-summary-20260910.md`，再读同目录 `handoff.md` 与 `active-engineering-goal.md`。主工作区为 `.Codex/worktrees/harbor-modal-integration`。代码已推送2f3ea86；本检查点不含新训练结果。

原生核心训练真实执行16步，但优势/梯度全零；P1有效学习未完成。最新reader诊断898项CPU测试通过，未部署GPU。用户报告服务器关闭，本轮未远程探测，也未购买/启动服务器。

## Decisions Made

- DSH唯一Agent Loop；固定SDK/runtime、Uni-Agent及paired VERL，凭据不进Git。
- 先定位A写入后B不读的问题：真实A冻结一次，原/修订提示各4个独立B，同一memory字节、独立session/输出，最多16A/128B。
- 诊断不提交TQ、不更新参数。保留可信零分和未完成；证据损坏中止。view次数仅尝试，不等于取回或使用事实。
- 不盲目重跑旧全零训练；Harbor/异步/Modal/SFT后置。

## Remaining Work

- [ ] 用户提供新SSH后核 `/workspace`、模型/checkpoint/venv、GPU/MIG与进程归属。
- [ ] 固定代码2f3ea86及配对依赖，按reader runbook新prepare/check/run，一题真实canary。
- [ ] Canary通过后固定16题配对；报告失败A分母、完整B配对及原/新差值，不补成功样本。
- [ ] 有可信成功路径和奖励区分度后RL：实际消费→有效梯度→参数变化→checkpoint→独立reload。
- [ ] 同harness训练前后评估与记忆消融；不由退出码判断有效学习。

## Backup / Notes

- 本机3份证据tar共51,176,549 bytes，已重新核验SHA256。
- 新增2f3ea86源码tar，967个Git blob内容核验通过。
- 备份索引 `docs/harbor-modal-integration/stage-backup-20260910.json`。
- 模型checkpoint仍仅云盘；代码tar不包含VERL子模块内容、venv或模型。
- outputs被Git忽略，删除worktree前先迁移归档。
- 入口命令在 `docs/harbor-modal-integration/core-reader-role-diagnostic-runbook.md`。
- 不复用旧manifest/目录/IP/PID/MIG UUID；绝对PYTHONPATH必须进入实际DSH父环境。

可直接给下一会话：

> 先读 tasks/harbor-modal-integration/checkpoint-20260910-reader-ready.md 与 handoff.md。继续已批准的reader诊断，固定2f3ea86及paired VERL/DSH。新SSH为〈填入〉，先检查持久云盘/环境，再按runbook跑真实canary与16题比较。不要重复旧全零训练，也不要宣称CPU通过代表有效学习。
