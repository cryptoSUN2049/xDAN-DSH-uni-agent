# S2 checkpoint 全量评测设计

状态：2026-09-20 12:40 UTC，清点与只读诊断完成；实现待设计批准，未启动批量评测。

## 目标与范围

按相同 eval-set-v1 78 题 × 4 次评估本轮所有仍保留且可加载的 S2 checkpoint，并加入 S1 step12 和原版作对照。默认不扩展到 r1–r11 历史实验；范围问题已发给用户。

| 版本 | 候选步数 | 状态 |
|---|---|---|
| 原版 Qwen3.5-9B | base | 现有 78 题/312 样本完整基线，mean@4=0.6410256410；复用前核实任务与配置身份 |
| S1 联合 OPD+RL | 12 | checkpoint 与 pinned 是同 inode，只评一次 |
| S2 纯 OPD | 10, 11, 12 | 三个模型文件存在 |
| S2 后续纯 RL | 20, 40, 58, 59, 60 | 20/40 永久保留，60 两路径同 inode；58 文件异常偏小，完整性待检 |

S1 另有 3–11 步文件，不默认加入本轮 S2 曲线。记录轮转删除步数与损坏版本，不能将其当作 0 分，也不能宣称全部 60 步均有结果。

RL step58 模型文件 14,294,188,032 字节，其余候选 19,026,026,647 字节。文件大小异常仅为诊断线索，不直接判定损坏。必须检查 archive 与实际加载。

## 架构

```mermaid
flowchart LR
  A[保留 checkpoint 清单与身份] --> B[完整性检查]
  B --> C[训练收尾完成 / GPU 预约与实际占用检查]
  C --> D[单版本加载验证]
  D --> E[78题 x 4 全量评测]
  E --> F[检查进程结果与逐题样本完整性]
  F --> G[原版配对与行为统计]
  G --> H[全版本汇总表和曲线]
  F --> I[缺失或失败清单 / 有界重试]
```

## 启动故障的已知事实

- step20 快检在 vLLM 初始化时可用 46.63 GiB，小于 0.6 × 94.97=56.98 GiB，0 题完成。
- 相同 vLLM 配置在原版与 OPD step12 成功；成功运行 FSDP 前占用 0.67 GiB、后 27.51 GiB；失败运行分别 15.05 与 41.89 GiB，多出约 14.38 GiB。
- 失败时还未加载 checkpoint，不能说 step20 checkpoint 导致显存不足。需核查物理 GPU UUID、CUDA/Ray 映射与外部进程；不盲目修改生成参数或合并 bf16 LoRA。
- 只读路由审查：入口明确 CUDA_VISIBLE_DEVICES=1；独立 Ray session；vLLM 从 FSDP worker 的 Ray accelerator ID 取得设备后设置 CUDA_VISIBLE_DEVICES，未发现静态映射错误。历史缺少 UUID/PID 快照，额外占用来源仍未知。
- 启动探针候选（待验证）：空卡上采用 GPU_MEMORY_UTILIZATION=0.4、ROLLOUT_MAX_NUM_BATCHED_TOKENS=8192、CKPT_LOAD_CONTENTS=model，仅1题1次验证加载和首条产出；探针不计全量结果。参数只控制显存/执行批次，不改变任务预算或采样定义；与基线是否可比较仍须在真实运行核对。
- eval_val_only.sh 使用 `|| true` 吞掉失败，空汇总退出 0；批量执行前必须修复失败传播和完整性判定。
- 现有训练收尾执行全局 Ray 清理。新批量评测必须等训练收尾完成，避免跨越清理阶段。

## 文件改动范围（拟实施）

1. `examples/harbor_opd_rl/eval_val_only.sh`：保留底层退出状态；保存失败证据；空结果或不足题数/样本数不得报告完整成功；GPU 路由诊断；如需配置调整，必须经实测验证。
2. `examples/harbor_opd_rl/eval_checkpoint_matrix.py`（新增）：清单校验、逐版本脱机执行、GPU 占用检查、有界故障处理、状态更新和汇总；复用原评测与配对/行为统计入口。
3. `tests/uni_agent/examples/test_harbor_eval_matrix.py`（新增）：失败传播、缺失样本、重复 pinned、有效已有结果复用、断点恢复与不覆盖证据。
4. `docs/performance-9b/checkpoint-full-eval/`：manifest、来源、每版本结果与最终报告。
5. `tasks/verl-uni-agent-harbor-opd-rl/handoff.md`：按用户当前目录约定记录本任务运行入口。

## 接口与统计合同

- Manifest：run_id、训练 run 路径、checkpoint 路径、step、模型/数据/任务配置哈希、n=4、GPU UUID、输出目录。
- 同一训练版本多路径（pinned/滚动副本）去重；不同版本不得仅凭文件大小去重。
- 结果状态：pending / running / complete / incomplete / failed / unavailable；complete 要求 checkpoint 加载成功、78 个指定任务各 4 条有效结果、进程成功，不只检查 exit=0。
- 每次尝试新输出目录；不覆盖失败现场；不修改正在使用的 checkpoint。
- 主表：mean@4、相对原版差值、按任务 paired bootstrap 95% 区间、SWE/TL 分项、输出 token 中位数、超时、跑满轮数、缺失数、时长与费用。
- 超时与基础设施缺失分开。只有共同完成子集的结果标记 partial，不伪装完整评测。
- 多版本筛选的最优点视作探索性结果，逐点 95% 区间不是多重比较校正后的结论；最终 step60 与原版是预先指定的主要对照。
- 原版 78×4 全量与旧 58×2 快检分开保存；最终曲线所有点采用统一全量口径。

## 资源与执行顺序

- 2026-09-20 12:37 UTC：Modal metered $740.88，billed $794.23；已记录上限 $900，但 CLI 本次未验证实际上限字段。费用额度与 Tinker 共用。
- 9 个候选新版本最多 2,808 条轨迹；若 step58 确認损坏，8 个可执行版本为 2,496 条。每条 $0.023–0.05 的历史粗估对应约 $57–140 沙箱费用，未计 RunPod GPU 和重试，不是承诺上限。
- 历史单版本耗时约 1.5–3 小时，粗估 8–9 个版本单卡 12–27 小时；双卡在资源/环境隔离验证和排期允许后可并行缩短，不承诺线性加速。
- 优先顺序：S2 RL60 → OPD12 → RL20 → RL40 → OPD10/11 → RL59/58 → S1 step12。不减少用户要求的完整版本范围，只先得到关键对照。
- 先解决加载与完成判定，运行一项并验证实际产出，再启动其余队列。不得自动扩大 Modal 上限、启动新 Pod 或杀其他会话的进程。

## 验证计划

- 单测模拟底层失败、空汇总、77/78 题、每题不足4条、路径重复、缺失checkpoint、继续执行时证据覆盖风险。
- shell 语法检查与 Python 编译；相关回归通过。
- 真实 GPU：记录 UUID/进程占用，加载 checkpoint，验证首条真实结果与独立 GPU0/1 映射，再验证一项全量完整性。
- 全部汇总逐项核对 manifest 与每任务样本，失败/不可用版本不静默排除。
- 每次 push 前执行 `ruff check .` 和 `ruff format --check .`。

## 尚未完成

- GPU 映射与额外显存占用根因。
- step58 文件完整性检查（第一次 SSH 检查连接中断，未得结论）。
- 批量评测实现、首次成功启动、所有版本结果与总报告。

## 2026-09-21 补缺策略修正（用户继续推进授权内）

已出现两次311/312但整套重跑仍缺1条的情况。仅重跑基础设施缺失，不重跑模型已有效判0的样本；保留原attempt，按validation.json的完整task id筛选原parquet和缺失n。以补充样本加原有效样本生成新aggregate，再用原78题×4完整校验；记录原始infra事件和合并provenance。GPU1补缺，GPU0原队列继续，既有manifest和运行现场不覆盖。future matrix重试改成补缺，0样本/异常退出仍停队列。

基础设施条件重采可能有选择偏差，报告同时给缺失当失败的原始分数与补齐分数，不能只报更高者。不同attempt不得按得分选择：固定用已有attempt2及其未判分缺口。
