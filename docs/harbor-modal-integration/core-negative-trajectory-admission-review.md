# Core 可信负轨迹准入审查

只读设计审查，2026-09-10。当前已批准 P1 继续以原511bd71完成r4终态、reload与归档；本文不阻断、不改变本轮源码、奖励或准入。**当前合同下整组拒绝的执行是正确的；这里讨论下一版合同是否更准确。**

## 已实现规则与实证

- `work_state/verifier.py:93` 对非法tool名或action记unsafe，没有区分“执行前已拦截”与“产生实际越权副作用”；`:109` 的complete只认正常completed，`:114` 以complete且无unsafe决定eligible。
- `trajectory_audit.py:175`、`:197`、`:199`、`:240` 要求envelope/receipt/奖励信息finished=true、eligible=true；同时严格核token/mask/logprob、trace/hash、receipt、session与版本身份。这把部分正常失败终止和证据损坏一起排除。
- `work_state/stage.py:281` 重评分后再次要求eligible=true；`memory_credit.py:164` 要求每条A/B stage同时finished/eligible。其作用是维护目前定义的完整可准入A/B组，不是GRPO数学上要求所有任务都成功。
- r4 `memory-bd787d87fce34dd8b495ba2df2364e46` writer：两次工具名`view`（call_bba47a02、call_5d8077cb）被固定policy.mjs的tools/pre-execute拦截，结果均WORK_STATE_POLICY_DENIED；原source SHA未变。原verifier重评分为finished=true、eligible=false、unsafe两次unapproved_tool。它具有可审计的失败证据，不是已经证明轨迹数据损坏；详见core-r4-tool-feedback-audit.md。
- 首writer重复create最终max-tokens，仍有原始token/mask/logprob、Session turn/end与receipt；但当前finished要求使其不可准入。预算语义另见core-token-budget-audit.md，不能事后按新8192累计限制解释旧r4。
- 合法动作但业务答错的reward=0已经允许消费。r4前两步完整8条A/B链均为零业务奖励，原16步参数审计也未见有效更新。不能说“当前完全不接受负样本”。

## 下一版建议：四个独立维度

| 维度 | 判定内容 | 下一设计原则 |
|---|---|---|
| 证据与版本有效性 | 真实token/logprob、mask、session/receipt/hash、实际策略版本、完整组身份 | 损坏、漂移、错配仍拒绝，不以低奖励替代完整性门 |
| 动作结果 | allowed、denied、实际side_effect、unknown | 可信的环境拦截是可学习失败候选；真实越权或不明副作用仍隔离 |
| 终止原因 | completed、预算截断、基础设施错误 | 保留真实原因；预算终止是否可训练须预先定义有限预算任务语义，不能把finished改成true |
| 业务结果 | 原任务成功/失败及原奖励 | 合法零奖励与被拒失败不能冒充成功，不为了产生优势人为补分 |

“已拒绝且无副作用”需要可信类型化policy决定和执行边界证据，而不是仅搜索错误文字；模型能复述同样文字。当前是本地工具策略，不是操作系统sandbox，少数source hash未变也不能证明整个宿主所有路径均未变化。新合同必须明确可信的副作用覆盖范围。

预算截断若被定义为固定资源内失败，可以保留其真实已生成token作为候选；若目标仍是无限期任务，应另处理truncation价值语义，不能随意当terminal。backend计量未知、被杀导致缺receipt或工具配对不完整不属于此类可信负轨迹。

## A/B与完整组约束

固定n4完整组不放宽：不能删除失败sibling后用较小成功组计算优势，也不能无声用成功样本替换失败。下一版可研究“完整n4组内包含可信失败”，但一个sibling证据不可信时仍须按合同整组隔离。

A在读取/保存阶段失败意味着可能没有真实B。必须设计独立、可验证的chain-failure终态与已执行A轨迹信用分配；**不能造B receipt、空B轨迹或把A伪标completed以满足旧A/B形状**。这属于新合同，不是删除一个assert即可完成。

当前失败整组丢弃/refill避免了部分组污染，也没有因单题失败立即停整个作业；r4首组拒绝后已真实补采样。代价是筛掉可信行为失败可能造成按成功行为筛选的偏差、增加采样成本，尤其会抹去模型学习“不要重复失败工具动作”的机会。

但保留更多可信失败**不保证非零梯度**：同一GRPO组奖励仍全零时相对优势仍无区分。应先做不改奖励的公开单变量诊断，检查模型能否在原任务出现成功与失败差异，再决定任务课程和信用分配；不能为造信号放宽准入。

建议下一设计先建立离线分类矩阵与恶意/损坏反例，验证只新增可信失败类型，保留所有原完整性与版本门。经明确新合同、CPU测试与固定版本新run后再实测；不回写r4旧数据或改变本轮验收结论。
