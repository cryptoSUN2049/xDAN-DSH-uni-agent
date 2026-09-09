# 短课程独立 reload 最终验收

两条固定公开开发题均完成独立进程加载、真实 A→B 执行与最终消费审计。运行源码 `b47521df1d6cd6b930ab6ac85ef41c670f2405d2`，离线审计源码 `d4401d33c47af623d202a8b52be8266da5ec86f2`。完整原始摘要见[JSON](work-state-short-reload-final-result.json)。

| Run | 退出/耗时 | 原B奖励 | 实际消费 | 母checkpoint |
|---|---|---|---|---|
| ws-short-reload-901-r1 | 0 / 425.010秒 | 1 | 1组、2唯一A/B | 11文件摘要不变 |
| ws-short-reload-902-r1 | 0 / 400.009秒 | 1 | 1组、2唯一A/B | 11文件摘要不变 |

两者实际日志分别记录加载step8的model、optimizer、RNG和lr_scheduler；原reader回执fresh/finished/eligible均true。新审计passed=true，无未知、重复或缺失消费。两次均为val_only，不产生新训练更新。母实验为 `ws-short-train-r1`；母checkpoint在 `/workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_8`。

## 原失败与修复

901原始审计 `final-audit-r1/consumption.json` 的false保留。原因是固定VERL评估dump把同session终态B奖励写到全部轨迹行，而旧审计错误地以A原reward0核对评估行score1。新审计仍独立核原A/B回执、实际trace和业务结果，仅对validation dump按已验证同链B终态分数比较；train仍核原阶段分数。修复33项CPU测试包括固定VERL真实validation代码块的广播语义测试。

新报告位于各run的 `final-audit-d4401d3/consumption.json`，不覆盖原失败，不修改母源代码、checkpoint或运行清单。部署隔离目录名包含审计提交，避免复用已有不同源码目录。

## 结论边界

联合训练消费、有限非零梯度与参数变化报告，本短课程的原生 DSH→Uni-Agent→VERL在线RL→checkpoint→独立reload/fresh评估工程链已得到实测证据。两题属于公开开发集、各一次采样，未做同条件训练前对照；不能据此量化提分、声称封存泛化或全部记忆/上下文/RSI能力已完成。旧四族r4的零更新结论保持。
