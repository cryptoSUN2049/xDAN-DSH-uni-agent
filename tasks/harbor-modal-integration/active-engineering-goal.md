# G1：可复建 Agent RL 工程闭环

更新：2026-09-08。训练集成主线：worktree-harbor-modal-integration。

> 当前运行：固定代码2df91d7，v2-r4两步完成，504LoRA变化、399base不变、optimizer2→4，10/10组消费通过；独立reload已完成：2/2新轨迹通过，无再训练，GPU释放。用户云盘已扩到500 GB，写入通过；r1/r2配额失败、r3启动命令错误均保留。checkpoint=/workspace/uni-agent-g1/checkpoint/dsh-redact-m1-v2-r4。
> 验收索引：[acceptance-tracker.md](acceptance-tracker.md)。历史运行更新不替代此处当前状态。

## 1. 目标与完成边界

在用户现有 RTX PRO 6000 GPU 服务器，以固定代码、依赖、模型、任务和评分版本，交付通过 GitHub 可复建的 DSH → Uni-Agent → VERL 训练闭环，并完成一个 Harbor 任务的端到端训练增量。必须有真实执行、可信奖励、优化器更新、可训练张量数值变化、独立 checkpoint reload 和训练前后留出评估证据。

G1 = 原生底座诊断（有界辅助） + M1 DSH工程复建 + M2 Harbor训练增量 + 复建交付。
用户再次明确最终交付：各核心组件版本、我方仓库分支/完整commit、部署产物摘要、模型/数据/评分输入与运行参数一并固定；提供可重复部署和运行的全链路工程包，并以实际复建验证。分支用于维护，完整commit用于复现；不得只提供版本说明或安装脚本而缺真实运行证据。
本轮不以显著提分、全面记忆能力或完整RSI为完成条件。没有真实运行证明时不得标记通过。

执行状态：用户已明确持续推进原G1，当前新Pod短SSH可用；M1 r1已结束并记录失败，下一步新v2回归。get_goal仍保留旧SSH故障时的blocked状态；现工具仅支持complete/blocked，不能据此重复创建目标或宣称完成。以下以新版证据为准。

## 2. 固定身份与更新规则

| 对象 | 当前候选/要求 |
| --- | --- |
| 集成代码 | GPU当前代码74b253bfe2f580d4c6175672b5bdc0b3ccf623a8；新检查点见分支HEAD，尚未部署；每次run保存实际完整40位commit，维护分支worktree-harbor-modal-integration |
| 上游Uni-Agent | 89733ec81a69c3cc93ac90479de7ea7f01e51c1f |
| 配对VERL | fefb080262e1c015a0ea05f958822a6a512dc795 |
| GPU依赖 | 复用此VERL的uv.lock，fsdp+vllm；记录lock SHA256和实际安装清单 |
| 已解析核心版本 | torch2.11.0+cu130、vLLM0.24.0、Transformers5.5.3；安装成功不替代运行兼容测试 |
| DSH | 后续统一 b2369692ea530007075ebcd18d39fdba0bbd3982 / 0.1.3a2；Linux wheels、独立minimal/restart、Harbor setup已通过；旧7840仅历史M1 |
| 模型 | 首轮拟沿用Qwen3-4B；固定revision、Tokenizer/template；自有微调模型另作为明确候选，不静默替换 |
| 任务和评分 | 固定数据release、实例与family、划分、环境/Harness/verifier digest、解码与预算 |

原始候选JSON仍有null和旧集成revision，仅用于报告缺口；启动实验前生成该run的完整resolved manifest，不把旧候选文件当最终锁。
新修复允许产生新commit；运行中的checkout不更新。代码通过GitHub分发，模型/数据/checkpoint在外部持久目录。

### Session v2 候选升级（用户最新执行顺序）

用户进一步明确：后续工程统一切换0.1.3-alpha.2，包括默认构建、GPU SDK/runtime、Harbor镜像及run manifest；7840仅保留历史M1证据和显式回退备份，不作为后续M2默认。部署未完成之前不得宣称已经统一切换。
候选：b2369692ea530007075ebcd18d39fdba0bbd3982，0.1.3-alpha.2；upstream c389f96bf3a9b6807cb71ed6bdad5849be0df6d8。

- [x] 独立审计转换器归属与Session v2差异；DSH-Exp已修converter，本仓在线SDK不调用它，不重复复制。
- [x] 新版Session/转换器388项、built migration worker1项实测通过；本仓DSH适配与审计84项通过。
- [x] 本机built CLI+新版SDK initialize/shutdown、官方sdk-minimal与sdk-restart通过；后两者使用替身模型，不是训练。
- [x] 新版commit已发布GitHub；Linux官方wheel构建、独立安装minimal/restart、Harbor新版镜像boot/setup通过。旧422状态已解除。
- [ ] 新runtime的Harbor trace/receipt/Gateway token绑定、实际GPU更新/reload；通过后更新默认部署pin。

完整顺序与仓库/远程职责：docs/harbor-modal-integration/dsh-session-v2-upgrade-plan.md。ContextPilot专题仍有独立消费者迁移缺口，不把SDK测试当记忆能力验收。

## 3. 当前事实

- [x] GitHub分支维护与固定checkout入口。
- [x] 配对Uni-Agent/VERL迁移；CPU回归422通过、1项Linux特定跳过，另70项Gateway/RLInsight通过。
- [x] SSH核验GPU与存储；RunPod缺Docker CLI/socket，Harbor方案待验证。
- [x] 只读部署预检与3项边界测试。
- [x] VERL frozen安装预演及254包隔离安装成功。
- [x] CUDA前后向、模块导入检查通过；torch2.11+cu130、vLLM0.24，loss254.692459、gradient norm8.884957；不代表模型训练。
- [x] 固定Qwen3-4B模型/Tokenizer、T2四train与两public-dev及verifier身份。
- [ ] 新版M1/M2有效在线RL更新、独立留出与最终复建验收。

历史4步训练、64rollout、独立reload属于旧版本证据，不挪作本次完成证明。

## 4. 执行任务与验收门

### G1.0 环境可运行

- [x] 固定GPU依赖和安装工具版本，执行CUDA有限数值前后向；vLLM/Ray/Transformers/TransferQueue/Uni-Agent/VERL可导入。
- [x] 固定模型真实推理、Tokenizer/解析/预算诊断已执行；T2 baseline与SFT后eval保留真实失败证据。
- [x] 确定DSH Linux runtime可分发来源，构建后跑不调用模型的SDK协议检查。
- [x] 确定Harbor任务环境：RunPod无Docker；复用Mac Docker，固定amd64镜像实测SDK/Harbor setup与模型方向网络探针，无新付费服务。
- 产物：安装log、uv.lock hash、package清单、GPU检查JSON、模型身份、DSH构建与smoke报告。

### G1.1 原生小任务诊断（E0a，辅助，不替代M1）

- [x] 复用HotpotQA Task/MemAgent及dataset adapter；选固定小子集，训练/留出不重叠。
- [x] 采用单卡sync配置，不照搬8GPU separate_async，不在DSH外嵌套MemAgent循环。
- [ ] 先验证模型请求、多context轨迹和真实评分，再做少量更新与reload。
- [x] 报告真实奖励分布；native-v1两组分别全0/全1，梯度0、504个LoRA张量无变化；未通过有效更新，不盲目加步数。
- 时间边界：一个短工程批次内评估适配成本；若新增基础设施明显多于现有DSH单卡入口，暂停支线并记录原因，继续M1。
- 原生任务没有DSH receipt/finished合同的完整保障，单独标native-smoke，不发DSH合格报告。

### G1.2 M1：升级后的DSH训练闭环

- [ ] 首批冻结1—2类评分明确的现有DSH任务；列出具体task ID、train/validation/sealed-test角色。
- [ ] 固定模型与Harness先做留出基线eval，记录预算与完整失败分类。
- [ ] 真实DSH进程经Gateway产生token/轨迹；任务、会话、模型、环境及fresh verifier receipt一一关联。
- [ ] 严格准入完整rollout group；基础设施错误不冒充正常任务零分，unfinished/tamper/replay拒绝证据可审计。
- [ ] 新版在线RL小步训练：初始目标最多4个optimizer step；只有有效样本进入更新，loss/gradient有限。旧版通过记录不迁作新版；本轮SFT数值更新单列。
- [ ] 新版在线RL同名可训练张量数值delta；LoRA只要求adapter变化，base冻结正确。checkpoint文件hash变化仅为辅助。
- [ ] 新版在线RL checkpoint独立加载及同一留出集同预算eval；已完成的SFT独立加载与public-dev评估不替代此项。
- 通过标准：轨迹确被优化器消费、更新有效、reload成功、前后评估均可复核；不要求4步显著提分。明显退化必须分析，不能作为能力发布。

### G1.3 M2：Harbor单任务训练增量

- [x] 一个固定的轻量任务，oracle验证环境/评分/产物/清理。
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

## 当前运行证据补充

- 原生诊断与DSH安装：docs/harbor-modal-integration/native-v1-and-dsh-runtime-results.md。
- Harbor H0：本机Docker固定文件任务oracle=1/nop=0，无exception且专用容器/网络清理；不代替M2 DSH桥接/训练。
- M1 v2因指标字典聚合异常exit1，仍为失败。v3独立运行exit0、两步非零梯度、504 LoRA张量变化/399 base冻结、10/10组消费审计通过；独立reload exit0、2/2组审计通过。同预算两题留出accuracy仍为0，不声称效果提升。详见docs/harbor-modal-integration/m1-v3-results.md。
- M2 bridge提交eb536fb；真实borrowed Docker与控制隧道探针通过，模型通路/真实训练尚未完成。
- 独立复建cf2d3f5新checkout+新venv安装及CUDA前后向通过，复用缓存/既有DSH wheel；完整交付审计尚未完成。

## 当前 T2 证据与下一步（2026-09-08 新版运行）

- [x] 新DSH runtime真实6case、18业务调用与完整注册/清理生命周期（脚本策略）。
- [x] 来源绑定的56train/28dev决策；原生SFT累计56步，base399冻结、LoRA504数值更新；独立加载。
- [x] SFT后学生public-dev 0/2，非法JSON/错误注册API；正确保留失败与fresh receipt，未改判据。
- [x] 四条原注册决策补课64步，父BF16→FP32规范后LoRA504真实更新、optimizer64；不是新增示范。
- [x] 注册课程后独立完整学生评估已执行：exit0、0/2严格成功；需继续执行能力课程。
- [x] Harbor T2固定双镜像四Docker正反例：1/0/0/篡改拒绝，全部清理；私有Release回下载hash通过。
- [ ] 新学生经Gateway→Harbor→Task业务重算→trajectory audit的完整准入。
- [ ] 新版M1/M2真实在线RL消费和有效数值更新、独立reload、未参与训练的留出前后评估。

当前任务范围是log-tool注册/调用/撤销的DSH能力子集，不宣称全面熟悉架构、跨会话记忆或RSI已训练完成。

## 本检查点更新：零学习根因与下一步

- [x] 新DSH原样邮箱课程4/2，真实baseline两题均成功；两步训练自然exit0。
- [x] 明确验收失败：两step梯度0，504LoRA无变化；15组中5拒绝，消费0方差，不进行旧run独立reload。
- [x] 根因审计：可信已完成无define失败被v1 hard-veto排除；独立v2实现与CPU freshreceipt/audit测试，原reward保持0。
- [x] Harbor evolution单题评分、Task/audit、worker/isolated verifier/打包与训练准备CPU接线。
- [x] 长SSH探针复现超时，有限抖动处理代码与CPU测试；真实新容忍尚待回归。
- [ ] 新v2 GPU采样/有效数值更新/独立reload与留出评估。
- [ ] Harbor新课程真实Docker和学生M2更新，再完成可复建交付。

本检查点为工程进行中，不将CPU通过、SFT更新或自然exit0替代完整G1验收。此句原为提交时状态；最新部署和进程以本文顶部当前运行状态为准。

检查点验证：611项组合CPU测试通过，无skip；Ruff check/format与diff空白检查通过。新增真实Docker执行尚未运行，不以CPU结果代替。

当前执行覆盖：2df91d7已拉取GPU，v2源/配置哈希核验通过，/root/runs/dsh-redact-m1-v2-r1（supervisor63737）已启动两步/2700秒回归；尚未验收通过。旧“未部署/无训练进程”只描述提交检查点时刻。

### 2026-09-08 checkpoint持久目录与容量阻塞

- 用户要求统一`/workspace/uni-agent-g1/checkpoint/<run-name>`，启动设置`CKPTS_DIR`，不再默认临时本地盘。
- v2-r1首次保存失败；v2-r2在Hydra写配置时退出，未启动有效训练。实际1 MiB写入返回errno122，云盘全局df空闲不代表用户配额。
- 恢复至少25 GiB可用配额后新run重试；历史有效checkpoint不删除，G1未完成。

### 容量恢复与v2-r3实跑

用户将网络云盘扩至500 GB；1 MiB实际写入落盘通过。已启动r3（PID70820，2steps/2700秒），checkpoint=/workspace/uni-agent-g1/checkpoint/dsh-redact-m1-v2-r3。未删除历史文件。待梯度、数值、消费审计和独立reload验收。

### r4真实训练更新验收

- 两步梯度0.1337890625/0.2119140625；step1→2全部504LoRA变化、399base不变、张量有限；optimizer2→4且动量非零。
- trajectory audit eligible=true：10组全部准入，0拒绝、0异常消费，2个奖励方差组。
- 证据：docs/harbor-modal-integration/redact-m1-v2-r4-audit-bundle.json。GPU保持2df91d7，未同步本机新增Harbor代码。
- 独立reload：/root/runs/dsh-redact-m1-v2-r4-reload，supervisor78419，1800秒，仅评估，继承r4完整环境。未验收，不宣称G1完成。

### M1工程闭环验收通过，进入M2

r4两步在线RL真实更新+消费审计+独立reload均通过。报告docs/harbor-modal-integration/redact-m1-v2-r4-reload-result.json。此结论限定固定邮箱脱敏课程与公开留出；不代表效果提升、Harbor M2或G1全体通过。Harbor v2执行与打包接线正在推进，另一会话负责新增数据。

### 用户确认的推进顺序

先完成DSH/Uni-Agent/VERL在线RL及Harbor Docker同步链路完整验收，再另排性能实验。单卡先评估现有colocate_async，具备独立资源后再评估separate_async；rollout.mode=async不等于trainer全异步。固定runtime/任务/verifier，模型权重同步不等于源码升级。SFT/数据生产由其他会话负责，不进入本轮工作。

### Harbor v2 Docker环节完成

四mode真实容器通过（1/.25/0/篡改拒绝），全部清理通过，报告harbor-evolution-v2-docker-r1-result.json。学生RL预检发现Hydra路径键序列化阻塞，未启动GPU。每环节通过即记录并commit/push，不等G1全部完成。
