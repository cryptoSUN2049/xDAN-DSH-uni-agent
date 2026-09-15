# Handoff: tinker-harbor-opd-rl

## TL;DR
用户确认以Terminal-Bench独立成功率为目标：公开Harbor任务训练，Terminal-Bench2.1独立评测；OPD指导与reward RL联合更新。
代码2ef293b的评估证据补强465项回归通过；本轮联合路径131项回归和4类本地payload检查通过，新代码未部署。
历史真实P0部署b06728a：参数更新/reload已验收，前2/2后1/2；独立原始数组重算RL0、OPD1138非零动作。没有证明能力提高或双非零云更新。
先读docs/tinker-harbor-opd-rl/joint-opd-rl-reference.md给其他会话交接；再读terminal-training-data-strategy.md。TaskTrove三源5830任务已下载，6候选已原样导入、loader通过，仍需/app、公开/setup_files、参考解和依赖失败分类；详见public-dataset-status.json。
4原创题仍为已云验收集合；公开候选的下载/格式与实际运行分别记账。所有云新运行、非零RL和正式TB仍须逐关验收。

## 本轮交付物
- `docs/tinker-harbor-opd-rl/joint-opd-rl-reference.md` — 178行；联合公式、代码、131项验证及真实RL0边界。
- `docs/tinker-harbor-opd-rl/terminal-training-data-strategy.md` — 100行；公开任务策略、接入契约和TB2.1评测分工。
- `docs/tinker-harbor-opd-rl/public-dataset-status.json` — 机器可读数据来源与候选状态，以实际文件为准。
- `docs/tinker-harbor-opd-rl/openthoughts-rl-integration.md` — 86行；固定版本核验、兼容差异、家族划分与接入设计。

当前评估记录关卡文件清单：
- `docs/tinker-harbor-opd-rl/eval-evidence-validation.md` — 60行；本轮新增/修改。
- `docs/tinker-harbor-opd-rl/system-plan.html` — 316 行；本轮新增/修改。
- `tasks/lessons.md` — 75 行；本轮新增/修改。
- `tasks/tinker-harbor-opd-rl/memory.md` — 17 行；本轮新增/修改。
- `tasks/todo.md` — 185 行；本轮新增/修改。

以下为历史P0文件快照（行数属于历史交接）：
- `docs/tinker-harbor-opd-rl/eval-evidence-validation.md` — 本轮实现、测试范围、已知边界与有效RL下一步。
- `docs/tinker-harbor-opd-rl/topk-opd-review.md` — 84 行；官方top-k能力、当前Harbor路线对照、修订候选和验收设计。
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
- [x] 评估记录本地实现/回归；新云版本复验单独待做。
- [ ] 统一口径有界initial/final评估；区分度开发集和Teacher优势检查。
- [ ] 实际非零RL组内信号验收；不以噪声奖励制造差异。
- [ ] 官方TB固定单任务重复与任务资源准入；该题不能再作最终盲测。
- [ ] state+optimizer恢复；最小Control Panel、预算/幂等/取消和恢复协议。
- [ ] baseline/OPD/RL/hybrid消融，最终同口径Terminal-Bench与Opus4.6对照。

## 分支/部署状态
本worktree分支 `worktree-tinker-harbor-opd-rl`。实现分支feat-harbor-opd-rl，部署代码b06728a；后续文档commit以git log为准，不表示重部署。提交备份远端：实现 `training/feat-harbor-opd-rl`（私有仓库 cryptoSUN2049/tinker-cookbook-opd-rl），文档 `origin/worktree-tinker-harbor-opd-rl`（xDAN-DSH-uni-agent）。本节点提交后推送，同步状态以 `git status -sb` / `git ls-remote` 为准；未创建 PR。
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

## 2026-09-15 提交节点与下一验收门槛

- 本轮：联合更新参考文档、公开训练数据策略、六题静态导入清单、任务与经验记录；没有新增云训练费用。
- 验证：联合路径 131 项回归、4 类本地 payload 对照、math_env 37 项；两仓全量 Ruff 检查通过。既有 465 项回归见评估证据报告，非本轮重新全跑。
- 目标仍进行中：6 题仅静态导入，training_ready=false；历史真实 RL=0，尚无非零 RL 与 OPD 同时生效、独立能力提升证据。
- 下一步：适配 `/app` 工作目录和公开 `/setup_files`，核验参考解与 verifier/依赖错误分类；再开展受限的小批云验证，记录 reward 方差、两路信号与独立 reload 评估。
- 5830 题原始归档与轨迹在 ignored outputs / Modal Volume；Git 只保存方案、固定版本、校验和与清单，不含密钥或原始训练输出。

## 2026-09-15 公开任务运行进展

- 显式 `/app` 与公开 `setup_files` 已接入训练 builder、工具、环境验收和资源日志；旧任务默认不变。134 项相关回归及全仓 Ruff 通过，独立代码审查通过。
- `curriculum-medium-0002` 真实 Modal 云验收：nop reward0，参考解 reward1，原始8项测试通过；两个 CPU 沙箱清理回执齐全。无 Tinker 模型调用。
- nop 原始报错为缺少任务要求创建的 `cite_seq_count`，不是 pytest/依赖缺失。原始 grader stdout/exit/reward 保存在 outputs/public-runtime-gate-20260915/audit.json。
- 证据摘要：docs/tinker-harbor-opd-rl/public-runtime-evidence.json；实现说明：public-runtime-gate.md；参考解：examples/harbor-public-runtime/（仅供 controller 验收）。
- 6题派生运行配置在原候选旁的 runtime-v1，未覆盖原始任务；仅上述1题已跑云端，training_ready仍false。
- 下一步：云端可导入错误解验收和 verifier 故障分类，再筛查 Student/Teacher。扩大前排除 stack 来源；当前manifest第二题仍是stack，不能直接把max_tasks改2。
- 本轮未更新 Student 权重，历史真实 RL=0 的结论不变。
