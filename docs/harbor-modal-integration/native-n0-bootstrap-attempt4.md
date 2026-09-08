# N0 旁路安装：attempt4 实录

2026-09-09 00:48:51—00:50:55 新加坡时间，124 秒内自然完成，exit=0。只做 CPU 依赖安装与隔离导入，没有 GPU smoke、模型生成或训练；不阻塞已验收环境中的能力主线。

- 专属 checkout：`/workspace/rebuild/uni-agent-native-n0-r1`，commit `80be2ec85e8db614b8b5cc9f6f4581fe990db9f0`；VERL 固定 `fefb080262e1c015a0ea05f958822a6a512dc795`。
- 专属新环境：`/workspace/venvs/uni-agent-native-n0-r1`；没有修改既有训练 venv。使用同 Pod 的 `/workspace/cache/uv`，准确称为缓存辅助复建。
- 已提交 `install-verl.sh` 执行 frozen sync 后，带 `--no-config --no-deps --require-hashes` 安装固定 NumPy overlay；实际联网下载 15.8 MiB wheel，日志明确卸载 2.4.6、安装 2.3.5。wheel hash 为 `0d8163f43acde9a73c2a33605353a4f1bc4798745a8b1d73183b28e5b435ae28`。
- 基础环境 `uv pip check`：255 包兼容；安装本地 DSH SDK/runtime `0.1.3a2` 后：257 包兼容。
- 安装前核实 SDK wheel SHA256 `6c6a1a8f26b9030326447a8ed41c3ae6261a6b78e7fe61d72c7bf3ae21f03d6e`，runtime wheel `59cc8ec59946afa572bfd0b9e6268d7380a4d00d1157d7dce6d2b2df86cf51ad`。
- 从 `/root` 执行 `env -u PYTHONPATH <新venv>/bin/python -I`：numpy、torch、verl、uni_agent、deepseek_harness、deepseek_harness_runtime 导入通过。Uni-Agent/VERL 的模块路径和 editable direct_url 均指向新 checkout；DSH 来自新 venv，runtime executable SHA256 为 `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。

完整版本与来源：[native-n0-bootstrap-attempt4-result.json](native-n0-bootstrap-attempt4-result.json)。远端原件位于 `/root/runs/native-n0-bootstrap-r1/install-attempt4.{log,exit-code}` 与 `install-attempt4-result.json`。

三份实录已归档至 `/workspace/reports/native-n0-bootstrap-attempt4.tar.gz`，SHA256 `967e1c184d4ad19bdb49d5008a50236dde8bc627691c63ae737eb905f36c6155`。历史失败 attempt1—3 保留。此结果不表示新环境训练、checkpoint/reload 或空主机复建已经通过。
