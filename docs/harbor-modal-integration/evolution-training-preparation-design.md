# Evolution 训练准备接线

复用 M2 单 TaskRef 工程入口，新增显式 `--evolution-binding` sidecar；不增加任务分发或更改评分。

变更：prepare_m2_training.py、registration.py 及对应 CPU tests。验证 TaskRef 全树摘要后，要求 fixture/metadata 来自 task/tests 固定文件，并与 task/evolution.json 的 kind/hash/source manifest 一致；加载原评分源码绑定并核 runtime/profile/patch。T2 与 evolution 互斥；空 patch 与有 patch 缺绑定仍拒绝。

输出 Task YAML 与 postprocessor kwargs 传递同一完整 operator binding；Parquet 仅标注一个原 scenario 的重复工程运行，沿用 same-task-engineering-evaluation-not-generalization。registration wrapper 原样转发，由最终审计独立复验。

测试先红：真实 prepare→Parquet/YAML/Hydra 合同，错误描述、元数据路径与互斥绑定拒绝且无输出；registration 参数转发；原 T2/file lane 全部回归。不运行 GPU、不更改旧 reward。
