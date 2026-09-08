# G1：可复建 Agent RL 工程闭环

更新：2026-09-08。训练集成主线：worktree-harbor-modal-integration。

## 1. 目标与完成边界

在用户现有 RTX PRO 6000 GPU 服务器，以固定代码、依赖、模型、任务和评分版本，交付通过 GitHub 可复建的 DSH → Uni-Agent → VERL 训练闭环，并完成一个 Harbor 任务的端到端训练增量。必须有真实执行、可信奖励、优化器更新、可训练张量数值变化、独立 checkpoint reload 和训练前后留出评估证据。

G1 = 原生底座诊断（有界辅助） + M1 DSH工程复建 + M2 Harbor训练增量 + 复建交付。
本轮不以显著提分、全面记忆能力或完整RSI为完成条件。没有真实运行证明时不得标记通过。

平台状态：用户提交新版目标后，get_goal已确认本会话新G1为active。按本文推进，不需要再次创建或恢复。

## 2. 固定身份与更新规则

| 对象 | 当前候选/要求 |
| --- | --- |
| 集成代码 | 最新部署脚本提交b21ae90；每次run保存完整40位commit |
| 上游Uni-Agent | 89733ec81a69c3cc93ac90479de7ea7f01e51c1f |
| 配对VERL | fefb080262e1c015a0ea05f958822a6a512dc795 |
| GPU依赖 | 复用此VERL的uv.lock，fsdp+vllm；记录lock SHA256和实际安装清单 |
| 已解析核心版本 | torch2.11.0+cu130、vLLM0.24.0、Transformers5.5.3；安装成功不替代运行兼容测试 |
| DSH | 旧发布物未恢复；本地候选1af5b00在GitHub不可拉取，需发布/选择可复建源码并验证SDK合同 |
| 模型 | 首轮拟沿用Qwen3-4B；固定revision、Tokenizer/template；自有微调模型另作为明确候选，不静默替换 |
| 任务和评分 | 固定数据release、实例与family、划分、环境/Harness/verifier digest、解码与预算 |

原始候选JSON仍有null和旧集成revision，仅用于报告缺口；启动实验前生成该run的完整resolved manifest，不把旧候选文件当最终锁。
新修复允许产生新commit；运行中的checkout不更新。代码通过GitHub分发，模型/数据/checkpoint在外部持久目录。

## 3. 当前事实

- [x] GitHub分支维护与固定checkout入口。
- [x] 配对Uni-Agent/VERL迁移；CPU回归422通过、1项Linux特定跳过，另70项Gateway/RLInsight通过。
- [x] SSH核验GPU与存储；RunPod缺Docker CLI/socket，Harbor方案待验证。
- [x] 只读部署预检与3项边界测试。
- [x] VERL frozen安装预演及254包隔离安装成功。
- [x] CUDA前后向、模块导入检查通过；torch2.11+cu130、vLLM0.24，loss254.692459、gradient norm8.884957；不代表模型训练。
- [ ] 模型/数据下载与身份冻结、原生训练、M1、M2、新效果验收。

历史4步训练、64rollout、独立reload属于旧版本证据，不挪作本次完成证明。

## 4. 执行任务与验收门

### G1.0 环境可运行

- [ ] 固定GPU依赖和安装工具版本，执行CUDA有限数值前后向；vLLM/Ray/Transformers/TransferQueue/Uni-Agent/VERL可导入。
- [ ] 运行选定模型的真实推理，验证Tokenizer、解析、结束原因和输出预算。
- [ ] 确定DSH Linux runtime可分发来源，构建后跑不调用模型的SDK协议检查。
- [ ] 确定Harbor任务环境：实际验证Docker能力；若当前Pod不能运行，评估现有可用环境后明确方案，不自动购买新服务。
- 产物：安装log、uv.lock hash、package清单、GPU检查JSON、模型身份、DSH构建与smoke报告。

### G1.1 原生小任务诊断（E0a，辅助，不替代M1）

- [ ] 复用HotpotQA Task/MemAgent及dataset adapter；选固定小子集，训练/留出不重叠。
- [ ] 采用单卡sync配置，不照搬8GPU separate_async，不在DSH外嵌套MemAgent循环。
- [ ] 先验证模型请求、多context轨迹和真实评分，再做少量更新与reload。
- [ ] 报告真实奖励分布；无组内差异时诊断难度/格式/评分，禁止伪造差异。
- 时间边界：一个短工程批次内评估适配成本；若新增基础设施明显多于现有DSH单卡入口，暂停支线并记录原因，继续M1。
- 原生任务没有DSH receipt/finished合同的完整保障，单独标native-smoke，不发DSH合格报告。

### G1.2 M1：升级后的DSH训练闭环

- [ ] 首批冻结1—2类评分明确的现有DSH任务；列出具体task ID、train/validation/sealed-test角色。
- [ ] 固定模型与Harness先做留出基线eval，记录预算与完整失败分类。
- [ ] 真实DSH进程经Gateway产生token/轨迹；任务、会话、模型、环境及fresh verifier receipt一一关联。
- [ ] 严格准入完整rollout group；基础设施错误不冒充正常任务零分，unfinished/tamper/replay拒绝证据可审计。
- [ ] 小步训练：初始目标最多4个optimizer step；只有有效样本进入更新，loss/gradient有限。
- [ ] 比较同名可训练张量数值delta；LoRA只要求adapter变化，base冻结正确。checkpoint文件hash变化仅为辅助。
- [ ] 新进程加载明确checkpoint，核对键与模型身份，执行同一留出集同预算eval。
- 通过标准：轨迹确被优化器消费、更新有效、reload成功、前后评估均可复核；不要求4步显著提分。明显退化必须分析，不能作为能力发布。

### G1.3 M2：Harbor单任务训练增量

- [ ] 一个固定的轻量任务，oracle验证环境/评分/产物/清理。
- [ ] DSH bridge使用Harbor拥有的环境，不重复创建sandbox；真实Gateway endpoint连通。
- [ ] 保留trial/session/token/policy/verifier身份；正常任务失败与环境失败分开。
- [ ] 对此组合执行真实VERL更新、数值变化检查、独立reload和小规模复评。
- 通过标准：这条组合自己的新运行证据完整；oracle成功或M1通过均不能代替M2。

### G1.4 复建与交付

- [ ] 在独立干净checkout/隔离环境从GitHub固定commit复建关键流程，记录缓存/镜像依赖，避免夸称全新主机复现。
- [ ] 文档给出安装→预检→eval→train→audit→reload→停止的实际命令。
- [ ] 保存run manifest、原始log、trace/receipt、训练消费审计、checkpoint身份和前后eval报告。
- [ ] Ruff check/format、相关测试与self-review通过，commit/push；handoff记录分支、服务器进程和下一步。

## 5. 预算与失败处理

- 使用现有GPU，不创建额外付费GPU/Modal/API资源；不修改无关服务，不自动删除云服务器。
- 每个训练run配置显式max steps、rollout/concurrency、episode token/time预算和总wall-clock截止；运行前落到manifest。未配置总截止不启动长作业。
- 保持首轮并发低；OOM先缩短长度、减少batch并核验offload，记录配置变化，不削弱证据门禁。
- 依赖冲突先保存错误，按固定lock/源码诊断；不在系统环境反复无版本pip升级。
- 零梯度、奖励常数、截断或消费审计失败：判失败并诊断，不靠增加步数掩盖。
- 截止触发停止本run进程并保存证据；停止进程不代表停止云资源计费。

## 6. 后续Goal（不混入G1）

- G2能力：C1 DSH策略内化→C2记忆/多context与C3受控Harness演化→C4权重×Harness四组归因。主要指标为未见任务成功与事实保真；token压缩不是独立成功标准。
- G3性能：固定质量门后，按瓶颈推进并发、全异步与可选Modal，验收吞吐、尾延迟与每成功任务成本。
- 各实验沿用experiment-matrix.html的八维配置及独立证据状态；四种循环身份分别记录。

## 7. 平台Goal建议文本

在当前harbor-modal-integration worktree和用户现有RTX PRO 6000上完成G1工程验收，严格按tasks/harbor-modal-integration/active-engineering-goal.md推进：固定Uni-Agent/VERL配对版本及完整部署身份，复用原生小任务作有界诊断；完成M1 DSH→Uni-Agent→VERL真实轨迹/评分/更新/独立reload/留出eval，完成M2固定Harbor单任务的DSH训练增量，最后交付GitHub可复建入口与可审计证据。未满足全部必需验收不得complete；不把历史训练、CPU测试或文件hash变化代替本次运行。第二阶段能力提升、第三阶段性能规模另立目标。

## 8. 用户确认的任务递进（2026-09-08）

原生Uni-Agent最简单训练 → 带DSH真实运行轨迹的记忆/上下文任务 → Harbor长任务与泛化 → 动态Harness/RSI → 性能规模。原生diagnostic不变为长期主线。
M1优先检查已有ContextPilot证据合同和DSH记忆动作能否承载首批任务；先通过真实观测/动作/结果/奖励到更新的工程门，再进入C2效果验收。若记忆runtime尚缺实现，明确列缺口并先复建DSH调用基础，不以普通任务假称记忆能力已经完成。
M2 Harbor端到端验收仍为G1必需范围；完整RSI和显著效果保持后续Goal。
