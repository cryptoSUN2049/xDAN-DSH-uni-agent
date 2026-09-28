# SFT完成验收交接

## 1. TL;DR
- 20K编程SFT确实完成10000步；目标尚未全部完成。
- W&B云端90020值与本地一致；正式run未启用rl-insight。
- 实际20K全为code，不能称为多领域全能模型训练完成。
- 用户已批准继续；CPU sidecar、启动器接线和固定依赖重建已实施。真实SFT小样等待环境重建和空卡。

## 2. 本轮交付物
- examples/performance_9b/sft_insight_sidecar.py：独立零GPU Ray、JSONL游标与结束回执；31测试、96%覆盖。
- examples/performance_9b/run_verl_sft.sh：SFT_INSIGHT_ENABLE=1就绪门禁与独立退出码；5集成测试。
- deployment/bootstrap/setup-performance-9b-sft-cu128.sh及runtime/build constraints：固定依赖重建，5测试。
- deployment/bootstrap/run-sft-observability-smoke-when-idle.sh：等待环境exit0和连续30秒空卡，最多24小时，单卡2条/一步/4K真实小样。此小样不替代原双卡20K。

- docs/sft-completion-audit/sft-completion-audit.md：总体证据、范围和缺口。
- docs/sft-completion-audit/sft-observability-repair-design.md：已批准修复设计。
- docs/sft-completion-audit/sft-completion-evidence/：原始metrics、256配对验证结果、云端/环境/数据哈希回执。

## 3. 设计约束
- 不干扰11403正在运行的OpenCompass评测。
- 不把loss下降等同于benchmark提升，不补造历史trace。
- 历史数据快照保持原样；未来多领域配比另建版本。
- 所有密钥留现有凭据存储，证据中不包含token或原始对话。

## 4. 真实行为
- 2026-09-28 03:29 UTC后端健康检查通过，但Prometheus activeTargets为空；见insight-health-audit.json。rl-insight健康路由为/healthz，不是/health。
- rl-insight客户端只注册Ray后端，torchrun未初始化Ray，必须单独解决监控传输。
- 当前bootstrap部分依赖未约束；156包版本一致不等于冷重建成功。
- 20K是源前20000行，验证是源前256行；已发布100条验证只是子集。
- JSONL包含同step训练/验证两行，不能只按step去重。

## 5. 下一里程碑
- [x] 用户批准、sidecar与launcher实施；CPU双值真实Prometheus range和val查询通过，sidecar退出干净。
- [ ] 原生脚本真实有界SFT期间验证后端指标可查询。
- [x] 固定依赖约束实现。
- [ ] 独立独立冷重建exit0、160包pip check和157项来源/版本核验通过；CUDA验收仍待空卡。
- [ ] 整理多领域数据配比，保留当前编程模型作为对照。

## 6. 分支/部署状态
- 分支docs/sft-completion-audit，基于performance-9b c51f6fc。
- 未申请新GPU、未上传模型。11403原评测仍运行。
- 不可变代码快照 /workspace/sft-observability/20260928；使用新venv envs/performance-9b-sft-cu128-rebuild-20260928，不覆盖原环境。
- 冷重建 PID74254（shell）、74255（bootstrap）；runs/sft-environment-rebuild/launch.log与exit-code，已完成exit0；新venv的包检查/导入通过，不重启重建。
- 空卡队列 PID75874；runs/sft-observability-queue/nohup.log、pid、exit-code。已用nohup启动；重建失败则拒绝启动GPU，连续空闲再执行，最多24h。
- 真实小样预期run：runs/performance-9b-sft/verl-sft-insight-smoke-20260928；尚未证明启动或完成。
- 已有单卡pod769tt1sxhn6bpj的SSH现为11621；上面已有其他项目18547/42501模型服务，不停止。旧15728不可继续当作当前地址。
- CPU acceptance /runs/insight-sidecar-acceptance-20260928 已完成；backend-verification.json与query-range.json留证据，不冒充真实训练。
- 256验证快照已在共享盘releases/sft-run-cxo04d3j-validation256，清单留证据目录。
- commit/push状态以git log和origin为准。

## 7. 冷启动
1. 读本handoff和总体审计文档。
2. 查看git status，不修改原performance-9b worktree既存变更。
3. 用回执中的路径定位原始数据；重新执行动作前核查GPU/进程归属。
4. 用户已明确批准。先查冷重建与队列当前PID/日志；训练小样完成后再做Prometheus实际值对账，不凭forwarding_complete宣称后端验收。
