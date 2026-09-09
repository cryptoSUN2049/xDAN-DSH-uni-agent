# Work-state：训练与独立评估分开执行

2026-09-09，按用户工程链路优先与正常任务失败不应拖停训练的纠偏实施。本次仅调整现有recipe调度，不改任务、奖励、安全策略、Gateway、DSH或VERL补丁。

## 首因与最小修复

r2/r3均在step4保存后、周期val的WS06 writer尝试写只读源被拒；严格val adapter传播不准入异常，导致训练作业退出。全零奖励没有触发停止。固定trainer先保存、再val、再写metrics/rollout JSONL，所以CK4存在却缺step4指标和消费dump；不能补造这些证据。

新work-state mode=train设置trainer.val_before_train=False、trainer.test_freq=0，保持8步、n4、SAVE_FREQ4（4/8保存）及原sync trainer。固定VERL最后一步也受test_freq>0门控制，不会偷偷再执行val。原mode=val/reload继续严格执行四公开dev。任务失败与准入拒绝如实记录，不伪造TQ、reward或eligible。独立eval失败仍报告为失败，不把中断报告改成成功。

## 文件/API/测试

仅prepare_memory_training.py及其现有测试、runbook与goal/handoff更新；无新CLI参数。prepare/check绑定关闭内联val的调度合同，拒绝未声明打开它的清单。先新增真实shell→Hydra最终配置回归RED，再改两个override并GREEN；val/reload行为和4/8保存不变。

## 拒绝组与边界

训练端保留sync_refill_failed_groups=True。失败sibling导致完整n4组不写trajectory，TQ记录prompt failure；ReplayBuffer对已终结失败组取新prompt补采，dataloader耗尽后重开并赋freshUID。不能把补采算新增独立任务、不能将拒绝组计入消费，也不能保证所有task都一定产生合法组。

该refill没有内部失败次数上限；未终结actor崩溃或持续失败可能无进展。保留现7200秒owned supervisor墙钟截止和定向进程组清理；不无界无人监督运行。报告实际任务覆盖、拒绝/补采与消费，不能仅以8个step宣称8个不同任务。

## 放行与验收

新commit→GitHub→独立r4 checkout→精确VERL补丁apply/check→原venv prepare/check→GPU训练完整保存→独立checkpoint reload与fresh评估。无需重复安装环境或修改运行中的checkout。第一层验收工程执行/消费/保存/加载；非零任务梯度和参数更新另验，任务提分再后置。沿用已取得的protocol3四dev基线作诊断，不能改旧结果。
