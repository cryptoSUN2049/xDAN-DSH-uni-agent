# VERL / Harbor / Modal 六个月专题审计

核查窗口：2026-03-08 至 2026-09-08。来源为 GitHub API 的 issues、PR body、files patch、merged_at、timeline 和本地 git merge-base。仅查相关主题，不代表完整 VERL 项目审计。所有实验成绩均为贡献者报告，本轮没有复跑训练。

## 结论

存在可参考的开源实现；应区分 Harbor runtime 集成、Harbor task 格式复用、Modal 沙箱和训练器底座。VERL 主仓没有发现已合并的完整 Harbor adapter PR；通用的多轮轨迹/异步底座已合并，并有 Uni-Agent 已合并 gateway。不能说生态没有实现，也不能说官方主线已经交付我们要的 DSH + Harbor + Modal。

## 时间线（10项）

| 日期 | 原始来源 / 状态 | 实际能力与复用判断 |
|---|---|---|
| 2026-03-25 | [VERL #5737](https://github.com/verl-project/verl/issues/5737)，open；[recipe #83](https://github.com/verl-project/verl-recipe/pull/83)，4/13 opened，仍 open 未 merged | RemoteAgentLoop：外部 Agent 调 OpenAI proxy，记录 token_ids/logprobs，支持独立 proxy + WebSocket relay；含 local_harbor 数据适配。可借鉴跨网络接线，不能宣称官方已合并。 |
| 2026-03-30 | [VERL #5816](https://github.com/verl-project/verl/pull/5816)，merged，60900f05 | 删除 fully_async 中强制所有多轮样本为 tool_agent 的覆盖；保留数据集自定义 agent_name。是自定义 AgentLoop 基础，不是 Harbor adapter。本地 483b8a0 已含。 |
| 2026-05-22/27 | [VERL #6444](https://github.com/verl-project/verl/pull/6444)，5/27 closed，merged_at=null | 实际新增 Harbor Trial→AgentLoopOutput，Daytona/Modal、prefix-aware step merging、12项CPU测试。作者报告8×A100 Qwen3-8B GRPO fully_async + Daytona smoke。维护者5/22仅说正在Uni-Agent用Modal做SWE全异步；关闭事件为wuxibin89，没有写关闭理由、没有cross-reference successor。可借鉴，不能称merged。 |
| 2026-05-28 | [VERL #6516](https://github.com/verl-project/verl/pull/6516)，merged，6a97abcc | 仅README一行发布Uni-Agent。不是Harbor训练代码合并。 |
| 2026-06-10 | [Uni-Agent #25](https://github.com/verl-project/uni-agent/pull/25)，merged，862314f0 | 真正合并blackbox gateway：OpenAI session、token-truth、mask/logprob、prefix变化切轨迹；当前项目HEAD已包含此提交。VERL [#6299](https://github.com/verl-project/verl/pull/6299)7/14关闭，作者[明确说明迁移](https://github.com/verl-project/verl/pull/6299#issuecomment-4965154602)。但其所指[Uni-Agent #73](https://github.com/verl-project/uni-agent/pull/73) mini-swe-agent recipe closed未merged；YRSandbox+gateway tunnel+V1 separate_async，不能误称Modal/Harbor成品。 |
| 2026-06-22 | [VERL #6779](https://github.com/verl-project/verl/pull/6779)，merged，603944b0 | Continuous Token builder，维持工具反馈/assistant生成间token连续性并对齐mask/logprob，Qwen/MiniMax/GLM边界支持；默认关闭。CPU及vLLM/SGLang smoke覆盖，作者报告SGLang工具GRPO。当前483b8a0已含，复用前需核开关和Gateway路径是否实际用到。 |
| 2026-07-20 | [VERL #6556](https://github.com/verl-project/verl/pull/6556)，merged，298fdc71 | fully_async trainer GPU空闲时加入rollout、训练时撤回，动态资源调度与权重同步。当前483b8a0已含；属于后期吞吐优化，不是首个Harbor任务的前置依赖。 |
| 2026-08-12 | [VERL #7357](https://github.com/verl-project/verl/pull/7357)，merged，535c4779 | CI迁移到V1 separate_async，disable旧fully_async/one_step_off_policy workflows，并为移动fully_async到recipe准备。当前483b8a0不是该merge祖先，日期不能代替代码祖先检查。新旧入口差异意味着不可整抄2026年5月recipe到新trainer。 |
| 2026-08-20/28 | [recipe #141](https://github.com/verl-project/verl-recipe/pull/141)，open未merged；依赖[VERL #7458](https://github.com/verl-project/verl/pull/7458)8/28 merged，a0feb78f | TMax最贴近long-loop目标：TMax-15K-Harbor格式任务、Modal沙箱、持久bash、自定义TmaxAgentLoop、verifier；作者报告Qwen3.5-9B TB2.1在64K预算21.5→29.8%，256K预算24.7→33.9%。实际代码不import Harbor runtime，而是读task.toml/Dockerfile/tests，直接modal.Sandbox.create，因此是Harbor格式复用+Modal直连。REQUIRED_VERL固定贡献者分支f765e4f439，Python>=3.11、vLLM>=0.26。#7458添加FSDP梯度同步opt-out；不在当前基线。不能直接cherry-pick整个recipe视为兼容。 |
| 2026-09-01 | [VERL #7115](https://github.com/verl-project/verl/pull/7115)，merged，c2429f29 | rollout router支持FQN/YAML外部插件，显式举Uni-Agent router；sticky session+least inflight默认不变，可按请求提供prompt_ids。当前483b8a0不含，先接通任务不必升级；以后并发/cache调优再评估。 |

## 当前版本与代码核验

当前 VERL HEAD：483b8a009ba3a97563edee3a19887e4862b8094a，2026-08-14，[misc] chore: bump version to 0.9.0 (#7411)。本地 merge-base --is-ancestor 实测：5816/6779/6556 为0，7357/7458/7115 为1。Uni-Agent #25 sha862314f为当前项目HEAD祖先。以上不是仅凭PR日期推断。

## 与本项目严格验收的差异

TMax #141 _build_output在环境失败时仍构造输出，缺失logprobs补0，reward额外信息仅acc；这种策略不能未经审查复制到DSH严格准入。ModalSandboxEnvironment在finally terminate/detach，verifier只在Agent提交后注入/tests，值得参考；它不提供我们的签名/新鲜回执绑定。#6444的flatten方式依赖token前缀和特定Qwen模板，需要核上下文压缩、子Agent和非append-only行为。

## 建议

保留当前已继承的Uni-AgentGateway+VERL基线，用Harbor统一管理任务/环境/验收，DSH bridge复用同一个环境。首轮先Docker oracle，再DSH+Gateway单任务，随后Harbor Modal provider迁移同一任务，最后把真实token、reward与回执绑定送入VERL并完成小步更新/独立reload/heldout对照。只借鉴#6444契约和#141持久shell、timeout、清理，不同时重写自己的Modal adapter；如目标改为复现TMax论文，则单独建立依赖隔离的训练分支。
