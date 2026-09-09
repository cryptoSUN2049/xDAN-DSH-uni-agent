# 四题独立reload：完整终态覆盖，3题消费通过、1题截断拒绝

2026-09-09。Suite `/root/runs/ws-r4-isolated-eval-r1`结束，`all_attempted=true`、`all_verified=false`、`stop_reason=null`、汇总exit1。四题均有独立终态；没有因单题失败提前停止整个任务集，也没有把失败题伪造为可消费样本。

固定源码`9dea127bf7bb69eb916aebcc0ab69ff86f53df08`，固定DSH0.1.3a2、显式VERL结束原因补丁、母r4 step8；每题n1独立进程和新A/B身份。部署前追加after_run_recheck三项CPU回归exit0，原报告`/root/runs/work-state-singletons-cpu-r1/result.json`。

| 任务 | 子进程 | 秒 | 原A/B奖励 | 实际消费 | 结论 |
| --- | --- | --- | --- | --- | --- |
| WS01 v1 s303 | 270480 exit0 | 490.011 | A0 / B0 | 1组、2唯一行 | verified，业务得分0 |
| WS03 v1 s303 | 275680 exit0 | 435.010 | A0 / B0 | 1组、2唯一行 | verified，业务得分0 |
| WS05 v1 s303 | 280630 exit0 | 405.010 | A0 / B0 | 1组、2唯一行 | verified，业务得分0 |
| WS06 v1 s303 | 285519 exit1 | 565.013 | A0，B未执行 | 0组、0行 | A max-tokens被拒 |

前三题A/B原回执均fresh=true、finished=true、eligible=true；verified只证明加载、身份、评分与唯一消费审计通过，不能推断任务reward1。总计3完整组/6唯一行，**没有业务reward1，也没有新训练更新**。

WS06原A envelope记录246 events、`finish_reason=max-tokens`；原回执fresh=true但finished=false/eligible=false/reward0。框架异常为`TrajectoryAuditError: trajectory 0: reward_info must declare finished=true`。没有B回执，没有crosswalk消费；不能将A失败0计作合法训练组。

## 加载、母checkpoint与清理

四题日志均保存从母step8加载model/optimizer/RNG/lr_scheduler的记录。执行器每次launch返回后运行`recipe.check(after_run=True)`，重新核母checkpoint11文件及版本身份，再做原消费audit与同题核对，最后GPU清理检查。最终`stop_reason=null`及逐题结果意味着这些门未触发异常；原summary绑定全部母文件SHA。末次现场GPU0%/0MiB（主线程10:44:42 UTC实查）。没有修改原run、回执、评分或母checkpoint。

完整证据见[JSON](work-state-independent-evaluation-r1-result.json)：原summary/hash、逐题原消费audit、加载日志/hash、7份真实stage回执及其SHA、WS06原运行终态。首题已冻结报告不追改。

## 工程与学习分别解释

按用户E4规则，此次完成固定四题独立reload后的终态覆盖、成功题真实消费、失败题原因留存、母checkpoint及清理核验。`all_verified=false`准确保留第四题未准入；不宣传4/4成功，也不因合理记录的任务失败无限延长工程阶段。原W4非零梯度和有效参数更新仍未通过，不能将E4执行覆盖替换整个工作包完成。

[母训练归档](work-state-r4-evidence-archive.md)保留r4及两次旧reload失败。当前suite另行归档，不复制母checkpoint或母run。
