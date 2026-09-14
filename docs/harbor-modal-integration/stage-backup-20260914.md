# 阶段性备份 — 2026-09-14

## 当前定位

- Worktree：`harbor-modal-integration`，分支 `worktree-harbor-modal-integration`。
- HEAD/远端：`9797c4e30fa9f38c84a9f06d9f772ef614f81552`，本地与远端一致，工作区干净。
- 固定版本：DSH `0.1.3a2`（`b2369692ea`）、VERL `fefb0802` + overlay、Qwen3-4B revision `1cfa9a7`。

## 已确认

- 原生 DSH→Uni-Agent→VERL/RL 的代码、部署脚本、诊断入口和证据合同已保存并推送。
- 历史 GPU core-train-r4 能完成消费/reload，但优势、梯度和 LoRA B 全为零；因此尚无有效学习证据。
- reader 配对诊断的实现、CPU 历史回归（898 passed、90% 覆盖率）及 runbook 已保存；当前临时 CPU 环境已失效，不能重新声称该结果为实时结果。
- 旧 RunPod 已关机；本检查点没有新的 GPU SSH、训练进程或新鲜 GPU 证据，不能宣称 P1 完成。

## 恢复顺序

1. 读取本文件、`tasks/harbor-modal-integration/handoff.md`、`tasks/harbor-modal-integration/active-engineering-goal.md`。
2. 获取新 GPU 地址后检查 `/workspace` 持久卷、venv、模型、checkpoint 和 CUDA/进程；先验证资源身份。
3. 按 `deployment/bootstrap/` 完成固定版本恢复，运行 `deployment/diagnostics/reader-diagnostic.sh prepare/check`。
4. 先运行 1 题真实 reader canary，再扩展固定配对诊断；记录 fresh manifest、session、receipt、reward、消费、梯度和 checkpoint。
5. 只有出现非零且可归因的有效更新，并通过独立留出评估，才推进 P1→P2。

## 证据边界

历史测试、CPU 合成工件和进程退出码不能替代真实 GPU 训练证据。任务失败应记录并继续；仅轨迹绑定、版本漂移、数据损坏或数值异常等完整性故障才停止训练。
