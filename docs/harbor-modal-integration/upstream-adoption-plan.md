# 当前实现与最新 Uni-Agent：复用和迁移计划

核查日：2026-09-08。上游 main 为 89733ec81a69c3cc93ac90479de7ea7f01e51c1f；本项目继承基线为 6e00d8312d3d78996b2cb2de4061fea0d7c18680。GitHub compare 显示上游比该基线多5提交，不表示本地DSH开发仅落后5提交；本地含独立适配与审计修复。VERL固定483b8a009ba3a97563edee3a19887e4862b8094a，本轮未升级。

## 已有能力直接复用

Gateway多token chain、context compaction/子Agent轨迹、MemAgent 4B recipe、mini-swe-agent黑盒训练、separate_async/colocate_async、Harbor CLI评估均已在本项目代码中。历史DSH运行和更新/reload继续保留。详细路径见uni-agent-code-audit.md，不因上游文档更新重新实现。

## 新提交决策

| 更新 | 影响 | 采用策略 |
|---|---|---|
| [#109](https://github.com/verl-project/uni-agent/pull/109)，9/4已合并，9aed3fa | breaking：AgentRunner返回TaskResult，Framework管评分；移除reward_info_url、POST reward_info、Trajectory.reward_info，debug schema变2 | 在S2扩建Harbor奖励接口前完成迁移设计；保持本地fresh receipt、finished、整组准入与审计不变量。不要静默合并或同时升级VERL |
| [#165](https://github.com/verl-project/uni-agent/pull/165)，9/4已合并，07b72ac | SWE-rebench重置到base_commit并清除未来refs/remotes/history，失败即阻断 | 启用该任务前优先采用并验证数据防泄漏；不把清理脚本用于开发者工作区 |
| [#173](https://github.com/verl-project/uni-agent/pull/173)，9/4已合并，89733ec | Claude Code RL结果文档 | 作为上游证据阅读，不是新训练实现，不是本项目成绩 |
| #159 d1b6e6d、#167 c5a0ca9 | CI标签与MkDocs触发检查 | 后续同步时合并评估，不阻塞本地H0 |

## #109为何不能直接覆盖

PR明确finished=None仍可训练，unfinished reward保留在rm_scores参与既有group-baseline语义；本地DSH要求不合格episode使完整group失效，两者不能未经适配混用。RewardLoopWorker开启时runner reward不一定成为最终reward，自定义scorer与colocated路径存在明确限制；不能让默认评分绕开DSH verifier。

迁移测试至少覆盖：正常TaskResult；finished False/None；超时/取消；错配或旧receipt；不完整group；custom scorer取值；多trajectory奖励传播；schema1历史artifact只读与schema2新artifact；训练消费和准入identity关联。上游报告的单GPUsmoke未运行optimizer，不能替代本地新链路更新/reload验收。

路线选择：S0/S1保留当前pin完成可复建与环境验证；S2先冻结目标TaskResult合同，再设计本地严格准入迁移。若暂留旧接口，须记录隔离边界和迁移测试，避免将旧reward_info扩散到新的Harbor/OPD接口。实际迁移仍需逐批文件/API设计与测试，不将本次调研当实现。

## 新版本没有自动解决的事

这5提交不改Harbor任务文件或teacher_client adapter；Harbor训练桥与DSH OPD仍待接入。MemAgent存在不代表DSH已学会记忆。动态插件不代表候选档案/跨进程晋升/回滚已闭合。训练框架支持不等于本地运行验证。

## 持续更新规则

每个集成里程碑开始时只读核对上游HEAD和相对固定基线差异；按bugfix、接口破坏、recipe、文档分类。保存来源SHA、适用性、迁移测试和决定；能力更新后同步工程路线图。未经验收不浮动依赖，不把合并PR等同实际能力成绩。
