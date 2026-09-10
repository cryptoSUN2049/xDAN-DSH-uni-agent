# Harbor / Modal 工程交接 — 2026-09-10 关机检查点

## 1. TL;DR

- 当前worktree：harbor-modal-integration；分支worktree-harbor-modal-integration。用户要求关机前保存，未启动新GPU任务。
- P1→P2→P3保持：核心记忆原生RL有效更新→独立能力收益→真实上下文/跨场景。P1未完成：core-train-r4 16步真实消费，但任务优势/梯度全零、LoRA B全零。
- 四族母step16 reload逐题审计已完成：三族执行成功reward0，WS06失败无B/消费；不称四族业务成功。
- 预算修复5e6b326真实触顶与正常路径均已验：触顶8192原因正确；正常A1037/B302，1组2条消费、exit0，reward0。
- 新reader配对诊断设计待批准，未实施。下一会话不要再重复旧全零训练。先看关机恢复说明与goal。

## 2. 本轮交付物

- docs/harbor-modal-integration/core-budget-normal-r1-result.md/json：正常路径token、回执、消费与after-run证据。
- docs/harbor-modal-integration/core-budget-val-r2-result.md/json：真实触顶修复验收。
- docs/harbor-modal-integration/gpu-shutdown-checkpoint-20260910.md：归档哈希、版本与逐步恢复入口。
- docs/harbor-modal-integration/uni-agent-system-plan-v3.html：当前P1→P2→P3与证据状态；27链接/锚点及三尺寸视觉检查通过。
- docs/harbor-modal-integration/core-reader-role-diagnostic-design.md：待批准的提示包配对诊断，最多16A/128B，不是训练n4。
- 原逐时记录保留handoff-history-20260910-pre-shutdown.md。文件行数见本轮Git diff；不将历史状态作为实时进度。

## 3. 设计约束

DSH唯一Agent Loop；Gateway真实token/mask/logprob；A/B独立session与可信冻结包；完整组消费、版本绑定、原始失败均保留。训练退出、有效优化、能力增益分开。520train/160dev不等于已消费数量。SFT/Harbor/异步后置。不升级固定依赖、不伪造B、不删除准入断言。

## 4. 已踩坑与真实行为

- 正式目录只能由launch创建，预检不能占用；新run新身份，不能复用归档manifest直接启动。
- CUDA/MIG利用率N/A不等于闲置；看实际进程、MIG显存与Session。SSH断开不等于作业结束。
- 活Session在chains/*/*/run/homes/*/sessions/*/*/session.v2.jsonl；导出trace只在结束后更新。
- 全组同分导致当前GRPO任务优势为0；optimizer计数和文件hash变化不是学习。
- 预算r1触顶但原因漏记，5e6b326修复并Linux22测试、真实r2验证；正常WS01无误伤。
- 原四族验证器失败不会追认为成功；WS06正式消费审计false/0条。

## 5. 下一里程碑

- [x] 固定预算修复两侧真实GPU验证、正常链消费与after-run校验。
- [x] 三预算run/准备/报告共7025文件归档至云盘并逐hash验证。
- [ ] 新GPU接回同一云盘，检查宿主与旧venv/解释器，重新记录GPU资源身份。
- [ ] 获明确批准后实施reader配对诊断；当前设计非自动批准。
- [ ] 定位工具/写入/读取瓶颈，获得有区分度的真实任务信号后再RL。
- [ ] 新版核心课程有效更新、同harness前后对照、记忆消融与泛化。Goal未完成。

## 6. 分支与部署状态

GitHub cryptoSUN2049/xDAN-DSH-uni-agent，分支worktree-harbor-modal-integration。关机前代码5e6b326，远端checkout/workspace/rebuild/uni-agent-core-5e6b326；文档HEAD以git为准。每push前Ruff双门通过，远端CI本轮未查询。
旧SSH root@216.243.220.120:13918；此地址可能随关机失效。预算normal-r1 outer83576已消失、supervisor exit0/570.016秒；不复活PID。未停止或购买Pod。
固定VERL fefb080262e1c015a0ea05f958822a6a512dc795+preserve-finish-reason-v1；DSH0.1.3a2/b236969；Qwen3-4B revision1cfa9a7208912126459214e8b04321603b3df60c。
venv/workspace/venvs/uni-agent-rebuild-cf2d3f5；模型/workspace/models/Qwen3-4B-1cfa9a7；checkpoint/workspace/uni-agent-g1/checkpoint/core-train-r4。
归档与hash见gpu-shutdown-checkpoint-20260910.md；本轮7025文件预算归档已验证，旧母训练及reload归档各自范围不混算。

## 7. 冷启动 checklist

1. 读本页→active-engineering-goal.md→docs/harbor-modal-integration/gpu-shutdown-checkpoint-20260910.md。
2. 核git status/branch/HEAD，避免主目录或其他会话文件改动；不要复活历史PID。
3. 用户提供新SSH后检查/workspace卷及归档hash、模型、venv、checkpoint；新GPU/MIG资源重新发现。
4. 按gpu-reconnect-runbook与pod-recovery-design恢复宿主，复用持久环境。新实验Git固定代码、新prepare/check/launch，凭据不进Git。
5. 下一步依据reader待批准设计和memory-rl-evidence-and-next-experiment.md推进，先产生可归因信号，不盲目扩训练步数。

本轮关键新增文件行数：docs/harbor-modal-integration/core-budget-normal-r1-result.md 11行；docs/harbor-modal-integration/core-budget-normal-r1-result.json 90行；docs/harbor-modal-integration/gpu-shutdown-checkpoint-20260910.md 23行。

关机附加保护：三份证据tar已本机备份至outputs/gpu-shutdown-20260910，逐SHA核验通过，共51,176,549 bytes；Git忽略，hash清单在docs/harbor-modal-integration/gpu-shutdown-local-backup-20260910.json。checkpoint仍仅云盘，不误称模型已本地备份。
