# Lessons：verl-uni-agent-harbor-opd-rl

1. **venv 不能建在 pod 本地盘。** 2026-09-16 发现之前通过 GPU 组件验证的 venv 在 `/tmp`，pod 重建后全丢，只剩 freeze 和 cache。规则：venv / cache / 模型 / 证据只放 `/workspace`，脚本层面拒绝其他路径（`uv-lane-bootstrap.sh`）。
2. **每个 GPU lane 的 freeze 必须进仓库。** 远端 `runs/` 里的 freeze 是唯一幸存物，如果它也在本地盘就全没了。规则：每次改依赖后 `uv pip freeze` 覆盖 `deployment/versions/uv-lanes/<lane>.freeze.txt` 并同提交。
3. **SSH 端口随 pod 重建变化。** 12524 → 30284。规则：handoff 里写端口时标注日期，冷启动第一步先核。
4. **交接文档放 `docs/<worktree>/tasks/`，不放根目录 `tasks/`。** 旧位置的 handoff/notes/memory 已 git mv 过来。
5. **跨项目的运维办法要"继承"而不是"引用"。** 用户明确要求把 MetaRSI 的 uv 管理办法搬到本项目并按本项目路径落地，链接过去不算完成。
