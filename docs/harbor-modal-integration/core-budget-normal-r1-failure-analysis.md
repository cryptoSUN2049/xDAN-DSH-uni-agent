# 正常预算路径的零奖励：离线失败分析

本轮只读本机已核SHA的关机归档，未调用GPU、未更改提示/奖励、未重新签发回执。范围为core-budget-normal-r1的一个公开WS01任务，固定基础模型。

- A的index JSON逐字段等于权威workflow：capacity=2869、schema_version=8，completed/required/dependencies完整保留。本题不是事实保存遗漏。
- B共有3次实际工具调用：view公共notice、create配置、create计划。没有实际读取memory路径；不能把memory在磁盘上存在当模型读过。
- 最终config={capacity:100,schema_version:1}，plan=[config.json]。文件创建真实成功，但业务值及动作ID错误；与原reward0一致。
- B仅302生成token，远低于8192，不是此次预算限制导致无法继续。它主动结束了任务回合，并未正确完成业务。

所检查fixture/index/trace/outputs均匹配归档内逐文件SHA，清单见同名JSON。正式token/消费/receipt身份仍以core-budget-normal-r1-result为准。

下一诊断应优先测试真实A产物条件下的检索/事实使用，不能按此一题宣布角色文案是因果根因。待批准的reader提示修订包仍未实施。也不能只提高步数、GPU吞吐或奖励文件数量来解决本题。
