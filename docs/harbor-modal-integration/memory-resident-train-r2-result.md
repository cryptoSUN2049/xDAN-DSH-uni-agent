# Resident memory train-r2：initial validation 的 writer 质量失败

固定代码 `c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0`，checkout `/workspace/rebuild/uni-agent-memory-resident-r2`，run `/root/runs/memory-resident-train-r2`。本轮只读调查，未改原评分、源码、回执，未启停或重启 GPU。

## 终态与时间

监督 child `196565`，exit **1**，**380.009 秒**；原 manifest 状态 `failed`。manifest 原始开始时间 UTC `2026-09-09T02:28:34.282107+00:00`，对应 UTC+8 `2026-09-09T10:28:34.282107+08:00`；结束时间 UTC `2026-09-09T02:34:37.468645+00:00`，对应 UTC+8 `2026-09-09T10:34:37.468645+08:00`。监督启动与 manifest 初始化属于不同时间点，不混用。

审计时 GPU compute-apps 为空。运行名含 train，但仅到 **initial validation、step 0、单 sibling writer A**；没有进入 train n4，没有 optimizer 更新，没有新 checkpoint。

## 首次实质失败与异常链

1. writer session `memory-A-67d69f8f1d764050a9a98a14bb163523` 正常结束，原训练 verifier receipt 为 **finished=true、fresh=true、eligible=true、reward=0**。这里 eligible 是安全/格式/来源等准入，不能代替 writer 的质量要求。
2. trace 的 `assistant/message seq=8` 在同一次模型输出中生成两个 tool calls：`view` 源文件与 `create` 记忆文件。因此 create 的 file_text 已在模型看到 view 返回值之前生成。执行顺序为 seq9 view、seq10 返回真实源、seq11 create、seq12 创建成功；执行看似先读后写，不代表中间经过模型观察与决策。
3. 源事实为 `forbidden=public_bucket`、`region=eu-west-test`；实际写入为虚构占位 `key1=value1`、`key2=value2`，source_version 字段虽正确，事实没有保真。最终文本还声称忠实复制。没有 policy 越权或工具 JSON 解析错误证据。
4. `memory_training_stage.validate_stage_execution` 用原 scorer 复核，writer reward 不为 1 时在 **Writer failed quality gate** 分支拒绝（依据固定源码与原产物复评分定位；顶层日志仅暴露组失败，未逐字打印该内部异常）。控制端按原合同不冻结，B 没有启动。这不是 StageSpec 接线损坏或 verifier 误拒。
5. initial val 整组被拒后，框架报告 `rollout failure at global_steps=0: 1 session(s) failed`，随后固定 trainer/TQ 报 `ValueError: Received an empty list as keys.`。最后的空 keys 是没有可消费组后的次级框架异常，不能拿它代替 A 的真实失败原因。

CPU 用固定源码 `memory_verifier.score` 对原 fixture、18 项 trace 事件与原 envelope 独立重评分，与原 reward/finished/eligible 一致。原回执未重写或追认为成功。

## 验收结果

- 原始 stage dump：1 个 A；reader B：0；frozen manifest：0。
- chain crosswalk：0；实际 train/val 跨链消费：0。
- 终态后专用 `audit_memory_training` exit **1**、`passed=false`、`consumption_verified=false`，不会把空集合判成通过。
- 无 n4 训练组、训练 gradient/advantage 指标或 checkpoint。没有完整 A/B chain 的实际版本证明，因此不对跨阶段 same-policy 门作成功结论。

## 后续边界

这是动作依赖顺序与事实保真的真实负例，可为下一版工作状态课程提供素材。旧门保持不变；不靠接受错误 writer、跳过 initial val 或重跑到偶然成功来改写本轮结果。若今后调整课程，应单独版本化“观察返回之后再决策”的目标，同时保持安全/身份与语义评分的区别。全拒绝组的 trainer 错误呈现可以另行改进，但它不会使本轮原始 A 行为变正确。

详见 [完整 JSON 证据](memory-resident-train-r2-result.json)，包含原 receipt、独立 rescore、批量工具调用身份、trace/log SHA、监督与 UTC/UTC+8 时间。远端保留 `consumption-audit.json` 与 `result-summary.json`。先前 resident val-r2 成功保持独立记录，不据此替代本轮训练验收。
