# 母课程 D3 失败 sibling：只读根因审计

范围仅 `/root/runs/context-v2-curriculum-r1`，固定remote `d3084f2`；未修改源码/旧run，未操作当前reload或启动GPU。

## 根因

此处不是SDK/进程崩溃。学生两次读取短索引文件时请求越界行号，DSH明确返回工具错误；现context v2评分规则将任何 `invalid_source_range` 作为不合格动作，恢复后仍硬拒整episode。

- group `fa49da52-3421-4064-9e8d-5ca2e72f651f`，train-D3，step5，sibling3。
- Gateway `session-sample-0-rollout-3-0b61c56d7ed04d1eb473d192e32af597`。
- 19:48:46 开始；19:48:58 DSH completed，40 events，Task正常返回reward0、finished=true。
- 第1次和第4次调用：`str_replace_editor view sources/index.txt view_range=[1,5]`。索引只有1正文行、尾空行后DSH按2行计算；真实tool result均isError=true，提示5超过文件2行。
- 第5次调用改为[1,2]后成功；current/old正文5行、含尾空行6行，对它们[1,5]及[1,6]均合法，不能混为同一种问题。

原始trace SHA256：`7903ccbfce20c63cf15ae0bc516b36f41b3ef5e180d6bf5ca1e6dd0b8c9cea3b`。
原始receipt：`sha256:9afda5727fe7238de92baf1000cffb363dbb1b666d77b1aa9dfb96da4d4fe3e9`，fresh、finished=true、eligible=false、reward0。原文件位于 `artifacts/results/a227a8ed63058291a3756ed6/`。

固定原源码CPU独立重评分结果：read_coverage=1、semantic_accuracy=1、citation_coverage=0.1818181818、valid_json=true，unsafe包含两次invalid_source_range。因此Task成功返回不等于trajectory允许进训练。`trajectory_audit`拒绝该不合格回执；Framework没有导出该sibling可消费trajectory，strict组拒绝其他三条，主trainer随后refill并继续12个有效batch。19:48:58日志中的 `rollout failure at global_steps=5` 与最终group_size_mismatch是后续结果，不是首个原因。

## 是否需要修复

本轮没有发现需要修SDK、Gateway、解析器或optimizer的bug。当前门按已定义规则拒绝、没有消费异常组，应保留。短索引读取的可复现触发是：文件为单行正文加换行，view_range=[1,5]；用现测试 `test_invalid_range_is_rejected` 所覆盖的越界语义即可复现评分拒绝，不需GPU。

后续更低成本改进是初始操作说明：未知文件长度时省略view_range或用[1,-1]，不提供答案。不在当前运行中修改prompt/评分，也不为追求12唯一题而重打旧回执。若将来希望把可恢复范围错误和越权动作区别评分，需要独立版本rubric审阅；这属于任务设计，不是工程闭环前置条件。

## 本次启动准备纠正

PRINT_COMMAND通过ops会创建RUN_ROOT/command.txt与run-manifest.json；不能当无副作用探针。本次准备曾污染reload目标目录，root已旁路保留两份打印证据后启动PID178933。后续打印使用独立scratch RUN_ROOT并在打印后再次检查正式目标不存在。tasks/lessons.md与课程result.md已由root记录，本审计未覆盖那些文件。
