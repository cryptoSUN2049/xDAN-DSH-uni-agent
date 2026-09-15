# P0 云端训练与独立验证报告

2026-09-15。Student **Qwen/Qwen3.5-9B**，Teacher **Qwen/Qwen3.8-27B**。

**工程结果：一批真实 OPD 更新、同源 LoRA 参数变化、独立加载与任务运行均已验证。能力结果：训练前两题 2/2，训练后 1/2；没有能力提升证据。本批 RL advantage 为零，尚不能称为已验证有效的 OPD＋RL 联合学习。**

机器摘要：[p0-closed-loop-evidence.json](p0-closed-loop-evidence.json)。完整原始文件保存在实现 worktree 的 ignored `outputs/` 和 Modal Volume，摘要附原始文件 SHA256，未修改历史关卡报告。

## 逐环节验收

| 环节 | 真实证据 | 结论 |
|---|---|---|
| 本地集成 | 286 项相关回归；10 个新增核心模块综合覆盖率 90.67%（含分支） | 通过；不是整个 Cookbook 全套测试通过 |
| 最终 Linux 镜像 | 实际 ml_log 初始化、config/metrics/code.diff 写读及关闭；git/bash、完整导入、Plotly HTML、依赖和任务树 hash | 通过；在付费模型预检之前执行 |
| 云内沙箱 audit | csv-paid-totals：nop=0、oracle=1；同资源契约，2 个 sandbox 已清理 | 通过；原有四题共 8 次 audit 另作历史证据 |
| 训练原始 token | 6 个 datum / Teacher 评分记录，1,179 个 action token，3,595 个屏蔽位置 | 原始上下文、target shift、评分、mask 与 advantage 公式逐条核对通过 |
| 实际训练回执 | 同一模型的 forward_backward 与 optim_step 各一次，完成回执有效；loss:sum=181.8892098665 | 有限 loss、优化器确实执行 |
| 保存与来源链 | 同一 client：initial(batch0) → 000001(batch1) → final(batch1)，state/sampler 分开保存 | 通过 |
| 非零 LoRA 变化 | SDK 官方下载 initial/final adapter；498 个同形同类型张量，249 个发生变化，53,520,850 个 LoRA 元素改变 | 通过；max abs diff=0.0001000000193，L2 diff=0.6847330752 |
| 独立 reload | 新 Modal 容器中新进程加载 final sampler；核对 9B、qwen3_5、sampler URI hash 与任务文件 hash | 工程通过；任务实际仅 1/2 成功 |
| 生命周期和落盘 | 训练及训练前评估 4 个 sandbox、独立验证 2 个、audit 2 个，全部记录 cleanup；训练和 reload session 已关闭 | 通过；periodic commit failures=0 |

训练器继续复用官方 Cookbook 的 importance_sampling 更新、CheckpointManager、TrainingRunStore、logtree、CaptureExporter 和评估组件。新增层负责组合、原始评分审计、资源契约及独立验收，不用自建 Teacher 推理 GPU。

测试范围之外，扩大检查曾发现上游旧 rollout 日志测试引用已移除接口。已记录该失败；当前新路径使用官方 serialize + Store。不能把 286 项相关测试报告为上游全套测试全绿。

## 本次实际学习信号

- 运行配置为 hybrid，β=1，learning_rate=1e-4，LoRA rank=32，temperature=1，max_steps=1，group_size=2，groups_per_batch=1。
- 训练只消费 `csv-paid-totals` 的两条 Student 轨迹；manifest 中另一个训练题本次未用于更新。
- 两条轨迹的奖励均为 1，组内奖励方差为 0，所以 RL advantage 全零。
- OPD 在 1,138 个动作位置产生非零 advantage；Teacher sampled reverse-KL 均值为 0.1576476395。环境位置 advantage 保持为零。
- 实际验证的是 Student 序列上的 sampled reverse-KL 信号及其更新路径。不是全词表精确 KL，也没有验证 top-k 分布 GKD；此路径不要求 Teacher top-k。
- 导出的 adapter 数值证实发生更新；并未下载或直接审计 9B base 全部张量，不能用此报告证明所有 base 权重不可变。

## 独立 reload 与任务结果

| 原创验证任务 | 训练前 | 独立 reload 后 | 后评估 action tokens | 终止原因 |
|---|---:|---:|---:|---|
| tree-sha256-manifest | 成功 | 成功 | 631 | max_turns（3轮） |
| repair-service-config | 成功 | 失败 | 458 | max_turns（3轮） |

训练前评估共 1,315 个 action token；独立后评估共 1,089 个。两阶段均为每题一次尝试，任务字节 hash 相同，单次最多 4,096 生成 token、3 轮交互。有效执行、grader 返回有效奖励、资源清理均通过；`passed=true` 表示工程验收，不等于 `task_solved=true`。

2/2 → 1/2 是观测结果，不能用两道题的一次随机采样判定训练导致退化。也不能忽略失败，只以 loss 或参数变化宣告模型变强。最终 failure 分析见下方补充或项目交接；当前不追加训练来“覆盖”失败。

## 失败轨迹的独立复核

`repair-service-config` 第二轮直接重写配置文件，遗漏要求保留的 `server.timeout=45` 和 `logging.path=/var/log/service.log`。该次写入工具返回 exit 0，第三轮只读取文件，随后达到 3 轮上限。遗漏字段足以解释任务失败；strict grader 返回有效 0 分且没有 `grading_error`。原始报告未保留 grader stdout/stderr、reward 文件原文及最后一次工具输出，因此不声称看到了具体断言日志。

训练前 capture 的实际 SamplingParams 为 temperature=1、top_p=1、top_k=-1、seed=None、max_tokens=4096。reload 代码走同一 evaluator 默认 temperature=1，但 JSON 未保存实际 SamplingParams；前评估两个任务并发，后评估顺序执行。任务和 runner hash 相同，仍不足以把两次成绩差异归因为参数更新。

独立审查还从原始 token 重算了 OPD：最大 advantage 公式误差为 2.384185791e-7，重算 KL 均值 0.157647629509（float32 汇总差）；1,138 个非零动作与训练记录一致。覆盖率细分为语句 93.13%、分支 83.23%，两者综合 90.67%。

## 云端来源与产物

| 项目 | 标识 |
|---|---|
| 训练 run | `hybrid-p0-20260915-02` |
| 运行源码 | `b06728a`（后续文档提交不改变云端运行代码） |
| 最终 Modal image | `im-3GvBhwyn7mJ2AuXtElFPPV` |
| Audit call | `fc-01M2J17D3NQ2NH3QNSENTZVS9P` |
| Train call | `fc-01M2J1EEA3QRHT0YPFACQYWP7H` |
| Verify call | `fc-01M2J1ZVVKBT9PATF66CPVFEFB` |
| Modal App / Volume | `tinker-harbor-opd-controller` / `tinker-harbor-runs` |
| SDK | Tinker 0.29.0、Modal 1.5.5；云 Python 3.12.10、Torch 2.14.0+cpu |

```text
tinker://971c8454-6952-53f2-bf5b-17afa5cf046d:train:0/sampler_weights/initial
tinker://971c8454-6952-53f2-bf5b-17afa5cf046d:train:0/sampler_weights/final
tinker://971c8454-6952-53f2-bf5b-17afa5cf046d:train:0/weights/final
```

```text
# 实现 worktree 本地文件
outputs/p0-integrated-gates/            # 本地关卡、提交和云返回回执
outputs/p0-trained-cloud-run/hybrid-p0-20260915-02/
  bootstrap/bootstrap.json
  status.json / trainer.log
  training/
    config.json / metrics.jsonl / checkpoints.jsonl
    capture_status.json / capture/{sample,train_op}.jsonl
    service-lifecycle.json / resources.jsonl
    timing_spans.jsonl / trace_events.jsonl
    iteration_000000/                  # 原始datums/scoring、轨迹、HTML、Gantt、评估
outputs/p0-verification-cloud-run/      # 原始5份验证报告
```

Volume 以 run ID 为目录，独立验证位于该目录的 `checks/`，包含官方下载的 adapters。不要重复提交已完成 run，也不要删除 App/Volume 作为任务清理。原训练 `status.json` 仅记录 `training_saved`；最终参数/reload 结论来自后续 `checks/verification-status.json`。历史文件不回填成“全部成功”。

训练前 typed eval 的 `time_seconds=0` 不能当作真实耗时；该报告 `num_truncated=0`，同时轨迹记录 `max_turns`，二者口径需要明确。后续以原始轨迹/阶段 timing 为依据补齐，不能把这些默认汇总值当完整遥测验收。

## 边界与下一步

实施规格：[下一里程碑的接口与验收设计](next-milestone.md)。

1. 本次 service-config 失败轨迹已检查，保留失败。下一步补齐 grader 输出与终态动作后的观测证据，再做新的对照。
2. 建立更有区分度的开发任务，测 Student 与 Teacher 基线和组内奖励分布。Teacher 也失败的题不能仅靠蒸馏期待解决；同组全成功/全失败无法验收非零 RL。
3. 锁定官方 Terminal-Bench 单任务及 harness 版本，独立 sandbox 重复运行；该任务此后属于开发数据，不可再当最终盲测。
4. 验证 state+optimizer 恢复；当前独立 sampler reload 不代表断点续训。长上下文和更多工具模板的数值对齐仍需验证。
5. 完成上述证据后接最小 Control Panel：只读查看阶段、失败、轨迹、checkpoint 和实际成绩，再接有边界的提交/取消；扩规模前补实验锁、预算预留和恢复协议。
6. 最终按同起点、同任务/工具/预算做 baseline、OPD、RL、hybrid 消融，再做未参与调参的 Terminal-Bench/Opus 对照。

本次训练与验证均已完成，不自动追加付费实验。用户充值 10 美元不是实时余额或美元硬上限，Modal 费用另计；本报告未声称已核对最终账单。当前轻量 Cookbook Harbor harness、存储配额/超时覆盖策略、后台进程与 grader 的权限边界都必须在官方任务准入时继续检查。
