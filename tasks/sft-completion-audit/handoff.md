# SFT完成验收交接

## 1. TL;DR
- 20K编程SFT确实完成10000步；目标尚未全部完成。
- W&B云端90020值与本地一致；正式run未启用rl-insight。
- 实际20K全为code，不能称为多领域全能模型训练完成。
- 本worktree只保存审计证据及待确认设计，不修改训练或评测代码。

## 2. 本轮交付物
- docs/sft-completion-audit/sft-completion-audit.md：总体证据、范围和缺口。
- docs/sft-completion-audit/sft-observability-repair-design.md：最小修复设计，尚未实施。
- docs/sft-completion-audit/sft-completion-evidence/：原始metrics、256配对验证结果、云端/环境/数据哈希回执。

## 3. 设计约束
- 不干扰11403正在运行的OpenCompass评测。
- 不把loss下降等同于benchmark提升，不补造历史trace。
- 历史数据快照保持原样；未来多领域配比另建版本。
- 所有密钥留现有凭据存储，证据中不包含token或原始对话。

## 4. 真实行为
- rl-insight客户端只注册Ray后端，torchrun未初始化Ray，必须单独解决监控传输。
- 当前bootstrap部分依赖未约束；156包版本一致不等于冷重建成功。
- 20K是源前20000行，验证是源前256行；已发布100条验证只是子集。
- JSONL包含同step训练/验证两行，不能只按step去重。

## 5. 下一里程碑
- [ ] 修复设计确认后实施rl-insight独立CPU监控接线。
- [ ] 原生脚本真实有界SFT期间验证后端指标可查询。
- [ ] 固定依赖约束并独立冷重建。
- [ ] 整理多领域数据配比，保留当前编程模型作为对照。

## 6. 分支/部署状态
- 分支docs/sft-completion-audit，基于performance-9b c51f6fc。
- 当前无新训练部署、无新GPU申请、无模型上传。
- 256验证快照已在共享盘releases/sft-run-cxo04d3j-validation256，清单留证据目录。
- commit/push状态以git log和origin为准。

## 7. 冷启动
1. 读本handoff和总体审计文档。
2. 查看git status，不修改原performance-9b worktree既存变更。
3. 用回执中的路径定位原始数据；重新执行动作前核查GPU/进程归属。
4. 监控设计确认后才实施；不能把自动goal提醒视作人类明确设计批准。
