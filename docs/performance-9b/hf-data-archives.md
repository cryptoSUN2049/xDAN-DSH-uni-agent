# Performance-9B 数据集 HF 归档

2026-09-23。用户要求保存到 HF；使用 gump2049 私有 dataset 仓库。仓库别名用于项目分类，不改变上游归属。

## 已完成

### gump2049/xDAN-9B-Math-RL-Nemotron-v2

- 入口：https://huggingface.co/datasets/gump2049/xDAN-9B-Math-RL-Nemotron-v2
- 归档 commit：`8609ecf4338e29f6305facdbe3ce12352db78c56`
- README 原始路径更新 commit：`52ec037de8111e5dabbe2b9e3ddb791a619399a6`；已回读线上核验。
- 上游：`nvidia/Nemotron-RL-Math-v2`
- 上游 revision：`804418c1d4eceeaa453d895954887c0975e79121`
- 原始数据字节数：6887923；远端文件大小校验通过。
- 保留原始数据、README、许可证元数据和 `_provenance/manifest.json` 中的 SHA256。

### gump2049/xDAN-9B-Agent-RL-OpenThoughts-5K

- 入口：https://huggingface.co/datasets/gump2049/xDAN-9B-Agent-RL-OpenThoughts-5K
- 归档 commit：`4c15015b8ce32a1978066a432fcdf5733eae5e05`
- README 原始路径更新 commit：`07e7ec07aac1eda7490243820ff1470c7d00cef6`；已回读线上核验。
- 上游：`open-thoughts/OpenThoughts-Agent-RL-5K`
- 上游 revision：`409012538183a68a19c5432f88ba0791a824c657`
- 原始数据字节数：12393991；远端文件大小校验通过。
- 保留原始数据、README、许可证元数据和 `_provenance/manifest.json` 中的 SHA256。

### gump2049/xDAN-9B-MOPD-Math-Code-IF-Science-v1

- 入口：https://huggingface.co/datasets/gump2049/xDAN-9B-MOPD-Math-Code-IF-Science-v1
- 归档 commit：`b36859f4c5bd0873271d1d0a7a2a5f302cbfb2d0`
- README 原始路径更新 commit：`3eedbc48f8264dde657d59c15ae0385ac28ed002`；已回读线上核验。
- 上游：`icemoon28/MOPD-Training-Data`
- 上游 revision：`96e88d579cb1ee68c9183c52e5d133f58cf370bf`
- 原始文件共 1705777701 字节；四个 Parquet 上游与归档 SHA256 一致，远端大小校验通过。
- 数学、代码、指令遵循、科学四域，保持原始子目录与数据格式。

## 验证记录

- 三个仓库均为私有，只有登录有权限的账号才能访问。
- Math JSONL 已独立回读比对 SHA256；Agent Parquet 与 MOPD 四个 Parquet 均校验远端 LFS SHA256。
- 机器可读入口：`hf-data-archives.json`，记录源与目标的固定 commit。每个 HF 仓库保留 `_provenance/manifest.json`。
- MOPD 下载曾中断；HTTP 续传完成后使用 Xet 上传成功，最终以内容哈希判定完成。

## 训练准入边界

- 状态统一为 `archived_unvalidated`，不是训练就绪。
- Nemotron：检查并恢复来源占位符。
- OpenThoughts Agent：验证任务环境、Modal 适配及 verifier。
- MOPD：第三方四域合集；核对各子集来源与许可证，不视为官方 MiMo 数据。
- 使用前完成去重、评测污染审计、数据分布与预算检查、固定验证集隔离。保留数据源身份；多教师路由单独配置，不能仅由别名推断。
