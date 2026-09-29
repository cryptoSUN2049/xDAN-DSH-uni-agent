# 2026-09-29 r6 操作记录

## 当前入口

- 用户已授权继续完整 RL 闭环，并指定接管 high-performance 双 RTX PRO 6000：db7kewdkd71js6，SSH 157.157.221.177:11403。Qwen3.5-9B 服务 PID103940/104728 已 SIGTERM 退出，两卡 0 MiB 已实测。
- Mac 默认到该 IP 经过 utun4，SSH banner 超时；单次连接增加 `-o 'ProxyCommand=nc -b en0 -G 8 %h %p'` 成功。不要改全局代理/路由，不把该 Mac 参数带进云端 SSH。
- CPU controller 仍在 11621，使用既有 runpodctl SSH key；GPU 使用用户 ~/.ssh/id_ed25519。CPU controller-key 公钥已加入 GPU authorized_keys；沿用本机验证过的 host key。
- 新运行 mimo9b-001661-r6 / mimo-controller-r6 / mimo-worker-r6；冻结源码仍为 /workspace/mimo-dsh-rl-20260928/run-src-r5（f2dcac2 对应修复）。r5 未启动训练，旧 B300 86ikzxxcveon27 已 get404。
- r6 训练 driver144769 / supervisor144770 于 03:05:14UTC 启动；4800秒上限。启动不等于训练成功，读下面实时产物确认。

## 固定配置与禁止事项

- 单卡 colocate_async、CUDA_VISIBLE_DEVICES=0、RAY_ADDRESS=local、私有 /root/mimo-private/ray-r6；清除继承的 RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES。GPU1 空闲备用。
- 32K 总上下文、每次4096、episode累计生成14336、n4、2步、每步保存；DSH及数据/model revision保持设计冻结值。
- 不修改共享 uv 环境；750源码文件哈希、273freeze约束及真实tokenizer/dataset预检通过。新宿主原生IPC 1passed/0skipped，94.37s，结束后无GPU残留。
- 现有 Pod 禁止套用 owned-gpu-watchdog。CPU /root/mimo-private/shared-run-window-r6.json 只是本轮期限，不允许删除Pod。正常结束只回收本轮进程/Modal资源，保留模型与网络卷。
- 其他会话服务器 213.192.2.76 不操作。不要全局 ray stop、pkill、清空共享目录。

## 实时路径

- CPU 私有 /root/mimo-private/{run-spec-r6.json,controller-r6.log,controller-r6.pid}，controller PID90127；端口38640/38641/38642/38643。
- GPU 私有 /root/mimo-private/launch-r6/{launch.json,train.log,supervisor-result.json}；supervised-r6-driver.log / supervised-r6.log。
- 持久 /workspace/mimo-dsh-rl-20260928/runs/r6/operator/status.json；checkpoint、rollout、agent 目录从实际 launch/run 输出核实。
- 凭据、完整私有回执不得打印/提交。CPU归档helper /root/mimo-private/mimo_private_archive_r6.py，PID90337；/root/mimo-private/evidence-r6/status.json。只读GPU产物，截止shared window减60秒，不操作Pod。
- CPU与GPU准备任务哈希均603c1f65f95a2e6b89716a618713f683b1fc9072386002eb014fb9b0ccb878e2；run-spec哈希97620df9c4a7f275721ec1272e383ac6fadca5614867a24082a07e9c7412ba27。

## 审计修复与验收

- 独立审计副本 /workspace/mimo-dsh-rl-20260928/integration-check/audit-r6-source，不改变运行中的run-src-r5。
- audit_m2_training新增显式--no-validation，实际消费(step,uid)为主表，预取轨迹另列且继续校验回执/NPZ。云端RED4failed18passed；GREEN22passed。公开日志见docs同名evidence/mimo-r6-audit-tests-*。
- 必须同一步验证奖励差异、正负advantage、有限非零当前梯度，并关联实际消费receipt及checkpoint参数变化。审计passed不是optimizer通过；MECHANICS_ONLY不算验收。
- r4没有checkpoint；不要运行旧mimo-r5-resume-wrapper.py。r6真实C2产生后，用新r7 run/controller/Ray/session重载，再验证C2→C3。TQ无队列快照，不能宣称恢复在途队列。

## 下一步

- [ ] 等模型/worker初始化，核Gateway注册、DSH实际工具轨迹与独立verifier。
- [ ] 至少一个有奖励差异的实际消费组及有效更新，保存C1/C2并核adapter变化/base保持。
- [ ] r7独立重载续训并归档真实证据；清理本轮进程/沙箱，保留现有Pod。
- [ ] 汇总结果与成本、完成提交及handoff；未通过全仓Ruff双门不得push。

Goal API当前仍报告paused，工具没有resume接口；用户已在会话明确要求继续，当前工作按授权执行。不要新建重复goal或伪称API状态已active。
