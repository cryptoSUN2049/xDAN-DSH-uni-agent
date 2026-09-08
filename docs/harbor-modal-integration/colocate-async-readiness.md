# 单卡 colocate_async 就绪核查

2026-09-08；只读源码核查，未启动 GPU、未修改训练代码。核查时本 worktree HEAD 为 `4b4fe731f5ba4700ac7a0a7a350deda6f4e3e288`，另有同步 Harbor 清理修复在工作区进行中。不能把未提交修复视为这个 SHA 的内容。M2 同步学生闭环尚失败，先修复、重跑同步证据，再进行独立异步对照。

## 固定身份与优先顺序

- Uni-Agent upstream：`89733ec81a69c3cc93ac90479de7ea7f01e51c1f`。
- VERL submodule：`fefb080262e1c015a0ea05f958822a6a512dc795`。
- DSH SDK/runtime：`0.1.3a2`；源码 `b2369692ea530007075ebcd18d39fdba0bbd3982`；runtime executable SHA256 `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- 模型：Qwen3-4B，revision `1cfa9a7208912126459214e8b04321603b3df60c`；LoRA rank/alpha 16/16。
- 开始前再锁定包含同步修复的本项目完整 commit；继承已验收同步 run 的完整 environment、数据/TaskRef/verifier/image hash。不要随异步试验升级以上组件。

执行顺序：同步 M2 修复与完整验收 → 配置透传测试 → 同任务/同预算单卡异步 smoke → 数值审计与独立 reload → 再测暂停恢复和吞吐。用户已授权机会合适时进行有界异步试验，不含新增 GPU/Modal 支出。

## 上游已经实现什么

`verl/verl/trainer/ppo/v1/trainer_colocate_async.py` 已注册 `colocate_async`。它使用 `FullyAsyncLLMServerClient`，预填 warmup 批次；采样后 abort 未完成生成、sleep 生成副本；更新后同步权重并 resume。单卡的生成和更新仍交替占用 GPU，不等同于独立训练/采样 GPU 同时满负载。

`FullyAsyncLLMServerClient.generate()` 在 abort 后续接已有 token，累计扣减同一次请求的 token 预算，记录 min/max policy global steps。`uni_agent/gateway/session/session.py` 汇总 generation version 到 trajectory。它处理模型生成暂停，不重新从头执行整个 DSH 工具任务；仍必须实测暂停期间工具副作用不重复。

`rollout.mode=async` 本身不是这个 trainer 开关。也不要进入旧 `experimental/fully_async_policy` 路径或照搬 MemAgent 的 4+4 GPU separate_async 拓扑。

## 最小配置与当前透传缺口

现有基础脚本已固定 `trainer.use_v1=True`、`transfer_queue.enable=True`。只切换模式时必要新增覆盖为：

```text
trainer.v1.trainer_mode=colocate_async
trainer.v1.colocate_async.num_warmup_batches=1
```

建议另外显式记录默认值，避免配置漂移：

```text
trainer.v1.sampler.max_off_policy_threshold=8
trainer.v1.sampler.max_off_policy_strategy=drop
```

基础 DSH 脚本最终 `exec "${COMMAND[@]}" "$@"`，允许尾部 Hydra override 覆盖前面的 sync。完成前置 environment/目录/manifest 准备后，实际命令结构是：

```bash
bash examples/dsh/train_qwen3_4b_online_rl.sh \
  trainer.v1.trainer_mode=colocate_async \
  trainer.v1.colocate_async.num_warmup_batches=1 \
  trainer.v1.sampler.max_off_policy_threshold=8 \
  trainer.v1.sampler.max_off_policy_strategy=drop
```

这只是底层执行命令，不能裸跑来替代已验收部署流程：必须由 owned-process-group supervisor 启动，记录完整 environment、实际 argv、版本与预算，创建标准 run-manifest，并用新的 RUN_ROOT/CKPTS_DIR。checkpoint 放 `/workspace/uni-agent-g1/checkpoint/<独立异步运行名称>/`，私有日志/回执放 `/root/runs/<运行名称>` 后归档。

当前具体缺口：

| 入口 | 当前行为 | 运行前处理 |
| --- | --- | --- |
| `examples/dsh/ops/launch_qwen3_4b_online_rl.sh` | 只接受 `--foreground`，其余参数报错 | 不能把以上 override 直接加到 ops wrapper；需受测透传或正式独立 launcher |
| `examples/dsh/train_qwen3_4b_online_rl.sh` | 实际 exec 透传参数；PRINT_COMMAND 分支遗漏尾部参数 | dry-run 不能原样证明最终模式，需修正并测打印/实际 argv 一致 |
| `examples/harbor/train_m2_online_rl.py` | argparse 无任意 Hydra 参数；自身 build_overrides 不含 trainer mode；environment 不会把任意 TRAINER_MODE 变成 Hydra | 需显式白名单 mode/warmup 参数，或正式组装 `base + build_overrides(launch) + async_overrides`；不能只设置环境变量冒充生效 |
| Harbor 单并发 | build_overrides 固定 gateway=1、max_concurrent_sessions=1 | 首次保留；若后续要并发，必须独立 override 和证据，不能期待 CONCURRENCY 环境变量生效 |

不能运行 PRINT_COMMAND 输出的删减命令来替代真实基础脚本；该分支不包括所有训练参数。透传修复应包含 CPU 测试：实际 exec argv 与声明 mode 一致；PRINT_COMMAND 包含同样 override；sync 默认不变；非法 mode/warmup fail closed。

## batch / TQ / warmup

- 维持单卡 NNODES=1、NGPUS_PER_NODE=1、TP=1；初始保留同步 batch=2、PPO minibatch=1、n=4、val n=1，2 global steps，4 train/2 public holdout（Harbor 使用其已验收课程实际数量）。train batch 必须大于 0，数据不能少于有效 batch。
- colocate_async 的 parameter_sync_step 默认 1。`trainer_base.step()` 要求 batch 能被它整除；不要误套 separate_async 专有的 `train_batch = parameter_sync_step × PPO minibatch` 断言。
- warmup=1 预填一批；不设为 0，不把增加 warmup 当作零成本加速，它增加在途任务、tool/sandbox 占用和过期样本风险。
- TQ 必须开启，`skip.rollout_tq.enable` 保持 False。保留任务完成/真实 verifier/Gateway token/trajectory dump/postprocessor 约束。
- async 会淘汰/补充 failed 或过期组；`sync_refill_failed_groups=True` 是既有同步专用开关，不是异步就绪证明。必须记录 evicted/failed/consumed 和 policy version，不能只看训练输出样本。
- 并发=1、max_num_seqs=1 可能不会自然出现跨更新暂停中的未完成生成。模式启动成功只能证明模式 smoke；没有实际 abort/resume 证据时，不得宣称 partial rollout 已验收。

## 暂停、deadline 与审计阻碍

源码未提供通用的“训练暂停时冻结 DSH/Harbor 任务时钟”机制。原生 fast task runtime/run timeout 为 1200 秒、verifier 为 300 秒；实际派生 v2 config 以 run manifest 为准。Harbor executor、worker、client 使用绝对 deadline 与 wall_time_seconds，生成暂停仍消耗预算。FullyAsync client 的 1 秒 abort 重试间隔不是暂停超时上限。

首个对照保留相同任务预算，使用既有 supervisor 2700 秒总墙钟、30 秒退出宽限；Harbor 同时保留 controller health 监督，不能用 `health=lambda:None` 规避真实桥接失败。若暂停导致 deadline 失败，要记录为调度不兼容/预算耗尽，不能放宽 verifier 或伪装成普通策略失败。预算要改时做新实验并同时记录 sync 对照。

同步审计的总通过条件要求所有观察到的组 `eligible-and-consumed`。异步正常可能存在预填但未消费或按 staleness 淘汰的组，不能直接继承总组数和“全部消费”断言，也不能跳过审计。需额外说明每一组是 consumed、policy-stale、仍在途取消或真正 invalid；消费组必须全部通过原始身份/token/reward审计，invalid 组不得被更新消费。

## 验收与非目标

1. 最终 resolved config 为 colocate_async，固定相同模型/数据/工具/verifier；无新环境安装漂移。
2. 训练消费组的 session/run/TaskRef/receipt/token/policy-version 全部可追溯；无伪造、缺失回执或重复工具副作用。
3. 有限且非零更新、LoRA 数值变化、base 不变、optimizer step/动量证据；独立 reload 验证 holdout，保留训练前后逐题结果。
4. 关闭和取消路径清理 GPU/bridge/sandbox；M2 同步 cleanup 修复须先通过，异步不能掩盖它。
5. 与同步比较有效任务/分钟、真实 token/秒、墙钟、失败/过期比例、峰值显存；先声明 smoke 或暂停恢复通过，再声明性能改善。

当前没有异步 GPU 实验结果。Modal、separate_async、多卡吞吐与 ContextPilot 树分支 partial rollout 均不属于这次最小对照。

## P1入口实施结果
2026-09-09：原生base/ops现已支持TRAINER_MODE=sync|colocate_async、正整数NUM_WARMUP_BATCHES与等效尾部Hydra参数。23测试通过/1旧Linux专用跳过；Harbor调用方51通过。上文入口缺口为实施前快照，已由这批修复解决；PRINT整体仍是简化投影，不等同完整resolved config。GPU异步尚未实测。
