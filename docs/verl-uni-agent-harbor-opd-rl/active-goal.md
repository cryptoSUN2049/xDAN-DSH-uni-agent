# MiMo 9B DSH RL：当前执行目标

2026-09-28：用户明确要求设置并激活 Goal；平台状态已读回为 `active`。

## 目标与范围

在当前同名 worktree/分支 `verl-uni-agent-harbor-opd-rl`，完成 MiMo Code 小样本经固定 DSH、Harbor/Modal、Uni-Agent/TransferQueue、Runpod VERL 的真实训练闭环。复用已有系统，不整体替换为 MiMo fork。首阶段 DSH-first，terminus-2 与其他四领域随后独立验收。

固定 DSH 源码 `b2369692ea530007075ebcd18d39fdba0bbd3982`、SDK/runtime `0.1.3a2`；数据 revision `639865fd3374018d6cb29b9fb82dd531406fcf5f`。镜像、模板、运行源码与任务都记录摘要。

## 退出条件

- [x] Code 全量 2698 条结构转换审计；首个任务镜像与 DSH 运行时实际验收。
- [x] 隐藏测试隔离、历史泄露清理、独立 verifier 的负例/正例校准。
- [x] 真实 tokenizer/processor 的多轮 token、mask、logprob 与预算合同回归。
- [ ] 模型驱动 DSH 执行真实工具轨迹，Gateway/TQ/独立 verifier 回执可追溯。
- [ ] 至少一次奖励有效的 GRPO 更新，证明非零有限梯度及参数变化；排除全零 advantage 或仅 weight decay。
- [ ] 保存 checkpoint；新 controller/run/session 身份重载并继续训练。
- [ ] 归档日志、配置、哈希、成本与资源回收证据，提交代码并完善交接。

结构审计不代表全量任务可训练；手写校准补丁不代表模型能力；工程闭环不代表能力提升。能力收益需后续独立任务、同预算对照。

## 执行与资源约束

- Mac 只编辑、Git 与轻量 SSH；镜像、数据、依赖、测试、推理和训练均在云端。
- 不修改共享训练环境，不挤占其他 GPU 作业；新增资源必须有明确 deadline 和自动回收。
- 先 CPU 依赖/配置预检，再在独占 GPU 跑小型真实 CUDA IPC 测试，然后加载 9B。
- 每个尝试独立保存成功和失败证据，不覆盖旧运行；凭据不进入仓库或公开证据。

## 当前状态

截至 2026-09-28 14:28 UTC：r2 缺失 FA2、r3 继承 NCCL 后端但缺 CuPy，均在模型轨迹前退出，训练更新为零。首个专属 GPU 已于 11:24:54 UTC 提前删除并回读确认，原 11:38 截止未延长。

r4 使用 MiMo 专属 SDPA/naive 配置（67a5948），45 项 CPU 回归、真实模型 tokenizer/dataset 预检通过；uv 持久化环境 273 项约束一致。云端 `run-src-r4/verl` 已复制冻结实际源码，逐文件摘要位于 `integration-check/verl-source-r4.json`，没有修改共享 VERL。

GPU `gqgtsz3pfov6tl` 通过原生 CUDA IPC 小测试（1 passed/0 skipped，203.53 秒），r4于12:19:39启动，完成actor/ref及vLLM加载，12:38 Gateway注册成功。前两job确有18/21轮模型生成及19/22次成对工具调用，但分别撞到16K上下文上限；独立verifier随后因缺少`/tests/test.sh`失败，原始测试未执行，不能计reward=0。

已停止本轮：3 jobs cancelled、5 Modal sandbox全部确认终止；12:49:33训练退出，GPU显存归零，无checkpoint。输入/registration及37份未准入工件已私有归档。12:52:38提前删除GPU，API204/get404/list absence；原13:26:54硬截止未延长，未触碰其他Pod。估计本GPU窗口约$1.94（非账单，不含存储/Modal）。

verifier注入修复已通过96项CPU回归（模块覆盖率94%）及真实原生Harbor校准：baseline0/public-only candidate1、测试文件hash与TaskRef一致、agent无测试入口，4个沙箱全部停止。32K上下文修复保持14336独立生成预算，52项recipe/预检/生成预算回归及真实MiMo预检通过。第一次组合回归缺pytest-asyncio插件失败，显式加载后全部通过；失败留档。新训练须新身份、固定新源码，不修改`run-src-r4`。独立resume脚本目前只是未运行草稿，r4没有C2，不能使用其恢复路径。

执行设计见 [集成设计](mimo-dsh-integration-design.md)，操作入口见 [云端 runbook](mimo-9b-cloud-runbook.md)，冷启动见 [handoff](../../tasks/verl-uni-agent-harbor-opd-rl/handoff.md)。
