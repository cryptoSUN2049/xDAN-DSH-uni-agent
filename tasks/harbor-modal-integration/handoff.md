# Harbor / Modal 工程交接 — 2026-09-10 关机检查点

## 1. TL;DR

**下次从这里开始：** [冷启动检查点](checkpoint-20260910-reader-ready.md) → [阶段总结](../../docs/harbor-modal-integration/stage-summary-20260910.md)。备份索引：[stage-backup-20260910.json](../../docs/harbor-modal-integration/stage-backup-20260910.json)。

- 当前worktree：harbor-modal-integration；分支worktree-harbor-modal-integration。用户要求关机前保存，未启动新GPU任务。
- P1→P2→P3保持：核心记忆原生RL有效更新→独立能力收益→真实上下文/跨场景。P1未完成：core-train-r4 16步真实消费，但任务优势/梯度全零、LoRA B全零。
- 四族母step16 reload逐题审计已完成：三族执行成功reward0，WS06失败无B/消费；不称四族业务成功。
- 预算修复5e6b326真实触顶与正常路径均已验：触顶8192原因正确；正常A1037/B302，1组2条消费、exit0，reward0。
- 新reader配对诊断已获明确批准；CLI、隔离分支和CPU测试已实现，GPU未部署/未执行。下一会话不要再重复旧全零训练。先看关机恢复说明与goal。

## 2. 本轮交付物

- docs/harbor-modal-integration/core-budget-normal-r1-result.md/json：正常路径token、回执、消费与after-run证据。
- docs/harbor-modal-integration/core-budget-val-r2-result.md/json：真实触顶修复验收。
- docs/harbor-modal-integration/gpu-shutdown-checkpoint-20260910.md：归档哈希、版本与逐步恢复入口。
- docs/harbor-modal-integration/uni-agent-system-plan-v3.html：当前P1→P2→P3与证据状态；27链接/锚点及三尺寸视觉检查通过。
- docs/harbor-modal-integration/core-reader-role-diagnostic-design.md：已批准的提示包配对诊断，最多16A/128B，不是训练n4。
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
- [x] 明确批准后实施reader配对诊断、CLI、CPU测试及操作指南。
- [ ] GPU恢复后先1题canary，再固定16题配对诊断；不将CPU模拟证据当真实学生。
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
5. 下一步依据reader已批准设计与core-reader-role-diagnostic-runbook.md和memory-rl-evidence-and-next-experiment.md推进，先产生可归因信号，不盲目扩训练步数。

本轮关键新增文件行数：docs/harbor-modal-integration/core-budget-normal-r1-result.md 11行；docs/harbor-modal-integration/core-budget-normal-r1-result.json 90行；docs/harbor-modal-integration/gpu-shutdown-checkpoint-20260910.md 23行。

关机附加保护：三份证据tar已本机备份至outputs/gpu-shutdown-20260910，逐SHA核验通过，共51,176,549 bytes；Git忽略，hash清单在docs/harbor-modal-integration/gpu-shutdown-local-backup-20260910.json。checkpoint仍仅云盘，不误称模型已本地备份。

关机后本机离线分析：core-budget-normal-r1-failure-analysis.md/json证明该WS01的A index与权威workflow逐字段相同；B只view notice后create两文件，0次memory读取，输出100/1与[config.json]，真实目标2869/8。单题支持优先诊断检索，不证明提示因果或学习收益。未调用GPU。

本次代码节点：新增diagnose_core_reader.py（prepare/check/run）、reader_diagnostic_evidence.py（可信负结果）、reader_diagnostic_runtime.py（自有vLLM/Gateway）；stage.py增加冻结一次/独立B分支，原训练入口保留。新增4个诊断测试文件，旧stage及consumption回归同步更新。启动门验证实际runtime/import、绝对PYTHONPATH、模型清单与manifest不漂移。reader运行仅诊断，不消费TQ。新代码尚未部署GPU；Git提交以本页所在提交为准。

本节点CPU验收：898 passed；诊断三个模块与stage.py合计行覆盖率90%。结果清单：docs/harbor-modal-integration/core-reader-role-diagnostic-cpu-result.json。旧consumption测试漏传新增budget参数已修复。CLI启动控制使用mock backend测试，CPU真实verifier工件使用合成模型trace；没有新的真实GPU证据。

新增 `deployment/diagnostics/reader-diagnostic.sh` 作为固定参数统一入口；runbook已补充其用法。

本节点主要文件行数（含新增/修改）：
- examples/dsh/capabilities/diagnose_core_reader.py：419行。
- examples/dsh/capabilities/reader_diagnostic_evidence.py：237行。
- examples/dsh/capabilities/reader_diagnostic_runtime.py：201行。
- examples/dsh/capabilities/work_state/stage.py：488行。
- tests/uni_agent/examples/test_diagnose_core_reader.py：280行。
- tests/uni_agent/examples/test_reader_diagnostic_evidence.py：179行。
- tests/uni_agent/examples/test_reader_diagnostic_runtime.py：226行。
- tests/uni_agent/examples/test_reader_diagnostic_launch.py：184行。
- tests/uni_agent/examples/test_work_state_stage.py：354行。
- tests/uni_agent/examples/test_work_state_consumption.py：68行。
- docs/harbor-modal-integration/core-reader-role-diagnostic-runbook.md：80行。
- docs/harbor-modal-integration/core-reader-role-diagnostic-design.md：51行。
- docs/harbor-modal-integration/core-reader-role-diagnostic-cpu-result.json：40行。
- docs/harbor-modal-integration/uni-agent-system-plan-v3.html：4行。
- tasks/harbor-modal-integration/active-engineering-goal.md：179行。
- tasks/lessons.md：240行。
- tasks/todo.md：590行。

2026-09-10 阶段保存：用户报告GPU关闭；本轮无远程操作。三份本机证据SHA再次通过；新增2f3ea86源码离线tar并逐Git blob核验。最新代码2f3ea86，后续本次提交仅文档；GPU runtime仍未部署新reader。新增阶段总结、冷启动检查点和备份索引，文件行数见各文件及Git diff。

阶段保存新增文件：
- docs/harbor-modal-integration/stage-summary-20260910.md：65行。
- docs/harbor-modal-integration/stage-backup-20260910.json：35行。
- tasks/harbor-modal-integration/checkpoint-20260910-reader-ready.md：43行。

2026-09-13 离线部署审计：`bash -n deployment/bootstrap/*.sh deployment/diagnostics/*.sh` 全部通过。固定 checkout、VERL frozen sync、DSH 构建与 reader 入口未发现 shell 语法问题；这不替代 Linux/GPU 安装和 CUDA 验证。

2026-09-13：统一诊断脚本修正 `--help/-h` 可在未设置运行环境时正常显示用法；bash -n、help smoke 与 Ruff 双门通过。

2026-09-13：checkout.sh 增加私有 GitHub 的临时 GIT_ASKPASS 支持；仅继承 GH_TOKEN/GITHUB_TOKEN，token 不写入仓库或 git 参数，退出自动删除临时文件。bash -n 通过。
