# Tinker 项目交接

## TL;DR
系统方案 HTML 已完成，入口 docs/tinker-harbor-opd-rl/system-plan.html。
主线：Tinker Teacher Qwen3.8-27B / Student Qwen3.5-9B 指令版，Harbor任务与Modal沙箱。
本地组合代码与历史42测试存在；真实更新/reload/benchmark尚未验收。
本轮用户提供key后真实preflight停在capabilities：HTTP402计费阻塞；已停止等待，未采样或训练。
下一步：处理Tinker billing，安全注入key重跑；并准备独立Harbor任务。

## 本轮交付物
- `docs/tinker-harbor-opd-rl/system-plan.html` — 313 行；完整离线HTML：架构、流程、目标、模式、SDK、步骤、云运行与缺口。
- `docs/tinker-harbor-opd-rl/system-plan-spec.md` — 22 行；HTML设计规格。
- `docs/tinker-harbor-opd-rl/system-plan-verification.md` — 36 行；浏览器/链接/JS验证及API诊断记录。
- `docs/tinker-harbor-opd-rl/scoring-probe-status.json` — 27 行；脱敏HTTP402实测状态。
- `tasks/tinker-harbor-opd-rl/memory.md` — 25 行；项目记忆与最新阻塞。
- `tasks/lessons.md` — 45 行；SDK签名与billing等待经验。
- `tasks/todo.md` — 168 行；执行与review记录。
- `tasks/tinker-harbor-opd-rl/handoff.md` — 本文件，冷启动入口。

## 设计约束
复用官方 research skill、Harbor/Modal/OPD trainer，不再扩建2.4T scoring主线。
Student精确原始token序列供Teacher评分，action mask与target shift对齐。
区分实现、单测、在线评分、更新、reload、能力提升；禁止相互替代。
最终Terminal-Bench测试不用于训练；Opus4.6超越目标尚无证据。
key仅由环境/Secret注入，未持久化本轮凭据；不要从对话复制进项目文件。

## 已踩坑 / 已发现的真实行为
SDK0.29.0 compute_logprobs_async直接返回logprob列表；部分Context7旧自动文档错误写为SampleResponse。
forward_backward_async/optim_step_async返回APIFuture，需再result_async；官方train_step移除辅助mask字段。
每批Teacher None/非有限分数、全零mask完整拒绝仍待补；HTML契约明确为目标。
HTTP402时SDK暂停等待billing恢复，可表现为长时间无输出。本轮SDK日志及只读路由均证实402。
403/1010是urllib诊断中网关响应，标准curl与SDK最终一致为402；不能误读成模型不存在。
本轮未返回模型列表，未进入Student/Teacher采样评分；无新checkpoint或得分。
已查HTML桌面/手机、链接、3模式切换、阶段展开、打印展开、Node语法；无浏览器错误。

## 下一里程碑任务清单
- [ ] 用户在 https://tinker.thinkingmachines.ai/billing/balance 完成计费配置或补足账户条件。
- [ ] 安全注入TINKER_API_KEY，重跑preflight；当前进程未持久保存key。
- [ ] 独立2 train +2 validation任务，Modal oracle/nop与cleanup。
- [ ] 多轮golden trace、每批评分/有效mask拒绝与故障测试。
- [ ] 首次hybrid更新、非零更新证据、新sampler与独立reload/后评估。
- [ ] baseline / OPD / RL / hybrid消融，再决定规模。
- [ ] Modal CPU控制器、持久化账本、预算与恢复控制；当前为设计。
- [ ] 同口径最终Terminal-Bench与Opus对照。

## 分支 / 部署状态
项目worktree分支worktree-tinker-harbor-opd-rl；本轮仅文档修改，本地提交、无推送/PR/部署。
实际Cookbook实现sibling ../tinker-cookbook-opd-rl，feat-harbor-opd-rl，commit f96cc38。
上游基线485726f；参考clone sibling tinker-cookbook-harbor-opd-rl不是Uni-Agent linked worktree。
本轮评分探针已停止，无新训练或Modal资源。HTML检查不等于CI或云训练通过。

## 冷启动 checklist
1. 读本文件、memory.md与HTML，再读Cookbook runbook和handoff。
2. git status核对两个worktree。主仓库历史未跟踪文件不要覆盖。
3. 先处理真实billing阻塞；不能仅凭key存在宣布账户验证。
4. 从P0继续，不重建工作树或复制训练器。任务路径示例仍需替换为真实数据。
5. 按实际产物更新验收记录；key与账户身份不写入报告。
