# WS07 短课程 r2 重复实验结果

**工程重复执行及独立 reload 通过；有效参数更新没有复现。** 未修改课程、准入或奖励，零更新报告保留失败。

执行与审计源码：`f419bbb3d72fd49abc0b37cea94fde699d1c03ac`，checkout `/workspace/rebuild/uni-agent-rsi-compare-f419bbb`，沿用既有 cf2d3f5 Python 环境、DSH 0.1.3a2 和固定 VERL overlay。

## 真实训练

- `ws-short-train-r2`：supervisor PID328949，exit0，1500.03秒，8/8步。原启动PID328842，没有重复启动。
- after_run检查通过。8组、64条唯一A/B实际消费通过，无未知、重复或重叠消费。
- **7个独立task ID**：s101、102、103、104、106、107、108。s102重复消费，s105未消费；两步各出现一次evicted sample，不计作新增任务。
- **32条终态B全部reward1**；每组n4为[1,1,1,1]，8步优势与梯度均0。A0/B1不构成sibling奖励方差。
- step4→8：504 adapter变化0、399 base变化0，模型文件SHA完全相同：`3af8e4f40844e5215d37a1ce9f6f2de5d018a1c8db0bab75212d40604471808f`。
- optimizer step8→16；504 active states、1008 moments均finite且全0。保留原审计passed=false（All optimizer moments are zero），步数推进不证明学习。
- 原始审计目录：`/root/runs/ws-short-train-r2/repeat-audit-r1/`。

## 串行独立 reload

| 运行 | 终态 | 消费 | 任务结果 |
|---|---|---|---|
| ws-short-r2-reload-901-r1 | exit0，420.009s | 1组2唯一A/B，passed | B reward1 |
| ws-short-r2-reload-902-r1 | exit0，390.010s | 1组2唯一A/B，passed | B reward1 |

两次均实际加载母step8 model/optimizer/RNG/scheduler，新session，receipt fresh/eligible/finished=true，after_run母checkpoint核验通过，采样版本8。最终GPU0%/0MiB，没有启动后续GPU任务。

## 云盘归档

- 路径：`/workspace/reports/ws-short-r2-engineering-evidence-20260909.tar.gz`
- SHA256：`15e23af2bb646d3b7c3efc456131b4d9c21a6ccfc50eeba7671cb6dc5dd46cee`
- 15,300,169 bytes，145,945源文件，所有成员SHA/size读回通过。
- Manifest：`/workspace/reports/ws-short-r2-engineering-evidence-20260909.manifest.json`
- Manifest SHA256：`54c6fc87e3b69cf41d684fe8df9c8fcb43857573532c8da43711161d71992de2`
- 包含三run/data、launch.log、两reload launch.json、三个metrics与审计。母训练无独立launch.json，以实际run-manifest/command/launch.log为证，没有补造。
- 排除3个training.env（不读取）、checkpoint大文件及源码。归档/清单0600，原文件不变。
- Checkpoint独立保留：`/workspace/uni-agent-g1/checkpoint/ws-short-train-r2/`。

## 结论边界

同一链路再次完成训练运行、保存、独立恢复和实际任务执行；短课程本次满分饱和，无法提供GRPO学习信号。r1有效更新证据仍成立，但不能推出每次重复都会更新。后续应冻结稍难且有真实奖励差异的新课程，不在当前记录上改分，也不将重复采样算作独立任务。
