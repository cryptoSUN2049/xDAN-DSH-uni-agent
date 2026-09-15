# Tinker 项目交接
## TL;DR
本 Uni-Agent worktree 保存项目记忆和设计；实现位于 sibling tinker-cookbook-opd-rl。
Teacher Qwen3.8-27B，Student Qwen3.5-9B 指令版；优先 Tinker 官方代码。
本地42测试通过；云端采样、训练、reload、benchmark 尚未验收。

## 交付物
docs/tinker-harbor-opd-rl/design.md。
tasks/tinker-harbor-opd-rl/memory.md（先读）。
Cookbook运行说明：../tinker-cookbook-opd-rl/docs/tinker-cookbook-opd-rl/runbook.md。

## 设计约束
复用官方Harbor/Modal/trainer。显式train/validation。测试不参与训练。
禁止把模型能力目标描述为结果，禁止把Modal某路由404推广为平台不能部署。

## 已发现真实行为
官方distillation训练器已能把组内中心化reward与token KL叠加。
新recipe开启真实grader；修复缺失/旧reward误用，42本地测试通过。
依赖安装完成；当前进程缺TINKER_API_KEY。
旧镜像版本粘连错误修正在memory.md。

## 下一里程碑
- [ ] 账户模型能力及fixed sequence评分
- [ ] 独立Harbor任务oracle/nop
- [ ] 首次更新和独立reload
- [ ] OPD/RL/hybrid消融与benchmark

## 分支/部署状态
Uni-Agent分支worktree-tinker-harbor-opd-rl，基线327d01a。
Cookbook分支feat-harbor-opd-rl，基线485726f。无新部署/推送。

## 冷启动
读memory、design、Cookbook runbook与handoff。查真实代码状态和凭据存在性。
按未完成项继续；无需重新复制训练器或重建worktree。
