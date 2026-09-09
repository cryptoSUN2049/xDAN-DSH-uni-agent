# Work-state train r2：周期评估拒绝，未完成八步

本报告是已结束作业的只读事实审计，未改原始回执、未运行GPU、未执行参数delta。机器可读证据与10份原始文件SHA见 [result JSON](work-state-train-r2-result.json)。

## 运行与失败

- 源码 `12902fb8849d9fdfa118686207669bbedfcfec37`，远端 `/workspace/rebuild/uni-agent-work-state-r2`，任务protocol revision 2。
- run `/root/runs/work-state-train-r2`；监督child PID221585，exit1，1195.029秒，reason=`training-exited`。
- global_steps=4 的周期validation中，`work-state-ws06-v1-s303` 的writer A不准入；chain `memory-57baab3f7c5549b4b7ab196eda12fc0d`。严格适配器传播 `TrajectoryAuditError: DSH verifier receipt must declare eligible=true`，不把该链写入TQ。
- 真实调用顺序：view只读request → 对同一request执行str_replace → view尚不存在的handoff → create handoff。第二次调用被 `WORK_STATE_POLICY_DENIED` 拒绝；即使old_str/new_str相同，写只读源仍属越权。随后补写handoff不能清除该次违规。
- DSH将Agent结束记录为 `completed`，31事件、4工具调用，回执finished=true/fresh=true/eligible=false。已证实拒绝原因是业务越权；仅凭DSH结束记录和调用次数不能排除底层生成截断。该A未进入B，也不在下述已消费轨迹EOS审计范围内。

## 训练与checkpoint的证据边界

metrics文件 `/workspace/rebuild/uni-agent-work-state-r2/dsh-work-state/work-state-train-r2.jsonl` 仅有initial val和step1–3。三步的reward范围、advantage范围、actor loss/pg_loss/grad_norm均0；stdout也只打印了这三步的梯度指标，未发现step4梯度值。

日志04:44:12.964明确开始保存 `global_step_4`；云盘存在model/optimizer/extra_state/data及模型配置文件。因此不能把“三条metric”说成只执行了三轮，也不能把step4 checkpoint说成第四步有效学习。训练第四轮后的周期评估失败发生在最终metrics输出之前；本报告未反推出或补造缺失的step4梯度。

checkpoint目录 `/workspace/uni-agent-g1/checkpoint/work-state-train-r2/global_step_4/`：model shard 8,889,735,011字节，optimizer shard 132,552,363字节，extra_state 15,141字节，data.pt 1,499字节；完整结构清单见JSON。这里只核存在与大小，未加载张量、未做参数变化比较、未完成独立reload。

## 实际覆盖

- train已产生16条合法A/B链：WS01八条、WS03八条；所有终态B reward0。stage回执共32份。该数量是生成事实，不能代替完整TQ消费审计。
- validation已有7条合法A/B链：WS01/03/05各两条，WS06一条；B全0。另一次WS06 A不准入。initial dev为4/4合法但严格成功0，step4周期dev未完整通过。
- 保存的训练消费JSONL只有 `rollouts/1.jsonl`、`2.jsonl`、`3.jsonl`。不能单凭此断言step4未消费；也不能凭stage数量宣称4组消费已审计。
- 尚未完成计划8步；train未覆盖WS05/06。不存在本课程有效任务更新、能力提升或独立reload的验收结论。

主线程另以新审计代码执行 `generation-boundaries-audit.json`，本报告只读复核：11个crosswalk中7组有完整实际消费证据（initial dev4组、train step1–3各n4），共32条A/B轨迹；另外4组未在现有消费日志中得到证实，包含step4训练组与周期val前三组。unknown/duplicate/error为空，整体passed=false，原因包括run失败及未全部消费，不能改成通过或宣称step4已消费。

上述32条已消费轨迹的194个原始生成段全部观察到EOS，0 non-EOS、0容量边界tie。EOS IDs为151643/151645，模型config及generation_config哈希保存在JSON。该证据只适用于被审计的已消费轨迹，不覆盖最后拒绝的WS06 A；也不恢复backend原始finish_reason，不代表模型学习有效。

## 下一步

保留本次零奖励与安全拒绝事实。protocol3应以新源码、新prepare、新run纠正空目录可创建及业务输出schema说明；不改安全权限、源真值或旧评分追认r2。先检查新fresh评估与真实n4终态B奖励分布，出现真实学习信号后再执行参数/optimizer和独立reload验收。
