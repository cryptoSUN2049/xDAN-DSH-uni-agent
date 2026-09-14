# 离线恢复入口回归 — 2026-09-14

在无 GPU、无远程 SSH 的条件下完成的可复现性检查：

- `bash -n deployment/bootstrap/*.sh deployment/diagnostics/*.sh`：通过。
- `bash deployment/diagnostics/reader-diagnostic.sh --help`：通过，未设置运行环境时可安全退出并显示用法。
- `deployment/versions/g1-deployment-lock.json`：JSON 可解析，DSH、Harbor、student 和 VERL revision 均存在。

该检查只证明脚本入口和锁文件完整，不证明 Linux 依赖安装、CUDA、DSH runtime、Gateway、真实任务或 RL 更新。GPU 恢复后仍须按 `stage-backup-20260914.md` 执行 canary 和训练验收。
