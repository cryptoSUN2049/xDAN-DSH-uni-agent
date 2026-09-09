# 原生训练工程验收标准：E0–E5

适用链路：固定模型 → Uni-Agent → DSH SDK/runtime → Gateway真实采样 → verifier奖励 → VERL更新 → checkpoint → 独立reload与新鲜评估。本文是验收标准，不是SSH操作手册；执行顺序和命令由配套复跑手册提供。

状态快照：2026-09-09，依据本worktree已落盘证据。当前12步课程已结束，step12独立reload已完成执行与4/4新鲜消费审计，专属optimizer比较及归档仍在收尾；后续状态以[handoff](../../tasks/harbor-modal-integration/handoff.md)和对应新结果文件为准。任何“已通过”必须注明具体run和范围，不从历史run自动继承给新代码或新recipe。

## 判定原则

工程闭环回答“是否真的执行、正确采样和消费、产生有效更新、保存后可重新加载并评估”。能力效果回答“模型在同预算、独立任务上是否更好”。**开发集暂未提分不阻止工程闭环验收；但没有真实梯度、发生异常消费、未独立reload或缺新回执，都不能用‘没提分也正常’掩盖。**

每个节点使用“通过 / 未通过 / 尚未验证 / 仅部分范围通过”，同时保留原始审计程序的返回值。所有CPU合成测试只证明对应代码边界；不能代替GPU运行证据。单个模型回答、进程PID、checkpoint文件存在、stdout写着success，都不足以单独判通过。

## E0：版本、环境和输入可确定

**通过条件**

- 记录实际integration commit、分支、VERL commit、DSH源码/SDK/runtime版本与安装物摘要、模型revision及本地路径；部署锁声明与实际检出事实分别记录。新integration代码可有新commit，不能误报成锁文件中历史M1 commit。
- 使用确定的venv与Python；依赖检查通过。清空旧PYTHONPATH后确认实际包来源，再以绝对PYTHONPATH从verifier工作目录核验导入和bundle。确认实际Linux runtime二进制摘要；macOS构建、源码已push或wheel版本字符串均不能替代该核验。
- 记录真实GPU可用性、模型/任务/数据/source/verifier/harness摘要、实际argv与非敏感关键env。新run/data/Ray工作目录独立，旧实验不可覆盖；模型与checkpoint位置明确。
- 锁文件、实际代码或输入变化后必须重新校验。模型revision声明与本地权重测量分开；未向上游重新验证来源时不宣称做过此验证。

**入口与证据**：[deployment版本锁](../../deployment/versions/g1-deployment-lock.json)、[source锁](../../deployment/versions/g1-source-lock.json)、[环境清点](../../deployment/checks/preflight.py)、[GPU检查](../../deployment/checks/gpu_smoke.py)、[SDK检查](../../deployment/checks/keyless_sdk_smoke.py)、[bootstrap](../../deployment/bootstrap/install-verl.sh)；各run的准备manifest、run-manifest、安装/预检日志。通用preflight需要其声明的manifest格式，不能把任意JSON当输入。

**当前事实**：既有已验收venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5` 被用于实际训练。新venv安装已有257包兼容性与隔离import检查，仍不等于新环境GPU复建验收。母12步课程实际integration为`d3084f2a771804f011c4e641ecf0986c7166bc86`；VERL固定`fefb080262e1c015a0ea05f958822a6a512dc795`，DSH 0.1.3a2 runtime摘要`d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`，模型Qwen3-4B revision`1cfa9a7208912126459214e8b04321603b3df60c`。详见[课程准备证据](context-v2-curriculum-r1-preparation.json)。

## E1：真实任务执行与奖励准入

**通过条件**

- 模型实际通过DSH完成工具调用；有独立task/session身份、真实Session trace、TaskResult、原始artifact与verifier receipt，时间窗和摘要相互绑定。
- Gateway提供真实prompt/response token IDs、response_mask与采样logprob；不能从最终文本事后分词冒充实际rollout。只把模型生成mask统计为model token，工具返回和上下文不是模型生成token。
- 合法零分与基础设施异常、未完成、越权、篡改分别记录。允许真实任务失败，但失败原因和eligible状态必须真实；不能把eligible=false改成0分合格数据。
- 对记忆A/B，A真实写入、冻结字节与来源版本、B新DSH/Gateway身份和独立读取均须验证；不能仅把A历史复制进B后宣称跨会话记忆。

**入口与证据**：[context准备器](../../examples/dsh/capabilities/prepare_context_training_v2.py)、[清单驱动推理入口](../../examples/dsh/capabilities/launch_context_inference.py)、[记忆链入口](../../examples/dsh/capabilities/memory_chain.py)、[typed轨迹审计](../../uni_agent/tasks/dsh/trajectory_audit.py)。run下`artifacts/traces/*/session.jsonl`、`artifacts/results/*/agent-result.json`和`verifier-receipt.json`；纯推理另有`inference-evidence.json`，训练不能凭空伪造此文件。

**当前事实**：context v2 r4四题真实strict准入/TQ回读通过；constraints-r3、updates-r1两族记忆A→冻结→B通过，均为`training=false`。母12步课程D3中一个sibling越界读取短索引，DSH正常返回工具错误，学生后续恢复并finished=true，但当前评分合同eligible=false；这是应保留的真实拒绝，不能按最终回答追认为合格。见[D3根因](context-v2-curriculum-d3-rejection-audit.md)、[第一记忆链](native-memory-writer-r3-result.md)、[第二记忆链](native-memory-updates-r1-result.md)。

## E2：完整组与实际消费正确

**通过条件**

- 训练按同题n个独立sibling完整组准入；当前recipe train n4、val n1。每条有唯一TQ key、stage/session/receipt/token映射，实际消费键与已准入组逐项一致；不得出现拒绝组被消费、半组消费、重复键、未知消费或无法解释的遗漏。
- 按独立任务数、采样尝试数、有效组数、实际消费条数分开计数；refill允许补新的有效组，但不能把重复采样算成新任务。课程覆盖率以消费task ID为准。
- 保留原审计JSON、stderr和退出码。`audit_qwen3_4b_online_rl.py`的整体eligible还要求**所有发现的组均合格且被消费**，比“被消费数据完整且拒绝组已隔离”更严格；出现合法拒绝时它仍可返回false，**不得改成pass、删掉失败dump再重算或放宽程序规则**。

存在拒绝组时应同时报告两项结论：①原严格审计`eligible=false`；②逐组核实“所有实际消费来自完整合格组，拒绝组消费为0，unknown/duplicate消费为0”。只有第二项有直接证据，才可表述为“消费边界成立，含已隔离失败组”；不能表述为“严格全组审计通过”。若第二项无法证明，E2就是未通过。自动验收门要求严格auditor通过时，必须保持该门失败，不用人工描述替代它。

**入口与证据**：[原生消费审计](../../examples/dsh/ops/audit_qwen3_4b_online_rl.py)，run下`agent-logs/step_*/session-*/trajectory.json`及`.npz`、`rollouts/*.jsonl`、`validation/*.jsonl`、run-manifest和audit输出。审计输出检查`eligible_groups`、`rejected_groups`、每组status、unexpected_consumed和legacy_unjoinable，而不只看一个总布尔值。

新NativeMemory使用[专用chain crosswalk审计](../../uni_agent/framework/memory_chain.py)，阶段dump是stage-only schema，不能直接拿旧单session v2消费审计冒充支持。其`consumption_verified=false`只证明信用映射/原stage文件核验；TQ写入返回也不等于trainer已消费，后续必须补真实消费键与组数据核验。

**当前事实**：旧context两步14/14组eligible-and-consumed，原audit=true。母12步原audit为**false**：24/25组合格、1拒绝、unexpected_consumed=0；52次train尝试中48条实际消费，D3拒绝组其余3个生成dump未消费，D2补采后共消费两组。实际仅覆盖11个唯一train题，不能写12题全覆盖。原结果完整保存在[课程消费审计](context-v2-curriculum-r1-consumption-audit.json)与[课程报告](context-v2-curriculum-r1-result.md)。

## E3：有效学习更新、optimizer与checkpoint

**通过条件**

- 至少一个实际消费训练组存在reward差异、非零advantage及有限非零梯度；记录其任务/组/策略版本，关联对应optimizer更新。不得以teacher/off-policy轨迹或仅参数文件变化替代online学习信号。
- 检查loss/梯度/模型参数/optimizer状态有限；optimizer step确实推进；训练参数逐张量有变化，需要冻结的base在已比较区间保持不变。首选明确的初始/最终比较；仅比较中间checkpoint时必须注明区间，不能扩大成全程或initial→final证明。
- checkpoint包含recipe需要的model、optimizer、extra状态，文件可读取且身份/摘要完整，保存到`/workspace/uni-agent-g1/checkpoint/<run-id>/global_step_*/actor/`。仅保存LoRA推理权重不等于可恢复完整训练状态。
- 同分组的advantage/gradient可以为0；已有Adam动量或weight decay仍可能改变参数。此种变化记录为状态延续，不当作新的任务学习信号。

**入口与证据**：[训练脚本](../../examples/dsh/train_qwen3_4b_online_rl.sh)、[ops启动入口](../../examples/dsh/ops/launch_qwen3_4b_online_rl.sh)、[逐张量delta](../../deployment/checks/checkpoint_delta.py)、[optimizer delta](../../deployment/checks/optimizer_delta.py)。run的`supervision/train.log`或旧run的`train.log`、trainer file metrics、checkpoint和数值审计JSON。监督器exit0是必要运行事实，不足以替代数值证明。

**当前事实**：旧context两步首步有真实非零梯度，第二步同分零adv；step1→2的252个LoRA变化与动量/decay一致，399个base不变，optimizer step1→2，证据[CPU审计](context-v2-train-r1-cpu-audit.md)。母12步exit0/1000.024秒，step3/4/5/7/10/12共6步有非零adv和grad；step6→12有504个LoRA张量变化、399个base不变且全finite。该母课程专属optimizer完整状态比较与reload还需以新增报告验收，不能借用旧两步报告代替。

## E4：独立进程重新加载

**通过条件**

- 原训练已经结束；以新run/data身份启动独立进程，使用指定持久checkpoint，不能复用训练内存中的模型。源码/环境及数据合同保持可解释的一致性，清单记录所有差异。
- 日志明确显示实际resume step及model、optimizer、RNG/lr_scheduler等extra状态加载；只看到resume_path配置不算加载成功。
- 本次为VAL_ONLY时，无新增训练消费/optimizer update或新训练checkpoint；加载optimizer状态与执行optimizer更新必须区分。
- reload失败时保留失败启动与日志。启动目录被PRINT_COMMAND等预检创建，也不能直接删除已有证据来假装首次成功。

**入口与证据**：[独立reload wrapper](../../examples/dsh/ops/reload_qwen3_4b_checkpoint.sh)，新run的supervisor-result、实际load日志、新manifest及训练输出目录核查；配套[context runbook](context-online-rl-v2-runbook.md)。

**当前事实**：旧context step2独立reload已415.009秒exit0，明确加载model/optimizer/RNG/lr_scheduler、无再次更新，见[reload报告](context-v2-train-r1-reload-report.md)。母12步的`context-v2-curriculum-r1-reload-step12`已470.012秒exit0；实际日志确认step12 model/optimizer/RNG/lr_scheduler加载，4/4 fresh val组审计true，无新增训练消费或checkpoint文件（输出目录存在但为空）。启动前目录冲突失败已保留；通过依据是加载与新消费证据，不是监督PID。

## E5：新鲜评估与可复建交付

**通过条件**

- reload后的评估是真实新session、新trace和新鲜receipt，实际Gateway/TQ回读或trainer val消费与清单匹配；不得复制训练期评估结果。评估样本可以与公开dev相同，但必须明确“重新执行”与“独立未见任务”不是同一概念。
- 记录每题reward、semantic/citation/严格准确率、失败与预算，训练前/后/独立reload分列。相同题合同和预算下结果略有随机差异，属于重新运行结果，不宣称逐字节/精确数值复现。
- 固定版本清单、操作脚本、非敏感argv/env、测试结果、原始证据、checkpoint位置和handoff可定位。日志若暂在/root/runs，结束后归档到/workspace/reports并记录SHA256；checkpoint直接落/workspace。Git分支保存代码和文档，不保存密钥或大模型权重。

**入口与证据**：独立reload的新`artifacts/results`、`validation`、审计报告与归档manifest；[旧reload结果](context-v2-train-r1-reload-result.json)、[归档摘要](context-v2-train-r1-reload-archive.json)。

**当前事实**：旧step2 reload有4条fresh且合格的dev结果，均值0.241875，严格准确率0；训练期dev均值0.255。证明保存→重新加载→新评估成立，不证明数值完全相同或能力提分。母12步dev step0/6/12均strict0/4、平均reward0.3979687579，尚无提分证据；新reload均值0.39796875、strict0/4，4/4新鲜评估消费审计通过，详细报告/归档正在收尾。

## 人工验收记录应保留的最小结论

| 字段 | 必须写明 |
| --- | --- |
| run / 版本 | 训练与reload独立ID、实际commit、模型/checkpoint/输入身份 |
| E0–E5 | 每项结论、证据路径、未验证或受限范围 |
| 严格审计 | 原JSON eligible及退出码，拒绝组/异常消费数；不改写原判定 |
| 训练信号 | 有效组/非零adv与grad步数、真实消费任务数、optimizer与参数比较区间 |
| reload与eval | 实际加载状态、无再次更新、新鲜结果与原任务合同 |
| 效果结论 | 已提分 / 未提分 / 尚不足判断；不与工程结果混写 |

截至该快照，已有M1和旧context两步的工程闭环证据；母12步课程训练与部分数值/消费审计已完成，但严格全组审计false且只覆盖11题，其step12 reload和4/4新评估消费已确认，专属optimizer比较与归档收尾中。两族记忆目前完成真实执行闭环，NativeMemory resident RL目前只有CPU接线测试；Harbor训练、RSI学生训练、全异步性能也不得据此宣称已经通过。
