# Context v2：独立 checkpoint reload 已验收

2026-09-09，run `/root/runs/context-v2-train-r1-reload`，415.009秒exit0。实际运行源码仍为 `a9c7b0a155da9b8d29da3d4d46a7c337156a54f3`，VERL `fefb080262e1c015a0ea05f958822a6a512dc795`；该事实来自已完成run清单，不以当前正在运行memory的checkout覆盖历史。

## 加载与无更新证据

原始 `train.log` 的行号和原文已保存在 `context-v2-train-r1-reload-result.json`，日志自身有SHA256：

- 1098行：从母run `global_step_2` 恢复，global step设为2。
- 1103行：实际Loaded model，指向该step的 `actor/model_world_size_1_rank_0.pt`。
- 1104行：实际Loaded optimizer，指向该step的 `actor/optim_world_size_1_rank_0.pt`。
- 1107/1108行：从 `extra_state_world_size_1_rank_0.pt` 恢复RNG和lr_scheduler。

启动命令为 `RESUME_MODE=resume_path`、`VAL_ONLY=True`。实际metrics只有step2的一条验证记录，没有actor update/pg_loss/grad_norm项；rollouts目录没有train消费JSONL；新reload checkpoint目录没有产物。因此这是从真实checkpoint启动的独立评估，没有新增训练更新。日志证明框架实际执行加载，未额外宣称逐张量内存快照与磁盘逐字节比较。

## 四个fresh结果与消费

原生 `reload-audit.json`：eligible=true，4/4组全部 `eligible-and-consumed`，每组n=1、partition=val、global_steps=2；0拒绝、0遗漏、0意外消费。四份回执各自fresh/eligible/finished均true；trace、artifact、receipt、token/TQ身份严格核验通过。

| task | reward | 严格准确率 |
| --- | ---: | ---: |
| dev-C | 0.1 | 0 |
| dev-D | 0.1 | 0 |
| dev-M | 0.1 | 0 |
| dev-V | 0.6675 | 0 |

回执均值 **0.241875**；训练过程中同四个dev均值为0.255，严格准确率一直是0。本次dev-V仍回答正确值8，但只给1/20条必要引用，引用部分分低于此前4/20。这说明重新运行产生了不同结果，不能表述为精确数值复现或效果提升。

独立核对四题原始contract与source字节：母训练准备目录和reload准备目录全部相同。运行路径、会话和采样执行是新建的，未要求逐字节prompt/执行调度一致；恢复RNG也不足以宣称整条分布式Agent过程确定性重放。

## 当前可认可的结论

本轮已完成：真实同题n4 online采样→有非零任务奖励梯度的第一步→checkpoint保存→CPU消费/参数/optimizer审计→独立恢复model/optimizer/extra→四题fresh评估与消费验收。

这证明工程训练闭环成立。仅两条不同train题被消费；第二步零advantage下的参数变化已有精确动量诊断，不能多算一个有效任务学习步骤。开发集严格准确率为0，仍没有能力提升或泛化证据，也没有因此完成跨会话记忆、真正多context或RSI训练。

## 交付与持久化

- `context-v2-train-r1-reload-result.json`：完整reload审计、run清单、四回执身份、加载日志、无更新检查、指标和题目等同性。
- `context-v2-train-r1-reload-archive.json`：训练＋reload日志、准备数据、CPU审计及原始metrics的云盘归档地址与SHA256。
- 归档位于 `/workspace/reports/context-v2-train-r1-reload-20260909.tar.gz`，校验gzip完整性；母checkpoint仍在 `/workspace/uni-agent-g1/checkpoint/context-v2-train-r1/`，不重复打包9GB权重文件。

本次核验均为只读CPU；只有明确授权的云盘归档写入，不修改源代码、旧训练证据或当前memory GPU作业。下一能力主线是已启动的新memory writer，通过后再freeze并开启新B会话检索。
