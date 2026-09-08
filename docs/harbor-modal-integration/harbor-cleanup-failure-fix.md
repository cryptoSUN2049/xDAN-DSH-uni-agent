# Harbor 清理确认与不合格试次终态修复

## 已观测根因与范围

M2 v2-r1 的前四 job（1 val + 3 train）成功，reward=1。第五个 `job-48df52c2ce44416b856e13855ec99315` 于2026-09-08 23:35:25启动，23:36:44.915因 `max-tokens`、finished=false被 trace bridge拒绝。61事件与10对工具call/result的哈希一致，非SSH问题。worker 23:36:45.657将异常记成清理未确认，随后旧slot卡在cancelling；新job每约2–3秒被加入再在ledger.start拒绝，观察到58cancelling。

executor在Docker agent/verifier container/network/volume独立查空后，证据收集抛异常；通用异常丢失了已通过的清理事实。worker.submit仅检查async task.done，没在新queued插入前检查ledger活跃/未确认slot。

## 最小设计

- 新无Harbor依赖 `execution_outcome.py`，定义 `CleanExecutionRejected`（固定错误分类、trial id）。这不是可训练零分，没有reward或有效轨迹。
- executor仅在 `_confirm_cleanup` 真正通过后，把返回trial的身份/证据/验证阶段失败包装为此显式终态。取消、deadline、trial.run异常、Docker库存非空/未知均不包装，继续阻塞。
- worker仅接收这个显式类型后封存无训练产物的cancelled manifest并释放slot。旧job同身份重交只返回原终态，不执行重试。
- ledger.submit在同身份幂等返回之后、创建新queued之前，事务内拒绝running/verifying/cancelling。既有queued排队语义保持，避免任意新cancelling风暴。
- 原unfinished准入、reward和v2 scorer完全不改；原清理未知行为不改。

## 文件与验证

`uni_agent/tasks/harbor_dsh/{execution_outcome,executor,worker,ledger}.py`；对应executor/worker/ledger回归测试。

先红测试：真实清理通过后的trial失败产生显式类型；清理未知不可产生类型；worker封存cancelled且允许下一新job、拒绝旧job重试；未确认slot下新submit无新增ledger行或目录。完成后运行定向测试与Ruff。

## 实现与回归结果

已实现。先运行新增测试得到4失败（缺显式终态类型，以及实际复现新submit仍被接纳）；修复后executor/worker/ledger/client/protocol共169项通过。Ruff check与format检查通过。

新增用例覆盖：清理6次库存检查都为空才产生typed rejection；首个库存非空仍普通异常；正常与already-cancelling两状态均可封存cancelled、无reward/artifacts；旧request幂等不会重新执行；下一新job可执行。未知清理后的3次重复提交全部在创建目录/插入行之前拒绝。两个SQLite连接对running/verifying/cancelling状态都拒绝新submit，同身份历史查询仍允许。

取消/超时/未知清理原测试保持不确认、不释放。没有把旧r1 ledger改为通过，也没有自动重发旧job。新运行仍需真实Docker验证取消终态和继续执行；169项CPU通过不代表GPU训练已恢复或获得参数更新。
