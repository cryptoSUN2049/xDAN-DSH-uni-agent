# M1 本地checkpoint空间只读审计

2026-09-08，未删除文件、未修改源码、未操作GPU。

远端/root overlay总32,212,254,720B，可用31,547,322,368B（约29.38GiB）。/workspace为云文件系统，df显示的全局空间不能证明本账号quota足够；本审计不把该数值当写入保证。

旧完整目录 `/workspace/runs/dsh-redact-m1-r1-checkpoints/global_step_{1,2}` 各9,033,733,447B（8.41GiB）。单份主要文件：model_world_size_1_rank_0.pt 8,889,735,011B；optim_world_size_1_rank_0.pt 132,552,363B；tokenizer.json 11,422,650B；extra_state 15,141B；data.pt1499B。FSDP_version=1/world_size=1，LoRA r16/alpha16。

两完整checkpoint合计18,067,466,894B，按当前/root available仍余13,479,855,474B（12.55GiB）。因此当前本地空间足够两完整checkpoint，推荐保持原生保存布局；仍应在启动前复核空间，不额外复制基座/venv至本地盘。此结论基于实测大小，不保证其他并行写入无影响。

同rank已存在SFT导出adapter_model.safetensors为66,127,744B。最小可搬运复建材料估计约210MB：adapter（含config）+optimizer132.6MB+tokenizer11.4MB+extra_state/data.pt/fsdp/lora metadata+精确base模型revision/hash、代码/runtime/task/verifierhash、训练配置、batch消费与数值审计证据。该包可用于冻结基座+adapter的warmstart与证据保留，**不是现有native FSDP resume原样支持的替代格式**：后者仍读取完整model文件；optimizer映射/基座还原的精确续训必须单独验证。

建议两完整checkpoint先保留到独立数值与reload验收通过，再决定归档最小材料；本轮不自动删旧文件或更改保存门。
