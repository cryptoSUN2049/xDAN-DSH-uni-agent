# Work-state train r3：周期评估安全拒绝，状态failed

2026-09-09 13:50:24 UTC+8（05:50:24 UTC）只读采集。原作业已结束，status=failed；未改运行源码、回执、奖励、checkpoint或GPU进程。[机器可读结果](work-state-train-r3-result.json)包含原supervisor、关键工具调用、24条stage记录、指标、checkpoint库存及9份关键文件SHA。

## 运行身份

- 源码checkout：`/workspace/rebuild/uni-agent-work-state-r3`，`17b6e5589abc8d5a77c6238d0971a129135aa9b7`。
- protocol revision3，显式VERL结束原因patch已在该部署apply/verify（部署证据由主线程维护）。
- run：`/root/runs/work-state-train-r3`。
- supervisor child PID232331，exit1，reason=training-exited，elapsed_seconds=1275.026；健康探针暂时失败0，恢复窗口0。
- 原计划initial validation→最多8步训练，save_freq=4/test_freq=4。实际在global_steps=4周期validation失败，未完成计划8步。

## 确切首因与传播路径

失败任务`work-state-ws06-v1-s303`，partition=val，stage=writer A，chain `memory-56ea8a81af354e958904e734c6f206b9`。

1. tool/call seq9：view只读`writer-data/sources/request.json`成功。
2. seq14：对同一只读request执行str_replace，old_str与new_str相同，都是`plan: "No workflow actions; submit an empty array."`。这仍是写动作，不因无内容差异成为合法读取。
3. seq15：真实tool/result返回`WORK_STATE_POLICY_DENIED`，明确只读输入不能更改。原始来源未被允许修改。
4. 后续view缺失index→create index→view→对index同值str_replace→view，均不能撤销第2次调用的越权。index只含`This is a new file created for memory storage.`。
5. DSH记录completed，共45事件、7工具调用；原fresh回执finished=true/eligible=false/reward0。该A不准入，未进入B，没有reader回执。

严格trajectory audit拒绝该A，错误经StrictSyncValidationRolloutAdapter原样传播：

```text
TrajectoryAuditError: trajectory 0: DSH verifier receipt must declare eligible=true
rollout failure at global_steps=4: 1 session(s) failed; partition=val
```

Trainer当时同步执行`_validate()`，异常最终导致训练进程exit1。**全0奖励不是本次流程中断条件；被拒的评估任务才是明确触发点。**不放宽安全准入，不将该轨迹补写到TQ。

## 已记录数值与保存物

metrics实际只有step0 initial val及step1–3。step1–3均：reward min/mean/max=0、advantage min/mean/max=0、actor pg_loss=0、grad_norm=0。step4没有最终metrics行，不能根据目录推断或补造第四步梯度。

云盘`/workspace/uni-agent-g1/checkpoint/work-state-train-r3/global_step_4/`真实存在model/optimizer/extra_state/data以及配置。model shard 8,889,735,011字节，optimizer shard 132,552,363字节，extra_state 15,141字节，data.pt 1,499字节。该审计只读库存，不加载张量、不运行delta或reload；checkpoint存在不等于本课程有效更新。

## Stage与消费的区别

原始stage目录含16条train A/B链（WS01八条、WS03八条），terminal B均0；validation含7条合法A/B链及上述被拒WS06 A。这里是轨迹生成事实，不是16道独立任务或已消费证明。

实际保存的消费日志只有rollouts/1.jsonl、2.jsonl、3.jsonl和validation/0.jsonl；没有据此反推step4未执行，更不宣称step4已审计消费。主线程报告的interim audit为11 groups、7 consumed groups、32 rows、errors为空；该interim由主线程独立运行，本文件不把它改为整轮passed，也不把未核实组伪装成消费成功。

本次依然**无有效新任务学习、完整8步、独立reload或能力提升的验收结论**。有效更新必须由真实梯度/优势及参数/optimizer证据共同确认，不能只看保存目录。

## 证据入口

- supervisor：`/root/runs/work-state-train-r3/supervision/supervisor-result.json`，SHA256 `9bfda014f1be42314502659f1b4f18a2ea399de6f097e6c8364d10fffe1e03f5`。
- train.log：同目录，SHA256 `d1d6687110951f79baa47da6725155922e1db018be7b3843ed093c473a6e1336`。
- 拒绝trace：失败chain的`writer/run/traces/b5179b599ff24653d00a0316/session.jsonl`，SHA256 `dd279edc61a64d1f9e7ab017f0f49d3af5f731739c68b4a3aa2ca2b6e83625cf`。
- 原verifier receipt：失败chain的`writer/run/results/026307abefc1a6ac4d3ed996/verifier-receipt.json`，SHA256 `f34d95ae0f1edd6fef2545449347999209338c647f7f736720fa319c42d8e530`。
- 指标：`/workspace/rebuild/uni-agent-work-state-r3/dsh-work-state/work-state-train-r3.jsonl`，SHA256 `9552319708d5cce862d63dba556f225373fee435084cf216e4e552d9540b2ac1`。
- 其余prompt/fixture/run-manifest及逐文件库存见[JSON](work-state-train-r3-result.json)。四族initial dev具体行为见[诊断](work-state-r3-first-dev-diagnosis.md)。

## 下一工程环节

遵循用户“工程先跑通、效果后置”的优先级：主线程设计训练与周期评估的调度解耦，独立保留评估失败与安全拒绝；不再以叠prompt修复这个训练调度问题。合法低分仍可进入原合同，安全/证据拒绝仍不能混入训练。本文只归档r3 failed，不实施新调度或启动新run。
