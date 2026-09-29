# 2026-09-29 r6 操作记录

## 最新：r6 终态与 r7 fresh 重跑

- r6已停止：driver exit1、trainer -15，supervisor因主动停止controller后的health failure清理；无checkpoint、无optimizer更新。前三条同组completed轨迹奖励0/1/0已准入，但第四条max-tokens使完整组失败，不能拿前三条拼成功。
- 两条失败轨迹累计生成均恰为14336；末轮分别24495+119=24614、28513+125=28638，总上下文尚未满。第四条独立verifier实际得1，仍因未正常结束严格拒绝，未修改准入合同。
- r6 6jobs：3succeeded、3cancelled；11Modal都有显式终止后的poll137证据（不代表OOM）；GPU进程已消失。122份CPU私有文件共3497246字节保存在/root/mimo-private/evidence-r6/cpu-jobs；GPU端3可信receipts等34文件已归档。archiver90337已停，Pod保留。
- r7是fresh retry，不是resume：复制run-src-r5为run-src-r7，加入已提交审计修复，仅将累计生成预算14336→20480，32K上下文/4096单次/n4/完成门保持。云端RED5failed49passed，GREEN54passed；755文件/273约束及真实数据预检、原生IPC通过。controller91543、driver172394、归档91558已启动；尚无有效更新证据。
- r7源码对应8b3f7ac，manifest在integration-check/source-r7-manifest.json；run-spec哈希b37826415b6d073f36b2304501d1781027f3eea63a114617ae0abeccf7c4c11e。窗口在CPU shared-run-window-r7.json，归档截止1790661844.0836086，训练仍4800秒上限，禁止删除Pod。
- r7使用独立/root/mimo-private/*r7*与持久runs/r7，仍单GPU0；下一次真实C2后续训须另用r8身份。旧r5-resume草稿和不存在的r4 C2禁止使用。
- 云端独立审计快照的包边界与原仓不同；Ruff0.15.8显式known-first-party=[uni_agent,verl,examples,tests]后双检查通过。原仓默认配置本地也通过；未改运行源码或放宽规则，所有失败日志保留。

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


## 2026-09-29 05:53 UTC r7终态与待批准设计

- r7首条job-9a271cb139d44f468066538f9fb9e8db生成16611，最后input32646+output122=32768，max-tokens，verifier0；严格模式拒绝。第二条随controller停止取消。零完整准入组、零optimizer更新、零checkpoint。
- controller91543已不存在；GPU supervisor退出，driver状态exit1，trainer-15，controller-health-failed（主动停止controller后）。两卡实测0MiB/0%。此前仅GPU0参与，GPU1未参与训练。
- 两jobs均cancelled，三Modal cleanup returncode137（停止记录，不据此推断OOM）。CPU evidence-r7/cpu-jobs归档29文件659035字节，源/目标逐字节一致；cpu-jobs-manifest.json保存摘要。归档helper91558已发送SIGTERM。
- 公开终态报告 /workspace/mimo-dsh-rl-20260928/integration-check/r7-failure-evidence.json；私有原始证据留CPU /root/mimo-private/evidence-r7/。
- docs/verl-uni-agent-harbor-opd-rl/budget-terminal-admission-design.md已呈交用户；异步问题等待批准。新契约仍finished=false，要求Gateway可信预算证明+独立verifier+完整同策略组，不能只关闭完成门。尚未实现，旧r6/r7不追认成功。
- 现有Pod仍运行计费，禁止旧watchdog删除；保留模型/固定273项uv环境。后续有效更新/保存/独立重载验收仍未完成。


## 2026-09-29 预算准入获批并通过CPU联调

- 用户明确“批准 开始”，后问64K，已说明保持32K/20480生成，先预算终态闭环，再做64K成本比较；未将方案改为64K。
- Gateway121项、launcher71项、Framework/旧回归160项、n4实际合同联调12项、私有准入+group覆盖28项通过（用例重叠不累加）。Worker356项+补足Git fixture后4项，共360项分别通过，五模块coverage93.18%；helper含分支80.53%，Framework新增可执行行86.67%。
- private admission绑定完整Gateway proof/receipt/policy/context/token/versions，private dump绑定NPZ和metadata。新mode v2 request/receipt，默认v1 wire/hash保持。预算样本finished=false；无效成员整组失败；取消和per-call长度终止不伪造budget。
- Gateway slice648d61a与import格式a7d8b76已push origin同名分支；在 /tmp/mimo-budget-push-check 精确提交干净worktree执行完整Ruff双门通过。不改未提交OpenCompass。
- r8源码staging=/workspace/mimo-dsh-rl-20260928/run-src-r8；尚未启动训练。CPU准备脚本prepare-r8.py与driver/wrapper已按新身份改好，待冻结commit/source manifest、设新限时窗口、任务与真实预检。禁止删除已有Pod；保持固定模型/DSH/uv。
