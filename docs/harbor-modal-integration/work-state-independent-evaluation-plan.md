# 固定四题独立评估收尾修复

目标：落实已批准的“任务失败保留、继续评估其余任务”，每题独立保存真实消费审计，拒绝伪造零奖励/TQ或放宽准入。

## 结构

固定母checkpoint及四题清单 → 串行prepare/check/launch(每题独立run) → 原audit → 原因/实际消费/状态逐题落盘 → 完整汇总。成功任务有独立dump；失败任务保留原trace与异常；未知审计错误、源码漂移、GPU未释放停止继续派发并保留not_run。

## 修改文件

- examples/dsh/capabilities/evaluate_work_state_tasks.py：复用现有准备器与监督器；新增串行控制器。
- tests/uni_agent/examples/test_evaluate_work_state_tasks.py：失败隔离、实际消费门、取消/清理/覆盖保护。
- docs/harbor-modal-integration/work-state-rl-runbook.md：统一入口与当前状态。

## 合同

四题固定WS01/03/05/06 variant1 seed303，同母checkpoint、相同预算。每个manifest记录单题selector和完整版本谱系；不覆盖旧运行。GPU再次空闲才派发。任务执行失败可继续，审计损坏或准备错误停止；取消不被当作正常失败吞掉。汇总区分attempts_completed与all_consumption_verified，非全部通过退出非零。脚本不改模型、VERL或DSH实现。

## 验证

先失败测试，再实现：中题失败不阻止下一题；exit0缺实际消费不能通过；清理不明停止；已存在目录拒绝；异常/取消汇总保留四题。CPU回归与Ruff双门后固定提交部署，GPU按四题真实执行，原审计复核，文档交接commit/push。

此为当前已授权异常处理修复的最小实现；非训练准入或奖励合同变更。
