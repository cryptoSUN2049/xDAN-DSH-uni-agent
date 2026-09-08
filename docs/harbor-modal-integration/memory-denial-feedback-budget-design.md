# Memory 拒绝反馈与重复预算修复

已批准实施。真实writer r1：首次读取来源成功，随后96次重复修改只读来源，均被正确拒绝；并非合法写目标被误拒。最终预算截断才触发Hermes解析错误。旧run/评分不改。

1. policy仅改善deny reason：列出当前配置的只读路径与单个写目标；说明新文件用create/path/file_text，来源不可改。只输出allowlist，不回显请求中的未知路径/参数，不输出文件内容。reader没有写目标，也不输出任何A来源路径。准入函数与verifier不变。
2. memory run_stage复用owned supervisor health callback。在线导出trace在runner结束后才写，故读取本run `homes/*/sessions/*/*/session.v2.jsonl` 的完整换行记录。忽略尾部未写完行；仅计真实tool/call和tool/result配对、isError=true、包含MEMORY_POLICY_DENIED的结果。以工具名+完整参数摘要比较，连续3个相同拒绝停止本stage；正常成功/其他结果或不同动作重置计数。各session独立，不能跨session累积。
3. 只终止现有supervisor创建的进程组，保留失败状态，不伪造完成/奖励，不启动B。回执仅存阈值/数量/动作摘要与当前日志相对路径；不存请求路径或内容。原1800秒墙钟上限保留，2秒巡检可能出现少量超出3次的调用。
4. 测试：writer可操作错误、reader不泄漏未知A路径；三连确认/未配对/尾截断/成功恢复/换动作/不同session；监督callback实际失败导致owned子进程退出。全链既有回归保持通过。

## 实现与验证

已实现policy反馈、`memory_denial_budget.py`与memory run_stage health接线，memory verifier/准入函数未改。先红后绿：Node新增反馈测试先因旧泛化错误失败；预算模块缺失红测试；实现后3组Node与120项组合CPU测试通过。实际CPU子进程生成三连拒绝日志后，被现有supervisor终止，退出PID不存在；合法恢复、跨session不合并及截断行均通过。全仓Ruff check/format-check通过（301个Python文件）。本轮未改旧run或远程checkout，未调用模型/GPU。
