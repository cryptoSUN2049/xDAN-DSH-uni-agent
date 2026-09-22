# VERL MOPD 首轮工程验收

用户已于 2026-09-22 确认 PG-MOPD 设计并授权实现。工作分支 `worktree-verl-mopd`，不替换正在运行的 VERL 评测。

## 保留的基线配方（native-pg）

- 单机三个独立 GPU 角色：学生 actor/rollout 共置一张，SWE 与 Terminal 教师各一张，TP=1。显存是否足够还需要实际验证。
- 使用同步 V1 trainer；复用原生 TeacherManager、`k1` PG loss、Harbor adapter，基线算法不变。新 MiMo 配方通过下述固定版本补丁接入。
- 路由字段 `teacher_domain`，保留原 `data_source` 和 Harbor metadata。
- N=1，temperature=1，不截断采样分布；teacher 对学生原始 token 与相同前缀评分。
- 学生生成 token 有梯度，prompt/tool observation 无直接蒸馏梯度。
- 纯 OPD，clamp ±5，原生 PPO ratio clip 0.2，distillation 的原生 dual-clip fallback 3。环境奖励仍记录，但不参与梯度。
- token-mean，batch=2，minibatch=2，1 epoch/update。显式要求每个任务恰好一条 admitted trajectory，防止多链导致多次优化。
- 固定 LR 1e-6、constant scheduler、warmup=0。原生 trainer 会覆盖 scheduler horizon，因此不能靠传入 `optim.total_training_steps` 保证续跑一致。
- 原生 V1 将 checkpoint transport 设置为 `naive`；YAML 明确写出实际行为，不宣称 NCCL。
- 四个不同训练任务、两个工程验证任务；先完成 step1 保存，单独重启到 step2。没有模型效果自动止损逻辑。

## 数据与教师输入

本机已准备：`outputs/mopd-data-smoke/prepared/receipt.json`。详细来源和哈希见 `data-readiness.json`。训练顺序 SWE/Terminal/SWE/Terminal，每批覆盖两个教师。

这六道题复用既有审计资产，历史 nop/oracle 证据被核对，本轮未重新执行。验证题来自历史训练池，只是工程 smoke，不能证明泛化能力。

远端运行前，将任务放到确定路径，用已有 Harbor preprocess 和本分支 prepare 重新生成 parquet，使 metadata.task_path 指向远端实际目录；不要直接把本机绝对路径搬到服务器使用。

```bash
PYTHONPATH=.:verl python -m examples.harbor_mopd.prepare \
  --train-parquet /run/source/train.parquet \
  --validation-parquet /run/source/validation.parquet \
  --manifest /run/task-manifest.json \
  --domains swe terminal \
  --output-dir /run/prepared
```

Manifest 要求 `schema_version: 1`，每条 tasks 包含 `instance_id, task_id, source, family, revision, split, fingerprint, teacher_domain`。fingerprint 使用 `prepare.fingerprint_task`，不冒充原先 Tinker 的不同哈希算法。可选 `leakage_group` 用于跨 split 的同题变体隔离；family 只是来源信息，不禁止同仓库不同题。

教师必须是本地 HF 导出，包含 config/tokenizer JSON 和 safetensors。FSDP actor checkpoint 不能直接作为 vLLM 教师路径。检查哈希只证明输入文件身份，不证明服务成功加载。

```bash
PYTHONPATH=.:verl python -m examples.harbor_mopd.launch \
  --inspect-model /models/teacher-swe
```

Registry 示例（将每个 sha256 替换成 inspect-model 输出的顶层 sha256）：

```json
{
  "schema": "harbor-mopd-registry-v1",
  "student": {"model_path": "/models/student", "sha256": "REPLACE"},
  "teachers": {
    "swe": {"model_path": "/models/teacher-swe", "sha256": "REPLACE"},
    "terminal": {"model_path": "/models/teacher-terminal", "sha256": "REPLACE"}
  }
}
```

当前实现要求 tokenizer.json 字节相同，确保 token ID 合同；模型身份还绑定配置、权重与单独存储的 Jinja 模板。字节检查不能代替 teacher 的真实加载/评分对齐探针。

顺序训练的两个 checkpoint 可用于路由组件检查，但不是已验证的互补领域专家；正式能力实验先资格评测。

## 资源与运行合同

启动器要求一个已经落实的 allocation 文件：

```json
{
  "schema": "harbor-mopd-allocation-v1",
  "owner": "实际操作者",
  "schedule_reference": "实际排期和预算授权记录位置",
  "gpu_uuids": ["GPU-实际UUID1", "GPU-实际UUID2", "GPU-实际UUID3"],
  "max_steps": 2,
  "budget_usd": 20
}
```

上面的 20 是格式示例，不代表用户已经批准金额。`budget_usd` 是记录与审查字段，代码不提供美元硬上限；需要外部实际计费监控。启动器只约束训练步数、身份与资源冲突。现有评测的 Modal 预算不能转给本轮。

同一 allocation 的三个 UUID 必须在同一机器可见；物理设备或进程检查失败就不会启动。run 目录锁与 GPU UUID 锁用于避免本启动器重复操作；其他会话排期仍需操作者核查。不会停止其他 GPU 进程。

`launch.json` 复用已有 Harbor 准备流程生成的 `dsh.harbor-m2-launch.v1`，包含本次正确的 controller registration、postprocessor 和 TASK_CONFIG。不能擅自挪用其他训练的运行身份。完整配置信息不打印到公开终端；native trainer.log 作为私有运行产物处理。

## 命令

默认只核查本地模型/数据文件、原生 tokenizer/dataset、原生配置，不启动 Ray/GPU。CPU 环境没有 vLLM 会如实记录依赖未安装；执行模式要求依赖齐全。

```bash
PYTHONPATH=.:verl python -m examples.harbor_mopd.launch \
  --launch /run/launch.json --registry /run/registry.json \
  --data-receipt /run/prepared/receipt.json --allocation /run/allocation.json \
  --run-root /run/mopd-unique-id --tool-parser hermes --target-step 1
```

只有模型/调度/预算/Harbor 身份均落实后，给同一命令添加 `--execute` 完成第一步。第二次仍使用相同输入与 run-root，追加：

```bash
--target-step 2 --resume-from-path /run/mopd-unique-id/checkpoints/global_step_1 --execute
```

恢复检查：原生 checkpoint 的模型、optimizer、extra_state 与 data.pt 完整，文件哈希和上次完成回执相同；代码、依赖、任务配置、模型、数据、教师路由和算法未变化；目标只递增到已约定 max_steps。失败/不确定更新不自动重放，需要先核实现场。

初始阶段结束后再恢复是工程检验安排，不是自动评估筛选或模型效果止损。

## 产物与验收边界

- `contract.json`：输入/算法/源码/依赖/资源合同。
- `state.json`：执行状态；`process_succeeded` 只表示进程成功退出且 checkpoint 文件回执齐全。
- `attempt-to-step-N/trainer.log` 与 `result.json`：保留各次执行，不覆盖原始失败。
- Harbor 轨迹 JSON + NPZ：domain、native manager 解析的教师路由/配置路径、原始 token/mask 哈希、实际 teacher IDs/logprobs。
- `identity_source=native_manager_configuration`、`loaded_weights_verified=false`：显式表示仍缺 worker 加载权重证明。

正式通过还要逐项取得：两个教师实际响应与权重身份、真实工具交互、有效梯度与学生参数变化、更新后的 rollout 版本、checkpoint 独立加载、优化器/游标恢复后下一次更新、拥有资源清理情况。当前启动器不会自动把进程回执提升为端到端或能力通过。

GPU真实闭环和9B/27B能力收益仍待执行；CPU测试与本地数据准备不是其替代品。

## 部署范围

当前 wheel 构建只包含 uni_agent 包；examples 下的 launcher、prepare 和 YAML 需要随整个固定 Git checkout 一起部署，不能仅安装 wheel 后就声称入口齐全。本轮没有上传或重部署现有 GPU 节点。

## 2026-09-22 只读资源复核

现有节点仅两张 RTX PRO6000 Blackwell Server Edition 96GB。03:58 UTC 快照中 GPU0约79.8GB被旧评测占用，GPU1空闲；闲置不代表已分配。当前原生三角色布局不能在该节点原样执行。Qwen3.5-9B 与 Qwen3.8-27B 的本地 safetensors 分别4与18个；tokenizer.json SHA不同，首版严格合同会拒绝直接混用，需要单独验证语义兼容性。旧 merged.verl-merger 目录没有 safetensors，不能直接注册为可服务教师。

补充只读结构核查：9B/27B tokenizer.json 的差异仅在 added_tokens；model.vocab 相同，added token 的 id→content 映射并非完全相同。此证据不能证明旧实验存在错位，也不能证明差异 token 出现在本任务中；跨尺寸实验必须检查实际序列使用的 ID，并验证特殊 token 语义后再放宽当前严格合同。

## MiMo 新配方：2026-09-22 实施

先应用本仓库补丁，保持 VERL submodule HEAD 为 a9f2985：

```bash
bash deployment/bootstrap/apply-verl-patches.sh .
```

0001 保留 padding teacher payload；0002 接入精确目标、全局有效轨迹计数、Top64 logits 分派。源码、补丁和实际依赖均进入恢复合同；不得从旧 native-pg run 切换新算法后续跑。

| `--recipe` | 目标 | 轨迹归约 | N | 奖励 |
|---|---|---|---|---|
| `native-pg`（默认，保留旧基线） | 原生 k1 + PPO | token mean | 1 | 仅老师 |
| `pg-sequence` | detached teacher-current log-ratio，clip ±5，直接 score-function surrogate | 每轨迹平均 | 1 | 仅老师 |
| `top64-reverse` | teacher Top64 上 p log(p/q)−p+q，全词表归一化 | 每轨迹平均 | 1 | 仅老师 |
| `flash-orm` | teacher advantage + alpha×ORM，current/sampling IS 越界置零 | 每轨迹平均 | 4 | Harbor verifier 的 GRPO 优势 |

新配方的 `use_policy_gradient=false` 是为了防止原生 wrapper 再套 PPO；pg-sequence 和 flash-orm 内部仍是显式 policy-gradient 代理式。Top64 是 direct loss。三者都拒绝上游重复 IS、entropy/reference KL 正则以及不支持的 fused/TP/SP 路径。

沿用前面完整命令，增加 `--recipe pg-sequence` 或 `--recipe top64-reverse`。Flash 必须显式提供本次研究选择的系数，不存在可照抄的官方默认值：

```bash
# 这些数值仅演示参数格式，不是论文超参，也不是已经批准的实验配方。
--recipe flash-orm --orm-alpha 0.3 --is-lower 0.5 --is-upper 2.0
```

每种配方使用独立 run-root。默认仍然只 preflight，实际运行须附 `--execute`。更改 recipe、alpha、IS 区间或任何模型/源码/数据都会导致原 run 的恢复合同不匹配。

### 训练方式与复现边界

当前继承 `base.yaml` 的 LoRA rank16、alpha32、all-linear；这是可调试的工程配方，并不等于 MiMo 生产训练全部设置。公开公式复刻、GPU工程闭环、专家能力整合、全参数规模复现分别验收。未公开数据/超参不作还原声明。

同期权重版本检查只要求每条轨迹的实际 min/max version 相同；不能直接把训练 step 当作权重版本。原生同步 trainer 在 step1 采样时使用已发布的 version0，保存与恢复也要保留这个区别。

新的数学诊断记录 OPD/ORM/联合优势与 IS 拒绝量；Top64 报告师生候选概率质量。各 microbatch 的平均诊断不冒充全局加权统计。现有 JSON/NPZ 保留原始 token、mask、turn、reward、版本与教师张量，可离线按领域及长度复核；thinking/action/EOS 分类仍需实际 tokenizer 与 renderer 语义，不能凭总长度作结论。

资源合同、容量估算与9B→27B扩展见 [resource-readiness.md](resource-readiness.md)。三张卡仅为当前角色下限，尚无GPU显存实测或训练通过证据。
