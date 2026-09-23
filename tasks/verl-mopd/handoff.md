# VERL MOPD handoff

## 1. TL;DR
- worktree `verl-mopd`，branch `worktree-verl-mopd`；用户2026-09-22明确要求完成MiMo算法→训练→真实验证，实施授权已取得。
- 基线7f835fe的原生PG保持可选；本轮增加pg-sequence、corrected Top64 reverse、Flash ORM/current-to-sampling IS，以及每轨迹平均。
- CPU整合回归551项通过；最终125项定向测试通过，557项不同CPU测试，三目标恢复精确一致；打包/提交状态见 `docs/verl-mopd/mimo-objectives-acceptance.json`（生成后为准）。
- 尚未启动本轮GPU训练。需要独立节点/预算、HF教师及专家资格、实际加载和真实更新/恢复证据。
- 先读设计、runbook、resource-readiness、replication-plan；CPU正确不等于GPU/能力通过。当前工程配方仍为LoRA rank16。

## 2. 本轮交付物
- `uni_agent/training/mopd_objectives.py`：三个数学目标、mask与全局有效轨迹归约、FP32全词表归一化及诊断。
- `patches/verl/0002-mopd-objectives.patch`：约354行，原生config/dispatcher、FSDP logits hook、微批前有效sequence计数；含新增native mopd.py。
- `examples/harbor_mopd/recipes/*.yaml`：3个独立配方；`launch.py`：约550行，显式recipe/Flash参数、早期后端检查、源码补丁绑定恢复合同。
- `uni_agent/framework/framework.py`：本轮新增单policy version检查，默认关闭保留旧行为。
- `tests/uni_agent/training/*mopd*.py`：数学/梯度/原生接线/THD-BSHD/padding/DP/保存恢复；GPU服务边界用fixture时明确标注。
- `tests/uni_agent/examples/test_harbor_mopd_recipes.py`：约140行，24项配方与真实Hydra dataclass检查。
- `tests/uni_agent/framework/test_mopd_policy_version_on_cpu.py`：约70行，单版本检查。
- `docs/verl-mopd/mimo-objectives-design.md`：约151行，已批准设计与公式。
- `docs/verl-mopd/resource-readiness.md`：约110行，独立资源/显存估算/分阶段验收。
- `docs/verl-mopd/replication-plan.md`：约45行，SFT→专家RL→MOPD数据/教师/能力验证缺口。
- `docs/verl-mopd/runbook.md`：约175行，配方启动、补丁、恢复与复现边界。
- `docs/verl-mopd/domain-expert-rl-roadmap.html`：领域专家方案的独立离线 HTML，含三级目录；主专题已在 tinker worktree 内嵌同源内容。
- 旧数据prepare、registry、evidence及4train2工程validation沿用；详细历史见acceptance.json/data-readiness.json。

## 3. 设计约束
- VERL HEAD固定a9f2985159536a607211dcac730d3f5d55028950；通过tracked patches部署，不提交新的submodule指针。
- 本地子模块dirty是应用0001/0002所致。不要将0001 padding改动再次收入0002；测试证明clean apply后逐字一致。
- Top64是sum[p log(p/q)−p+q]，候选不重归一化；TP/SP1、unfused FSDP，不能冒充forward KL或全词表KL。
- Flash teacher/current优势与current/sampling IS显式detach，越界置零、原始mask分母不变，无额外PPO/重复IS；alpha与阈值必须显式给出。
- trajectory-mean权重不等于实际梯度贡献，也不保证thinking变短。无任意长度罚分或效果自动止损。
- teacher_domain路由不覆盖data_source。configured model path不冒充loaded weights证明。
- 原生配方需要单机3独立GPU角色；不抢旧评测、不把空闲视作授权，不挪用旧Modal预算。
- 只add自己的明确文件；push前ruff check .和ruff format --check .必须通过。

## 4. 已踩坑/实际行为
- 同步trainer step1采样使用published weight version0；只检查轨迹min=max，不强行等于训练step。
- config旧actor SP与实际fsdp_config SP都要核查；Top64 pad_to_length需在preflight拒绝。
- teacher payload为next-token对齐且尾行dummy ID重复；只检查实际response prediction位置。
- CPU jagged tensor的BSHD padding需pad_sequence(unbind)，不是盲目to_padded_tensor。
- 覆盖率工具在本机torch导入阶段可segfault；预加载torch/tensordict/native loss后调用pytest.main能工作。native adapter覆盖96/112=85.714%。
- Math模块namespace目录没有__init__.py但wheel已包含mopd_objectives.py；examples/YAML/patch仍须完整源码checkout一起部署。
- 两个顺序RL checkpoint不是互补专家；旧merged目录没有safetensors。9B/27B added-token映射不同，跨尺度需专项兼容验证。
- 现有4train2validation复用历史审计任务，本轮未重跑oracle；validation来自历史训练池，不能证明泛化。
- 预算字段仅记录+外部核算，max_steps可约束；没有美元实时硬上限。

## 5. 下一里程碑
- [x] 用户具体设计批准；三个目标、原生接线、配方和CPU数学验证。
- [x] 整合551项回归；原生adapter独立review，无剩余P0/P1；资源方案落盘。
- [x] 最终125项定向恢复/diagnostics测试、wheel源码一致与摘要；提交状态以git log核对。
- [ ] 获得独立节点、唯一操作者排期和GPU/Modal费用上限。
- [ ] 冻结同源S0，领域RL数据与无污染held-out，训练/资格评测两位专家；完成HF导出与实际加载证明。
  领域候选与训练合同已写入 `domain-expert-rl-roadmap.md`；当前仍只有4train+2工程验证，不构成教师训练集。
- [ ] 实机profile后逐配方运行rollout→teacher→update→save→新进程resume→下一批update→资源清理。
- [ ] 领域能力、遗忘、长度/成本的配对实验；9B通过后再定27B资源，不声称私有生产配方完整复原。

## 6. 分支/部署状态
- branch `worktree-verl-mopd`，旧基线7f835fe；实际最新commit/push用git log/status核查。
- 本轮只改本worktree，未部署/提交/取消GPU作业。CPU环境/private/tmp/verl-mopd-cpu。
- 2026-09-22 06:38 UTC旧节点2×96GB，GPU0旧OPD10评测，GPU1无进程但未分配MOPD。共享Modal账单864.40/900美元，非新实验预算。

## 7. 冷启动 checklist
1. 读本文件及mimo-objectives-design.md、runbook.md、resource-readiness.md、replication-plan.md。
2. 核git status/diff/branch/HEAD/stash/worktrees；保留现有未提交内容。
3. 阅读新mimo-objectives-acceptance.json与旧acceptance.json，区分本轮与历史证据。
4. 原生子模块按bootstrap应用0001/0002；源码/patch不匹配应停止部署并修复。
5. 核GPU实际进程、台账/锁、教师导出和预算。先写唯一操作者记录，再执行默认preflight。
6. 每种recipe独立run-root；不重复提交旧run，不自动重放不确定更新，不把CPU/mock成功升级为GPU或能力结论。
