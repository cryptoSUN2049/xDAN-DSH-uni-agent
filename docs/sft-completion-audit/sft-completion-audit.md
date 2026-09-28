# SFT 完成与观测验收

核查日期：2026-09-28。当前结论：20K 正式 SFT 完成；全链路观测目标仍未全部完成。

**范围纠偏：本次20K实际全部标为code，不是原规划的多领域混合。** 15,589条来自greghavens/gpt-5.6-sol-coding-and-debugging-traces，4,411条来自saidutta69/Qwen3.8-Agent-Premium；256条验证全部来自前者。数量是行数，不是独立任务数。详见data-scope-audit.json。

发布manifest明确记录first 20000 rows；W&B无显式data.shuffle/seed，适配器默认shuffle=False。当前train/val的record_id和非空task_group_id交集为0，但尚不证明内容无近重复。已有loss结果只能支持当前编程分布上的拟合改进。

当前完整训练分片59,164行：code 42,914、reasoning 12,496、general 3,754；教师标签GPT5.6 31,178、Qwen3.8 27,986，未见Fable标签。完整验证2,866行：code 2,031、reasoning 625、general 210。说明从完整分片取前N行确实漏掉现有reasoning/general数据；办公、数据处理、翻译、写作没有独立标签，不能直接声称这些领域为零，也不能声称已经满足配比。

源码一致性补充：当前远端src/uni-agent/examples与本地的verl_sft_dataset.py SHA256均为db2e2061c2a1e80e2a92223de31ed05ed4e0ed1c16079ef103def46ea74bfb4e；verl_sft_mask.py均为16b2f5d8ea7c497442a8dc36661b76d07ed7930d0c126dd34de269a66c42427e。远端VERL HEAD为a9f2985159536a607211dcac730d3f5d55028950；uni-agent目录不是Git仓库，仍需文件级快照，不能只用editable包版本复现。

## 已核实的训练

远端根目录 `/workspace/verl-uni-agent-harbor-opd-rl`。
运行 `runs/performance-9b-sft/verl-sft-cu128-64k-20k-fsdp2-20260925T0756Z`。

- `exit-code=0`，原始 metrics.jsonl 已下载并核对 SHA256。
- 训练 step 连续覆盖 1–10000，没有重复或缺失；数值指标均有限，零梯度步骤为 0。
- command.sh：Qwen3.5-9B、LoRA rank/alpha 16、双卡 FSDP、bf16、FlashAttention2、max_length 65536；train_max_samples=20000、global batch=2、micro batch=1、num_workers=0、lr=1e-5。
- 使用 `train.parquet` 和 `validation.parquet`，验证限制 256 条。64K 是长度上限，不代表每条样本均为 64K。
- 每 500 步验证/保存；共 20 个验证点。step500 loss 0.513278，step5000 0.418413，step10000 0.412975。
- 最后累计 global tokens 0.277837344B。MFU 全部为 0：该字段不能用于判断实际算力效率。

## 合并模型的独立加载验证

产物 `runs/performance-9b-eval/sft-final-step10000/merged-model`。
原始验证报告 `validation/summary.json` 时间为 2026-09-26T04:25:21Z。

| 项目 | 原版 9B | SFT 最终模型 |
|---|---:|---:|
| 请求/完成样本 | 256/256 | 256/256 |
| 每样本 loss 的均值 | 1.0536412201 | 0.4570854658 |

这是固定验证数据上的监督 loss 比较，不是生成任务准确率；与训练器 val/loss 聚合口径不同，不能直接混用，也不能据此宣布全面能力提升。

## 观测验收

| 要求 | 证据 | 状态 |
|---|---|---|
| 训练日志和连续曲线 | train.log、完整 metrics.jsonl | 已核实 |
| GPU/系统监控 | gpu-metrics.csv 541441 字节、vmstat.log 存在 | 存在；采样覆盖率待验 |
| W&B | API返回 finished；10000步、90020个指标值与本地一致 | 云端逐步对账通过；无缺失、不匹配或重复step |
| rl-insight | 正式命令 logger 只有 console,file,wandb | 未接入本次正式 run |
| 历史运行 trace | 未取得实际 backend trace | 不得声称已采集 |
| 环境版本一致性 | 156个固定版本与当前安装包全部相同 | 已对账；editable源码、完整冷重建仍待验 |

W&B 入口：https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/cxo04d3j

pilot 曾启用 rl_insight，但因为 Ray 未初始化而禁用 monitoring。正式 run 直接未启用该 logger。不得以服务安装或进程存活替代接入验收；历史 scalar 可以明确标为回放，但无法补造不存在的运行期 trace。

## 后续验收清单

- [x] W&B 云端 run 状态与本地 10000 步全部指标对账；回执 `sft-completion-evidence/wandb-cloud-audit.json`。
- [x] W&B显式命令参数逐项核查一致；engine=fsdp为Hydra配置组，云端展开为FSDPEngineConfig；列表、数值与布尔按类型比较。
- [x] 已保存freeze的156个固定版本与实际环境一致；回执 environment-audit.json。
- [ ] 补安装脚本严格约束和独立冷重建验证；editable源码不能仅凭版本认定一致。
- [ ] 为 torchrun SFT 明确可用的 rl-insight scalar 接入路径，用独立有界运行验证后端可查询；不得干扰当前评测。
- [x] 核验实际采样规则、领域计数和当前ID级隔离：训练/验证都为code。
- [x] 共享盘源train/validation和发布20K/100快照四文件SHA256均匹配manifest；全列比较源前20000/100行与快照相同，回执data-snapshot-audit.json。
- [x] 将实际使用的256条验证另存共享盘 `releases/sft-run-cxo04d3j-validation256/validation-256.parquet`，回读与源前256行相同；SHA256 c88d841b2f38639036e64e5e4b11d5ddcf877c71c95d94ffd0a41995c269d637，3078774字节。清单validation256-manifest.json；尚未发布HF。
- [ ] 完整语义去重与未来多领域配比。
- [ ] 完成三模型生成能力对照；loss 下降不代替 benchmark 结果。

原始证据放在 `sft-completion-evidence/`；metrics-audit.json 为本地从原始曲线生成的核查摘要。当前不能标记整个 goal complete。

2026-09-28 CPU回归复验：`uv run --no-project --with pytest python -m pytest --noconftest -q tests/uni_agent/examples/test_performance_9b_verl_sft_mask.py tests/uni_agent/examples/test_performance_9b_verl_sft_export.py`，5 passed in 0.16s。使用临时uv环境，不修改现有训练venv；范围只覆盖现有mask与导出单测，不代表全量tokenizer或真实GPU验收。

## rl-insight 源码定位（当前服务器安装版本）

位于运行 venv 的 `lib/python3.12/site-packages/rl_insight/`：

- `client/__init__.py` 只注册内置 `MonitorBackend.RAY`。
- `client/ray_monitor_client.py:create_ray_monitor_client` 在 `ray.is_initialized()==False` 时记录警告并返回 None。
- `api.py:init` 以 `client is not None` 决定 enabled；配置logger和server URL不能绕过该条件。
- `MonitorRayClient.apply_event` 为异步提交，不回传Hub错误；验收必须查询实际Prometheus后端，不能只检查调用没报错。
- 11403 上 Prometheus/Grafana/Tempo/http_api 进程仍在运行；这只证明服务存活，不证明该SFT run已接入。

后续方案应保持torchrun训练方式，独立解决监控传输；不为安装观测重跑20K训练。历史曲线回放须标明 replay，不能制造历史trace。

2026-09-28 03:29 UTC实际后端检查：Prometheus /-/ready、Grafana /api/health、Tempo /ready均200；rl-insight /healthz返回status=ok。但Prometheus /api/v1/targets的activeTargets为空。回执insight-health-audit.json证明服务健康，不证明SFT接入；不需要仅因无数据就重装服务。

## 已批准修复实施（2026-09-28）

- 用户明确“继续”后实施CPU sidecar、launcher就绪门禁和独立退出码；默认不开启，使用SFT_INSIGHT_ENABLE=1及RL_INSIGHT_SERVER_URL开启。
- 46项相关测试通过；sidecar单独31测试，覆盖189/197=96%。
- 原生API与正式sidecar两条CPU传输路径都已在11403真实运行；Prometheus range query包含train_loss=0.75、0.5，并读到val_loss=0.4。正式sidecar处理2记录，Hub接收7事件，终态forwarding_complete，进程退出。此为合成数据传输验收，非SFT模型表现或历史回放。
- 原观测服务复用，不改训练器。runtime/build约束已部署到独立代码快照，新venv正在冷重建，当前进入FlashAttention源码构建。
- 已部署nohup空卡验收队列：等待环境重建exit0、GPU连续30秒低于512MiB且利用率<5%，才运行2条训练/2条验证、一步、4K、单卡的真实SFT。最多等24小时。尚未计为GPU验收完成。
- 不抢占现有双卡评测和单卡其他项目服务；实际GPU小样、冷重建终态和后端真实训练指标仍待核验。

冷重建最终结果：exit0，160包pip check通过，157项固定版本/来源验证通过，Torch2.8.0+cu128及扩展导入成功。MIN_GPU_COUNT=0，本项不包含CUDA forward；真实SFT小样仍排队。回执environment-rebuild-result.json。
