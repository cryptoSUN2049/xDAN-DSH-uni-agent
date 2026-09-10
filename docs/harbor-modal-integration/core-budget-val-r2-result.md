# 累计生成预算修复：真实 GPU 触顶复验

固定代码5e6b326，复用固定DSH/runtime、配对VERL及基础Qwen3-4B。WS06公开任务，val模式，不更新参数、不加载母checkpoint。

core-budget-val-r2已终止：exit1、740.018秒、健康检查失败0。NPZ实际模型token为8192，工具/context mask0为6014，prompt为1495；生成logprob有限，NPZ哈希与元数据一致。materialization_reason正确为max_generated_tokens，与累计计数8192一致，补齐r1的精确触顶原因漏记。

writer仍finished=false、eligible=false、fresh=true，B未执行，原准入拒绝该轨迹。此退出符合旧合同；不改写成任务成功，也不声称有训练消费或学习。真实触顶记录验收通过，整体预算验收仍等待正常完成路径。

七项原件复制到/workspace/reports/core-budget-val-r2并逐文件回读SHA，审计见同名JSON。旧4232-r1结果不覆盖。

下一条core-budget-normal-r1已通过现有launch入口发起，外层PID83576；固定相同5e6b326，WS01-v1-s2001，val。准备清单/root/runs/core-budget-normal-r1-data/manifest.json，日志/root/runs/core-budget-normal-r1-launch.log。继续检查活进程，不能把已发起当完成。

## After-run 版本复核

原5e6b326入口check(manifest, after_run=True)在CPU完成并通过，确认源码、runtime、输入和配置身份。报告/workspace/reports/core-budget-val-r2/after-run-source-check.json，SHA256 04258117d4f4a3e8f21b2de88ebef2decca646d090b337c7b45b5fc6db429018。它证明版本/工件完整性，不改变未完成任务的评分。
