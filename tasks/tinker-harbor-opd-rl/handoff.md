# Handoff: tinker-harbor-opd-rl

## TL;DR
P0真实云端工程闭环已完成：1batch更新、同源LoRA差异、独立新进程reload，部署代码b06728a。
训练run hybrid-p0-20260915-02；训练和验证均已结束。不要重复提交同一run或自动扩大训练。
能力未提升验收：训练前2/2，后1/2；RL advantage为0。真实失败是遗漏需保留的配置字段。
先读docs/tinker-harbor-opd-rl/p0-cloud-closed-loop.md、next-milestone.md，再读系统复核；下一步补评估证据与有效学习信号。
286相关测试通过；10核心综合90.67%、分支83.23%；不是整个Cookbook全套测试通过。

## 本轮交付物
本节列出当前工作分支产物，行数为本次交接快照；原始大文件/权重在ignored outputs和Volume，不提交仓库。
- `docs/tinker-harbor-opd-rl/design.md` — 43 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/next-milestone.md` — 63 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/p0-closed-loop-evidence.json` — 189 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/p0-cloud-closed-loop.md` — 104 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/p0-live-status.json` — 180 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/scoring-probe-billing-history.json` — 27 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/scoring-probe-status.json` — 30 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/system-integration-review.md` — 177 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/system-plan-spec.md` — 22 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/system-plan-verification.md` — 58 行；系统设计、证据或交接记录。
- `docs/tinker-harbor-opd-rl/system-plan.html` — 315 行；系统设计、证据或交接记录。
- `tasks/lessons.md` — 63 行；系统设计、证据或交接记录。
- `tasks/tinker-harbor-opd-rl/memory.md` — 17 行；系统设计、证据或交接记录。
- `tasks/todo.md` — 175 行；系统设计、证据或交接记录。
- `tasks/tinker-harbor-opd-rl/handoff.md` — 本文件；当前里程碑冷启动入口。

## 设计约束
- Tinker提供Student与Teacher模型计算，Modal CPU提供controller和sandbox；优先官方Cookbook trainer/Store/logtree/capture/checkpoint，research/debug已使用。
- Student原始token前缀供Teacher评分；thinking和tool-call是动作，环境返回mask0。当前sampled reverse-KL，不是全词表KL或top-k GKD。
- 同一training client保存initial/final并核对SDK下载来源；参数变化、推理reload、optimizer恢复和能力提升分别验收。
- 原始key不入仓库；子sandbox不携带Tinker Secret。用户10美元不是实时余额或美元硬预算。
- 仅worktree内改动，保留主目录；不自动重试训练，不为Tinker模型请求新增timeout包装。
- 已完成云run保持证据，不删除App/Volume；后续代码不能继承本次云验收状态。

## 已踩坑 / 已发现的真实行为
- 首次训练01缺git失败发生于日志初始化，早于更新，但付费短预检已发生。02用最终Linux真实logger/bootstrap修复并验收。
- 训练实际只消费csv-paid-totals同题两条轨迹，奖励[1,1]；1179动作/3595屏蔽，1138非零OPD位置，RL全0。
- 同源adapter 249/498张量改变，共53,520,850个LoRA元素；maxdiff1.000000193e-4。未下载base全部张量。
- 新容器reload正确加载final，2任务均工程有效但仅1任务成功；passed!=task_solved。
- service-config重写遗漏server.timeout=45和logging.path=/var/log/service.log；第3轮cat后到max_turns。无grading_error，未留grader原文，不声称读过具体断言日志。
- 前评估并发2、后评估顺序；前实际temp1/seedNone，后代码默认相同但未记录SamplingParams。不以2题一次随机结果推断因果退化。
- 已有task config落实CPU/内存/network；storage为backend managed非任务硬配额，timeout由显式recipe覆盖。轻量Harbor harness不是完整Harbor Trial或正式TB。
- training4+reload2+audit2 sandbox的create/cleanup逐ID对齐，训练/采样session关闭成功。硬kill下periodic commit不保证零丢失。
- Modal CLI1.5.5 volume get目录前预建目标目录；已有证据不盲目--force覆盖。SDK REST holder可走session-less路径，不能误判为训练session泄漏。
- 原始training status只到training_saved；后续独立checks状态才有参数/reload结论。不要回填旧报告或将其unknown当作最终结果。
- 本地扩大审查发现上游旧rollout日志测试调用已移除API；286相关测试与新Store路径通过，全仓测试未宣称全绿。
- sample/rescore的有限精度偏差仍未形成通用容差；本轮短预检max .1206014。完整长上下文/模板覆盖待后续。

## 下一里程碑任务清单
- [x] A–E工程关卡：bootstrap/记录/资源/token/loss/optimizer/checkpoint/参数/reload。
- [x] 独立失败分析、原始证据摘要、HTML与交接同步。
- [ ] 补评估实际SamplingParams、末次工具输出、grader原文、耗时/截断语义。
- [ ] 统一口径有界initial/final评估；区分度开发集和Teacher优势检查。
- [ ] 实际非零RL组内信号验收；不以噪声奖励制造差异。
- [ ] 官方TB固定单任务重复与任务资源准入；该题不能再作最终盲测。
- [ ] state+optimizer恢复；最小Control Panel、预算/幂等/取消和恢复协议。
- [ ] baseline/OPD/RL/hybrid消融，最终同口径Terminal-Bench与Opus4.6对照。

## 分支/部署状态
本worktree分支 `worktree-tinker-harbor-opd-rl`。实现分支feat-harbor-opd-rl，部署代码b06728a；后续文档commit以git log为准，不表示重部署。未push/PR。
Modal App=tinker-harbor-opd-controller；Volume=tinker-harbor-runs；min_containers0，CPU控制，无本项目自部署Teacher GPU。
image=im-3GvBhwyn7mJ2AuXtElFPPV；wheelSHA=18513048b76f5ef9e2481e38eabb18d5409c7465dce9c3a89515efa2c08281e0。
train call=fc-01M2J1EEA3QRHT0YPFACQYWP7H；verify call=fc-01M2J1ZVVKBT9PATF66CPVFEFB；均已结束。
final sampler=tinker://971c8454-6952-53f2-bf5b-17afa5cf046d:train:0/sampler_weights/final。
state=tinker://971c8454-6952-53f2-bf5b-17afa5cf046d:train:0/weights/final。
原始证据在实现worktree outputs/p0-integrated-gates、p0-trained-cloud-run、p0-verification-cloud-run；云Volume的run/checks中还保留adapter。
CI未推送触发；已执行本地相关回归与真实云验证，正式benchmark和费用账单未验收。

## 冷启动 checklist
1. 先读本文件、docs/tinker-harbor-opd-rl/p0-cloud-closed-loop.md、next-milestone.md；系统HTML和集成复核在文档worktree。
2. git status/diff/HEAD核对两个worktree；保留用户或其他agent未提交工作，不碰主目录。
3. 从p0-closed-loop-evidence.json查hash和原始证据；需要云状态只读查询既有call，禁止重复submit/verify已完成run。
4. 读tasks/lessons.md及官方research/debug；对照实际SDK，不把示例签名或API字段当模型服务实测。
5. 按新验收缺口先本地实现测试，再独立云关卡；每个新run另存来源和状态，保持有界费用。
6. 更新相关todo/记忆/HTML/交接；工程通过与1/2成绩、RL0必须同时保留。
