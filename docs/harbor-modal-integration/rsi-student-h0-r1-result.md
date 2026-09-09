# RSI 学生实验：H0 父策略真实基线

2026-09-09，源码 `b1c568bc4a158309f1435d907cd51ec96538ea92`，远端 `/workspace/rebuild/uni-agent-rsi-b1c568b`；DSH 0.1.3a2、VERL fefb080 + preserve-finish-reason-v1。Run `/root/runs/rsi-student-h0-r1`，manifest SHA256 `f37d7cb1430c872ea339e3a8b4be76eb488c1337b5af2e0a376939930b113b68`。

## 真实结果

| 开发任务 | 行为与输出 | 奖励 | 准入/完成 | 生成 token |
|---|---|---|---|---|
| inspect-discovery | 请求 cordis_inspect_list 被父策略拒绝，真实返回 unavailable | 0 | true / true | 38 |
| file-constraint | 成功读取唯一允许文件并准确引用，但 value 输出 max_attempts=3，而非要求的值 3 | 0 | true / true | 89 |

两条均实际进入 TQ 并唯一读回，原始 NPZ/token/trace/receipt 重审 `audit_parent` passed=true；SDK policy 路径、冻结父 active 与模型字节通过复核。未完整或未知样本没有混入。父基线没有注册子候选、没有晋升、没有 optimizer 或参数更新。

启动21:38:04(SGT)，子进程316725，监督耗时314.622秒、exit0、无健康检查失败；框架记录实际任务执行51.7秒。GPU 曾使用约30GB显存，作业结束已释放至0MiB。初始化包含Ray/worker启动、模型加载及JIT，不能把总耗时全当生成耗时。

完整可核摘要在 [JSON](rsi-student-h0-r1-result.json)。`runtime-binding.json.receipt_sha256` 是回执文件字节hash；`audit_parent` 的 proof.receipt_sha256 是轨迹绑定的canonical receipt hash，两者表示形式不同，不能当作同一字节摘要比较。

## 判读与下一步

第一题是预定的父权限限制，合法失败；第二题是字段值格式错误，不能归咎于权限不足。新增inspection能力不会自动修复该输出错误。两题均零分不触发作业异常，也不改原reward。

下一步把现审计器产生的白名单失败诊断交给同一固定学生P，记录真实声明式提议。合法提议仍需隔离H1比较才能判断是否有收益；没有收益不强制晋升。本报告仅证明父基线执行和审计，不能证明RSI能力提升或RSI RL闭环。
