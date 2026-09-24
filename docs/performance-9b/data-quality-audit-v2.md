# 数据质量审计 v2

2026-09-25，本轮在 CPU 节点 `157.157.221.177:16358` 执行，不启用双卡训练。

## v1 失效与纠正

`quality-gate-v1` 的 16,732 条所谓 training-ready **作废**。门禁曾将上游模型字段升级为鉴真、README 语言声明用作样本语言，并将缺失 reasoning 自动设为 exclude；其判断不足以证明训练准入。
远端 manifest 已改为 `INVALIDATED_DO_NOT_TRAIN`、approved_rows=0；原输出改名为 `invalid-candidates-do-not-train.jsonl`，旧 manifest 留存为 `invalid-original-manifest.json`。没有启动训练。

v2 仅提供字段回填和诊断，不具备授予 training-ready 的权限。所有样本保留语义质量、语言检测、污染检查、teacher provenance review、tokenizer/mask 待验收标记。

## 本轮实现

- 固定原文件 SHA256 验证后，按 repo、revision、source_row 联结元信息。
- 修正 source_file 为上游相对路径；README 可从父目录读取。
- source model 仍为 row_claim；语言声明放 provenance，不能冒充逐条识别。
- 原始 thinking markup 保留，缺失 reasoning 保持 unresolved。
- 非 train split 不能进入训练候选；跨 split 的任务组被拦截。
- 输出 annotated、quarantine、空的 structural_candidates 和报告；不能据此宣称最终合格池为空，只能说当前未授予准入。

## 下一步质量闭环

1. 验证联结回填逐字段与原版一致，统计声明缺失及冲突。
2. 修正工具审计对 next-action 前缀的误判：最后一个被监督的调用没有结果可以合法，历史调用缺结果必须隔离。
3. 严格 JSON 校验（重复键、NaN/Infinity）、工具 schema/调用顺序、重复 ID、监督目标与语义 hash 复算。
4. 逐条语言识别；保留非俄语多语能力，不擅自改成 English-only。
5. 教师证据分级、近重复/评测污染、任务组隔离、抽样语义质量与模型模板 mask 验收。
6. 完成后计算真实合格池及 20K 分域缺口；当前不抽样、不启动训练。
