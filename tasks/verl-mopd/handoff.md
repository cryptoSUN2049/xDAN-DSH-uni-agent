# VERL MOPD handoff

## 1. TL;DR
- 用户已确认使用 VERL，并于2026-09-22明确批准具体 PG-MOPD 方案实施。
- 当前 worktree `verl-mopd`，分支 `worktree-verl-mopd`；原 VERL 线与已运行评测未修改。
- 原生双教师配置、数据准备、运行合同、恢复检查和轨迹证据已实现；CPU回归与真实本机任务准备通过。
- 尚无本轮GPU训练。原生首轮布局需要3GPU角色，现有节点只有2GPU；教师HF导出/实际加载身份及独立预算仍待落实。
- 先读 `docs/verl-mopd/runbook.md` 与 `acceptance.json`；不可把CPU通过写成GPU端到端或能力通过。

## 2. 本轮交付物
- `examples/harbor_mopd/prepare.py`：220行，显式任务身份/领域join、文件fingerprint、隔离与parquet receipt。
- `examples/harbor_mopd/launch.py`：约428行，本地HF身份、数据复核、原生配置、运行锁、checkpoint合同与显式resume。
- `examples/harbor_mopd/mopd.yaml`：140行，同步原生PG k1、多教师、纯蒸馏、clamp/PPO/token-mean/单轨迹合同。
- `uni_agent/framework/framework.py`：新增79行，教师路由/评分证据与可选单轨迹检查，旧行为默认保留。
- `tests/uni_agent/examples/test_harbor_mopd_{prepare,config,launch,resume}.py`：数据、配置、进程合同、真实CPU恢复测试。
- `tests/uni_agent/framework/test_mopd_{evidence,gradient}_on_cpu.py`：路由/mask/逐token信号、原生autograd与单轨迹检查。
- `docs/verl-mopd/design.md`：设计及批准后的原生行为修正；`runbook.md`：可复制输入/命令与验收边界。
- `docs/verl-mopd/data-readiness.json`：248行，六道真实任务来源/哈希/历史oracle核对；`acceptance.json`：最终检查证据与未完成项。
- `outputs/mopd-data-smoke/`：已忽略的真实本机任务及4train/2validation parquet；路径需在远端重新准备。
- `tasks/todo.md` 与本目录 `lessons.md`：执行状态与经验。

## 3. 设计约束
- 复用原生 TeacherManager 与 losses，无 VERL submodule修改。不得把top-k forward KL称为reverse KL。
- preserve data_source；teacher_domain为独立路由。教师配置路径不冒充实际worker加载权重证明。
- 首轮batch2/N1/单admitted trajectory/单minibatch；不静默丢弃多链来满足配方。
- 仅用户已分配资源可执行；现有GPU评测和Modal预算不可挪用；不杀其他进程、不打印密钥。
- 不设置模型得分自动止损。输入无效、资源冲突、更新结果不确定时拒绝新执行/自动重放。
- 只提交本worktree自己的文件；push前`ruff check .`和`ruff format --check .`必须通过。

## 4. 已发现的真实行为
- k1使用当前actor logprob，detach后通过PPO；pure OPD强制蒸馏系数1，环境reward保留但不进梯度。
- distillation配置没有clip_ratio_c；native fallback3已做数值测试。
- V1覆盖optimizer horizon、强制checkpoint transport naive。首轮使用零warmup恒定LR保证分段恢复合同。
- 一个Harbor任务可能产生多条轨迹；新增明确的single-trajectory选项防止任务数与minibatch数混淆。
- CPU真实StatefulDataLoader+AdamW+scheduler保存/新对象恢复，与连续两步完全一致，下一步不重用已消费任务。
- 原生教师响应没有加载权重digest；保存evidence明确loaded_weights_verified=false。GPU验收需补实际加载/数值响应证明。
- 六道任务与旧审计逐文件匹配；历史12条nop/oracle未重跑。validation来自历史训练池，仅可用于工程smoke。
- 只读确认远端9B/27B基础vocab相同、added token ID映射不同。需检查实际使用ID，不能据此断言旧OPD失败原因。
- 原节点2×96GB，GPU0仍旧评测。原生actor1+teacher1+teacher1需要3GPU角色；旧merged目录没有safetensors，非现成HF教师。
- 预算只记录+外部核算，未实现美元硬上限。不要把示例budget20当用户预算授权。
- 本机Ruff0.13.3全仓通过；0.12.2与0.16.7分别暴露继承lint/Markdown格式差异，见lessons。不要为工具版本差异批量改无关文件。

## 5. 下一里程碑
- [x] 设计批准，最小原生多教师工程实现与独立审查。
- [x] CPU路由/梯度/mask/全局token归一化/恢复回归。
- [x] 复用真实审计任务，准备本机4train2工程validation。
- [ ] 确定三GPU可用节点、单操作者排期和独立费用上限。
- [ ] 导出两个可加载教师，验证真实token/模板兼容和worker加载身份；区分工程fixtures与合格专家。
- [ ] 在远端独立目录重新准备任务/Harbor注册/输入路径，核部署源码与模型摘要。
- [ ] 真实两教师评分→学生更新→新rollout→保存→新进程恢复→下一批更新→资源清理证据。
- [ ] 独立测试集上的专家资格与学生能力/遗忘/长度/成本评估；9B后扩展27B。

## 6. 分支/部署状态
- worktree `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/verl-mopd`。
- base outer7897cad；VERL固定a9f2985159536a607211dcac730d3f5d55028950，未改动。
- 实际提交/推送状态以`git log -3 --oneline`与`git status -sb`为准。本轮未部署GPU、提交训练或取消旧作业。
- CPU环境 `/private/tmp/verl-mopd-cpu`，Torch2.14.0/Ray2.54.1/Transformers5.5.4/TensorDict0.10.0；不冒充GPU依赖环境。

## 7. 冷启动 checklist
1. 读本文件、runbook.md、acceptance.json、data-readiness.json及lessons。
2. 核当前branch/HEAD/status/submodule；保留其他操作者文件。
3. 先查原VERL最新handoff、GPU排期/实际进程和现有预算；不重复提交旧run。
4. 如三GPU与教师仍缺，推进导出/兼容性/独立数据准备，不伪造设备数或无预算启动。
5. 具体执行前在台账声明唯一操作者、检查锁、冻结输入合同；按runbook先默认preflight再执行。
6. GPU结果仅在真实证据齐全时写通过；run exit0或checkpoint存在本身不是完成验收。
