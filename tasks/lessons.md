# 项目经验

## 2026-09-06：项目记忆必须能在所属仓库恢复

- 用户指出训练交接仅保存在 sibling DSH worktree。本仓库须保留自己的
  `tasks/<branch>/handoff.md` 与 `docs/<branch>/project-status.md`，使新 session
  无需先猜测外部仓库路径就能确认分支、证据、目标和最近阻塞。
- 跨仓库原始设计、论文和实验账本保留其所有权；本地状态快照注明日期、来源
  revision 和证据范围。更新实验状态时同步本仓库快照，避免维护两套完整资料。
- 当前 `dsh-adapter` 是独立 Uni-Agent 仓库的开发分支。位于 DSH
  `.Codex/worktrees/uni-agent-dsh-adapter` 的旧 clone 不代表最新实现。
- 单测/trace replay、真实 process smoke、optimizer update、checkpoint reload、
  held-out uplift 是不同证据。后续代码修复不得追认旧 run 合格；远端状态须带
  查询日期，不能把旧 `status=running` 或历史停止记录当作实时状态。

## 2026-09-07：先比较全路径成本，再选择是否使用 GPU

- CPU 可连接模型 API，不等于能直接复用要求真实 Gateway ID 的训练 Agent/Task。
  评估成本时计入新增预算、receipt、隔离适配；不要仅按 GPU 小时费判断路径更省。
- DSH turn 不等于模型请求次数；SDK 的逐请求 max_tokens 与 RPC timeout 不等于
  总 token / episode wall-clock 上限。用源码与可执行测试证明预算实际在哪一层生效。
- `sdk-minimal` 的临时 cwd 不是宿主隔离，Cordis node:vm 也不是 containment。
  无模型初始化成功不授权在本机全权限环境运行模型生成的 host code。
- 本机 Ruff 通过不等于 CI 固定版本通过；显式声明本项目 first-party imports，
  避免两版 formatter 反复改动同一空行。
- 当前 runpodctl 2.12.0 help 不含 skill 示例的 terminate-after / stop-after。
  创建前验证真正可执行的停止机制，不把负载退出当作停止 GPU 计费。
- 导出卡住不能延后停费截止；停止后的存储费、补导出和资源删除也必须有截止条件。
- 独立 Pod 只隔离本机；同 UID 的模型代码仍可能修改 Pod 内 verifier/fixture。
  digest 复核可发现变化，但不构成不可篡改或候选权限隔离的证明。

## 2026-09-08：源码发布与运行时发布分开记录

- 用户补充DSH发布状态后，分别核查source SHA、可下载SDK/runtime及hash、Harbor镜像pin和实际运行版本；“已推送”不能表达全部完成。
- 新提交若主要为格式整理，先对比AST及少量语义变化，避免把大行数diff误判为架构升级；旧verification状态不能覆盖后续回执。

## 2026-09-15：Tinker路线
- 用户指定优先Tinker资源；先复用官方Harbor与OPD训练器，不再扩建2.4T scoring。
- clone与git worktree不同；本轮实际代码worktree是tinker-cookbook-opd-rl。
- 默认指令版9B不能默默改成Base；group reward与sampled KL分别验收。
- 细节纠正见 tasks/tinker-harbor-opd-rl/memory.md。

## 2026-09-15：Tinker API 验证证据
- Context7自动生成片段可能与安装SDK签名冲突；compute_logprobs_async返回list，训练async返回APIFuture，分别核对官方API与本地代码。
- Tinker SDK0.29.0在HTTP402计费问题时暂停并重试；长期等待不能直接归因为代理，也不能把402误读成模型缺失。用无密钥泄露的只读诊断确认服务原始detail。

## 2026-09-15 — 用户要求完整集成与逐项验证
- 不把系统缩成“能跑trainer”的脚本。先审计官方记录/轨迹/capture、评估、checkpoint、session关闭、任务资源契约与持久化是否实际接入。
- 在付费模型预检之前，用最终云镜像执行真实日志bootstrap；仅import、dry_run、沙箱oracle都不能发现所有训练支撑依赖（本次git缺失）。
- 参数非零更新应比较同一client的initial/final adapter；gradnorm、路径存在或采样文本变化不能单独替代。
- 明确原创smoke与官方Terminal-Bench的不同验收边界；SDK字段存在不等于模型服务能力实测。
- 用户要求“等等、先考虑完整集成”时暂停新训练提交，保留已完成与失败证据，再提交具体修订方案。

## 逐关验收（2026-09-15用户再次强调）
每关保留输入、配置、失败与清理证据；上一关失败不进入下一关。测试通过、API提交、API完成、参数改变、独立加载、能力提升分别记录，不能互相替代。

## 2026-09-15：真实 P0 闭环后的审慎验收
- `passed` 的工程含义与 `task_solved`/`score` 必须分别显示。此次 reload 工程通过，但任务仅 1/2，不能写成两题成功。
- 训练前2/2、后1/2只能作单次观察；没有配对seed，且并发不同，不能因果归结训练。实际SamplingParams、终态工具输出和grader原文应保存到评估产物。
- 同组奖励[1,1]使RL advantage全0。配置叫hybrid、参数非零变化，都不能替代非零RL学习证据。
- Modal SDK1.5.5 CLI下载目录前先创建目标目录；否则目录映射可能因目标is_dir判断产生IsADirectoryError。第一次失败需保留并查明路径，不能盲目覆盖证据。
- SDK0.29.0的create_rest_client经_get_rest_holder(_skip_session=True)走无session REST路径；不要仅凭构造ServiceClient就判断泄漏远端训练session。训练/采样session仍须实际close回执。
- 完成新关卡后同步当前状态和handoff，保留旧文件为历史证据；不能靠不断追加“覆盖前文”留下相互矛盾的冷启动说明。

## 2026-09-15：用户纠正算法选型不能只检查单一recipe
- 用户追问top-k后发现官方sdft.py已有[N,K]软目标和custom reverse KL；先前只检查Harbor OPD入口导致比较不完整。今后声明SDK训练能力或选择最终方法前，检索所有相关recipes和实际SDK形状支持。
- 工程baseline、官方推荐的某个配方、特定任务最优是三种不同结论。SDFT内deprecated不等于官方所有sampled OPD弃用；top-k条件KL也不是原始全词表KL。
- 更密集监督是候选优势，必须对照Teacher覆盖质量、Student可微targets、工具mask和任务收益；没有模型实测不能写top-k链路已通过。

## 2026-09-15：评估证据独立审查经验
- observer构造失败也要登记证据错误；不能依赖已创建对象才能验收。
- 事件计数不等于原文可靠：重读artifact校验哈希/字节，并对照reward与轨迹。
- 区分框架拒绝工具、真实命令退出、执行异常；缺少并未发生的调用事件不是记录故障。
- capture失败不能抹去已知任务分数；成功预算终止不能重复计数。
- 单batch顺序取题可能永远训练第一题。RL验收先看同题组内真实成败，不看全批方差或combined非零。

## 2026-09-15：外部Harbor任务集接入
- 728唯一任务ID不代表728独立源问题，按original_nl仅616家族；拆分必须按源问题分组。
- 从单一Smoke外推任务兼容性前，核对Dockerfile WORKDIR和输出目录；每次独立shell不继承上一次cd。
- task_manifest可能含答案，不能为了方便导入而把完整task根目录复制到Student环境。

## 2026-09-15：用户强调真正目标和公开数据
- 最终目标是独立Terminal-Bench成功率，不是框架复杂度、hybrid名称或双非零信号本身。
- 全成功与全失败都可能使中心化RL为0；两次成功只能支持该题偏易，不能确定其真实成功率。
- 联合路径必须检查实际优势相加及训练调用；模拟payload、云状态、权重差异与能力提升分别报告。
- 公开任务归档必须实查环境与参考解；NVIDIA千题分片全无solve.sh且配置含内部镜像，不能只据数据卡说即插即用。

- 公开测试任务必须遵守原始可见性契约：TaskTrove curriculum/multifile声明/setup_files可读，不能笼统隐藏所有测试而让任务缺信息。隐藏验证集和源家族隔离另做。
