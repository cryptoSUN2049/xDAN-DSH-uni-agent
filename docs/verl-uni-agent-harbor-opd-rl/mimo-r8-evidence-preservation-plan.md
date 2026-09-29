# r8 私有证据保全方案

状态：主线程已批准并完成独立 helper。CPU 29 项测试通过，行覆盖率 86.650%、分支覆盖率 72.674%、合并覆盖率 82.534%，Ruff check / format check 通过；真实单次保全已验证。主线程 review 后批准启动 30 秒 watch，CPU PID 99526。训练源码、运行进程和 Pod 保持当前状态。

## 已确认缺口

- CPU 上 `mimo_private_archive_r7.py` 的 `validate_job` 只接受 `dsh.harbor-verifier-receipt.v1` 且 `finished=true`。r8 使用 v2，预算终态保留 `finished=false`。
- 旧 `collect` 一旦记入 `completed[job_id]` 就跳过该 job。即使放开 schema，它仍会漏掉回执之后创建的 `admission-chain-N.json`、`dump-chain-N.json`。
- Framework 先保存私有 dump binding，再通过临时文件替换发布 `trajectory.npz` 和 `trajectory.json`。出现 dump binding 不代表 NPZ 已落盘；三者须逐字节核对。
- GPU 私有 launch 根为 `/root/mimo-private/launch-r8`，权限已只读确认为 `0700`；首查时 artifacts 目录尚不存在。持久卷 run 根是 `/workspace/mimo-dsh-rl-20260928/runs/r8`，实际 agent-log 子路径应从固定 operator 配置指定。

## 最小接口

独立 stdlib operator helper，不导入训练框架，不修改活跃 source：

```python
collect(launch_root, agent_log_root, run_id, previous_file_hashes) -> snapshot
archive(snapshot, private_destination) -> report
```

`snapshot` 包含有界原始 bytes、每文件大小/SHA256、原始绝对路径与 job 阶段。所有内容通过 SSH 私有管道传输，控制台只显示计数、摘要和错误码。

固定 allowlist：

1. launch JSON、训练/验证 Parquet、当前 run 的 registration receipt；排除 `task.yaml`、凭据、环境变量与整份训练日志。
2. job 的 request/manifest/receipt 与 manifest 明确列出的 object artifacts。
3. `admission-chain-<nonnegative integer>.json` 和 `dump-chain-<nonnegative integer>.json`。
4. 固定 agent-log 根中与上述 context 对应的 `trajectory.json`、`trajectory.npz`；不跟随任意 receipt 路径。

每轮都扫描新文件。旧文件如内容变化则冲突，不能覆盖；不能仅凭 receipt hash 将 job 永久封顶。

## 隔离与完整性

- CPU 目标 `/root/mimo-private/evidence-r8`：所有目录 `0700`、所有文件 `0600`；拒绝符号链接、硬链接、路径穿越、非常规文件及非 owner 文件。
- 文件读取前后比较 inode/stat/大小/时间，校验字节数和 SHA256；源写入中的文件标为 pending，下一轮重试。
- 私有源文件仍要求原有私有权限。网络卷上的 NPZ/JSON 可以按其实际 owned regular-file 权限读取；不得为了归档改变活跃训练文件权限。
- 先写私有暂存文件，fsync 后发布；重复复制只允许原始 bytes 相等。保留 immutable 原始证据，不格式化 JSON、不重算并替换原有签名字段。
- request、manifest、receipt、Gateway proof、admission 和 dump 的绑定仅用于 transport 完整性检查；归档器不产生训练准入结论。
- 阶段区分 `candidate`、`admitted`、`dump_complete`、`pending`。最后一项必须同时满足 metadata 摘要、NPZ 摘要以及对应私有 binding，不能用缺失文件代替失败证据。
- 循环使用明确截止时间、单实例锁、单次 SSH 超时和有界文件/总量；退出只停止归档器，不停止 trainer，不删除 Pod。

## 路径迁移限制

原始 launch、trajectory metadata 与 MiMo binding 中包含固定绝对路径。CPU 私有归档必须记录这些路径并原样保留 bytes。不能通过修改原始 receipt、metadata 或 launch 来伪造离线审计通过。

后续离线审计可在隔离 namespace/container 中挂载同绝对路径的只读恢复视图；若 CPU 主机上对应路径没有冲突，也可由 operator 显式创建同路径恢复视图。此步骤独立于 transport helper，不能修改原训练目录。

## CPU 回归

- v2 自然完成与预算终态均可原字节归档；不把 `finished=false` 改成 true。
- receipt 先到、admission 后到、dump binding 先于 NPZ、多个 chain 分批出现时均不会提前封顶。
- 缺失/不完整 NPZ 为 pending；伪造 metadata/NPZ 摘要、重复路径内容冲突被拒绝。
- 路径穿越、symlink/hardlink、越界大小、源文件读取中改变、目标权限错误均被拒绝。
- 目标逐文件 SHA 与源一致；没有凭据进入 allowlist，状态报告不输出原始私有内容。

本方案不构成 r8 已完成更新、checkpoint 或续训验收的证明。

## 实现与验证

- Operator 脚本：`mimo-evidence-transport.py`，仅 stdlib，CPU 接收端通过 SSH 将相同公共脚本作为只读 reader 执行，不在 GPU 落脚本。
- 测试：`tests/uni_agent/deployment/test_mimo_evidence_transport.py`。初始 13 项 RED 已保留；首轮实现 14 passed / 4 failed，失败是 fixture 中间目录 0755 被正确拒绝；修正 fixture 为真实私有目录后，最终 29 passed。
- CPU 隔离快照：`/workspace/mimo-dsh-rl-20260928/integration-check/archive-r8`；固定 uv 解释器和独立 coverage 工具，未修改共享环境。
- 真实单次复制：CPU `/root/mimo-private/evidence-r8`，33 文件共 726,697 bytes；2 个完整 dump 链包含 2 NPZ / 2 metadata，1 个正在生成的 job 为 pending。逐文件哈希差异 0，目录 0700 / 文件 0600 权限差异 0，无 source_missing。
- 截止固定取 `shared-run-window-r8.json` 的 `deadline_unix - 60 = 1790674027.546294`。30 秒循环只能停止归档器；没有 Pod 删除、训练停止或源码部署接口。
- 已确认的新 5 小时训练授权不改变 r8 的内存截止；本 archiver 保留原 r8 截止。后续 r9 使用独立 run ID、目的地和归档进程，不能覆盖 r8 身份。
- 本地与远端源码 SHA 相同；测试原始日志、覆盖率及精确摘要存于 `evidence/archive-r8-20260929/`。私有轨迹与凭据不进入 git。
- 提交前另在 `integration-check/archive-r8-project` 显式载入当前 `pyproject.toml`，Ruff check / format check 再次通过，2 文件未改变；相同 29 项 CPU 回归再次通过（0.61 秒），不重复计为 58 项。运行脚本 SHA 仍与待提交版相同。
