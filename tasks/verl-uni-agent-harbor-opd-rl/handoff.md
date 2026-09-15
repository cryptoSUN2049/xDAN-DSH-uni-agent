# TL;DR
- 当前分支/worktree：verl-uni-agent-harbor-opd-rl，基线9075dfa；实施已明确授权。
- 已成对升级Uni-Agent91618ea/VERLa9f2985，合并提交0c61d01。
- Teacher原生桥接已实现，CPU合同与回归通过；GPU环境安装中，无训练成功证据。
- 用户目标：全异步高性能LoRA RL，支持OPD与独立Harbor verifier reward；可按需提供双卡。

# 本轮交付物
- docs/verl-uni-agent-harbor-opd-rl/integration-design.md（100行）：来源、架构、Teacher/TQ因果位置及异步资源合同。
- uni_agent/framework/entry.py（221行）：teacher_client配置验证与转发。
- uni_agent/framework/framework.py（1685行）：每条准入chain评分、原始token/mask保留、Teacher顶层TQ及正确ragged维。
- tests/uni_agent/framework/test_teacher_scoring_on_cpu.py（182行）：26例，先红后绿。
- tests/uni_agent/framework/test_teacher_rollout_on_cpu.py（170行）：8例，真实CPU调用链和整组失败拒绝。
- Gateway与原有postprocessor测试：兼容上游CT/task_result并保留本地严格证据。
- tasks/todo.md与memory.md：当前计划/用户授权/环境边界。

# 设计约束
Uni-Agent保留Agent/DSH/Gateway/任务准入/TQ；VERL负责optimizer/同步，Harbor负责verifier，Modal只做任务sandbox。不能切换Tinker trainer或另一套agent loop。Teacher概率不是任务成功判定。完整组任一Teacher失败必须零trajectory提交。生成版本、行为logprobs与工具mask不得丢失。

# 已踩坑/真实行为
- 原生Teacher返回全序列[S,K]且已left-shift，首response用prompt_len-1行，末dummy不能再shift。
- Teacher TQ必须ragged_idx=1，缺列不得shared_keys静默drop。
- 上游新增TQ running状态、postprocessor必传task_result；本地strict/receipt合同同时保留。
- CT暂不支持incremental image/video，纯文本终端任务不受影响。
- Harbor严格controller锁0.16.1；现有执行器仍Docker专用，Modal未接通。
- 单卡不能调度原生Teacher独立池；colocate+OPD至少2角色GPU，separate+OPD至少3；纯separate RL两卡。
- 共享FUSE不支持chown，源码rsync用-rltz，不能用-a后忽略exit23。
- CPU临时环境torch2.14，不能冒充GPU锁；UA测试lane vLLM0.23与VERL正式uv.lock0.24不同。

# 下一里程碑任务清单
- [ ] 保存Teacher桥接提交并同步远端增量。
- [ ] 完成GPU测试lane基础算子/真实vLLM相关回归。
- [ ] 完成三种原生recipe及配置测试（gateway_upgrade agent负责）。
- [ ] 完成Modal backend隔离/cleanup证据与可达HTTPS gateway。
- [ ] 按用户承诺在确实需要时通知开双卡，先separate_async LoRA RL。
- [ ] OPD/组合目标多卡更新、版本同步、独立reload和optimizer恢复验收。

# 分支/部署状态
未push、未PR。远端root@157.157.221.177:12524，SSH key ~/.ssh/id_ed25519。
独立根/workspace/verl-uni-agent-harbor-opd-rl；src/uni-agent已同步升级源码，Teacher后续增量待同步。
环境envs/ua-verl-py312-vllm023仍安装中；无训练正在本项目启动。
不得修改SkyRL/metarsi目录或进程；启动前重新查GPU使用情况。
CPU：升级Framework256/Gateway227；Teacher26+8；评分后Framework282（后加8另跑通过）。
日志/private/tmp/uni-agent-opd-framework-regression.log等，远端runs/environment-install.log。

# 冷启动 checklist
- [ ] 先读本handoff与memory.md，再读integration-design.md。
- [ ] git status / log / submodule status，确认工作目录和未提交改动。
- [ ] 查GPU环境安装日志/exit marker，不重复启动安装或训练。
- [ ] 以当前实际源码测试；不把CPU或Tinker历史证据当完整VERL闭环。
- [ ] 继续tasks/todo.md当前节，用户已授权勿重复询问是否实施。
