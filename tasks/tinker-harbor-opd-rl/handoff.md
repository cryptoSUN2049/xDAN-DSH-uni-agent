# Tinker项目交接

## TL;DR
主线不变：Tinker 9B Student / 27B Teacher，Harbor + Modal + OPD/RL。
真实任务、Teacher评分、云端Controller与cloud audit通过；117相关测试通过。
首个云训练在记录代码来源时缺git失败，未参数更新；本地修复尚未重部署。
用户要求先全面检查集成与验收、不要过度精简；新训练暂停，修订方案已落盘。
下一步按system-integration-review.md的A-D补齐，再进行一次参数更新与独立恢复验收。

## 本轮交付物
- `docs/tinker-harbor-opd-rl/system-plan.html` — 314 行。
- `docs/tinker-harbor-opd-rl/system-integration-review.md` — 166 行。
- `docs/tinker-harbor-opd-rl/p0-live-status.json` — 72 行。
- `tasks/todo.md` — 184 行。
- `tasks/lessons.md` — 52 行。
- `tasks/tinker-harbor-opd-rl/memory.md` — 15 行。
- `tasks/tinker-harbor-opd-rl/handoff.md` — 本文件，冷启动入口。
- 实际实现与原始证据在sibling `../tinker-cookbook-opd-rl`，先读其对应handoff。

## 设计约束
复用官方research/debug、trainer/Store/logtree/capture/evaluator/checkpoint；业务层补控制与验收。
Student原始token供Teacher评分，动作包含tool-call，环境返回mask0。当前是采样reverse-KL，不声称全词表KL。
参数变化、独立推理reload、optimizer恢复、任务能力提升是不同证据；不能用controller complete包办。
所有代码在专用worktree；原始key不入仓库，Tinker Secret已授权创建；用户10美元不是硬预算。

## 已踩坑 / 真实行为
- 4原创任务8次nop/oracle全部通过且清理；Student/Teacher各2/2，不是正式TB分数。
- Student 6次交互1602动作token、4482屏蔽位置，通过真实KL路径；均值.16305654。
- 两短文本重复/前缀评分一致，但sample/rescore仍有最大.0898/.2061差异，通用容差未定。
- 云端audit验证容器内动态镜像与子sandbox；首次训练日志bootstrap缺git，失败记录已存Volume并下载。
- Cookbook OPD入口未完整接入RL的轨迹HTML/JSON与eval导出；capture不自动捕获compute_logprobs。
- preflight/trainer缺统一close；Harbor清理会吞错误；task.toml资源未完整落实。
- 非零参数比较须保存同一client的initial/final；不能新建随机LoRA作为initial。
- 基础timing已有；full trace默认关闭、CLI未透传；Plotly可选，缺依赖可能跳过图表。
- 旧handoff/HTML中的“无key/无资源”过期；最新状态以p0-live-status.json和本文件为准。

## 下一里程碑任务清单
- [ ] 最终Linux无付费bootstrap、来源与依赖清单。
- [ ] session/logger生命周期、sandbox清理记录。
- [ ] 官方logtree/rollout/eval/capture与Teacher原始评分审计。
- [ ] 同client initial checkpoint、adapter比较器与独立reload。
- [ ] OPD/RL分项与零奖励方差检测，避免无RL信号却宣称已验收。
- [ ] 门槛通过后新run_id单批更新；官方TB单任务重复验证。
- [ ] optimizer恢复、任务分层/评估对照、最小Control Panel。

## 分支/部署状态
项目文档分支worktree-tinker-harbor-opd-rl；Cookbook分支feat-harbor-opd-rl。
远端部署代码71176ee；本地运行修复76d8ac4；无push/PR。App已部署但无活跃训练。
训练run hybrid-p0-20260915-01失败；无checkpoint。不要删除App或Volume中的证据。

## 冷启动 checklist
1. 读本文件、memory.md、system-integration-review.md及Cookbook handoff。
2. git status核对两worktree；不要新建重复目录或触碰主目录用户改动。
3. 查最新JSON及outputs原始实测；保留失败记录。
4. 先落实A-D，不能只因为git修好就立刻再跑；用户强调系统完整性和测试验收。
5. 任何进展写回阶段状态；能力提升与超越Opus仍没有证据。
