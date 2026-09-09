# eligible：当前工作状态课程的准入含义

2026-09-09。此页解释当前已运行合同，不修改旧回执、评分或准入规则。

`eligible`由本项目可信verifier生成，表示该轨迹是否可按当前合同被训练/评估消费；不是学生自行声明，不等于任务分数。`finished`记录会话完成，`fresh`绑定本次执行，`reward`记录任务成绩。完整但答错的任务可以eligible=true且reward=0。

## 当前实现为何拒绝

`examples/dsh/capabilities/work_state/verifier.py:79–104`检查真实工具调用：未批准工具、参数格式问题或不在允许读写集合内的动作写入unsafe列表；`eligible = complete and not unsafe`。原输入文件SHA、工具调用/结果配对及输出快照等完整性检查另行执行。

r4独立reload的WS06 writer真实seq14请求对只读sources/request.json执行str_replace，old_str等于new_str，seq15被policy拦截。仍是未授权写动作，verifier记unapproved_action，因此finished=true、fresh=true、reward=0、eligible=false。输入并未因此被允许改写；unsafe变量名不证明已经造成副作用。

需要准确区分：同一会话seq19在允许的index.md路径上对尚未创建的文件用str_replace，也被环境拒绝；随后create成功。该路径在write_files白名单，不应误报为“未授权索引路径”。不是所有工具错误都会自动使eligible=false；本次明确触发项是只读源文件写入尝试。

下游stage和trajectory_audit要求eligible=true；训练端整组失败后可补采，严格评估端传播异常。固定VERL汇总在全部评估批次后才写，因此单条失败会使此前合法批次没有最终消费dump。这是当前工程设计/调度限制，不能归结成CUDA、checkpoint加载失败或“零奖励不允许训练”。

## 概念审查与后续选项

这是本课程自定义的保守规则，不是Uni-Agent/VERL要求任何错误尝试都丢弃。应区分：

- 环境确实拦截了错误请求，输入未变且轨迹完整：原则上可设计成保留的失败样本，由奖励反映错误。
- 输入真的被改、轨迹或工具结果缺失、奖励错绑、来源不明：仍不应作为有效训练数据消费。

若调整前者，必须新增明确的“已被拦截且无副作用”证据规则、奖励/跨A-B归因与回归测试，固定新verifier版本后新run验收；不能直接把所有eligible改true，也不能追改r4失败回执。当前评估选择器只隔离结果落盘，不暗中改变该训练合同。
