# MiMo → VERL MOPD：从数据到真实验证

2026-09-22。实施授权已取得；新 GPU/Modal 费用和节点分配待落实。算法设计见 mimo-objectives-design.md；资源见 resource-readiness.md。

## 要复现什么

可复刻公开的领域 RL→冻结专家→学生 on-policy 多教师整合流程及公开目标公式。不声称获得 MiMo 私有数据、生产超参数或相同能力数字。当前实现是 LoRA 工程配置；全参数训练另做容量与效果验收。

首先做同源9B→9B的多专家整合以减少变量，再评估27B同源版本。27B→9B是额外的跨尺度实验，须先处理当前已知added-token映射差异；不能把这个变量混进首次算法验证。

## 数据与训练阶段

| 阶段 | 输入 | 产物 | 验收 |
|---|---|---|---|
| SFT起点 | 固定9B checkpoint和实际tokenizer/template | 唯一共同初始化S0及文件哈希 | 格式、工具调用、自然结束、各领域基座分数 |
| 领域RL | SWE与Terminal独立训练分区；真实环境verifier | 从同一S0分别训练的T_swe/T_terminal及optimizer/cursor | 各教师在其held-out领域优于S0；评估跨域遗忘 |
| HF导出 | 完整FSDP checkpoint/或LoRA与基座 | 两个可独立加载、不可变HF目录 | 导出数值一致性、实际加载与相同前缀评分探针 |
| MOPD | 学生S0在线rollout；按teacher_domain路由 | 每个目标独立学生checkpoint与轨迹 | 数学、工程、能力三层证据分别判定 |
| 下一轮 | 整合后的学生作为新共同起点 | 新领域RL专家及后续整合 | 每轮固定可追溯父checkpoint，不循环使用评估题训练 |

SFT不是为了凑完整流程而无条件重训：先测现有S0的格式和工具能力；若已有合格SFT基础，冻结复用。若确实需补SFT，另准备有环境成功证据的完整轨迹并保留thinking/action/stop边界，不将任意教师输出当作正确答案。

每条训练记录至少绑定任务ID、仓库/题目revision、环境fingerprint、来源、领域、split、teacher_domain与可选leakage_group。现有prepare已检查显式join及文件身份，但不能自动发现所有语义相似题或泄漏；正式held-out需要补专门去重与污染审查。

当前只有4train+2engineering validation。它们用于接线和恢复检查，不是领域RL数据规模或无污染能力评测准备完成的证据。现有顺序RL checkpoint也不能直接记作两个合格互补专家。

## 实验顺序

1. 保留native-pg历史基线，记录其PPO与token-mean差异。
2. 验证pg-sequence；如果研究长度归约本身，单独设置只有归约不同的对照，不能把同时去掉PPO造成的变化归因于长度。
3. 从同一S0启动top64-reverse；记录全词表归一化及候选概率质量。
4. 从同一S0启动flash-orm；显式登记alpha与IS范围，N4保留真实全对/全错组。
5. 独立held-out比较领域成功率、配对差值与不确定性、遗忘、长度/重复/工具轮数、每次成功成本。先看工程结果再登记效果实验预算，不预先承诺题量和训练步数足以证明提升。

每组两步工程验收采用新进程恢复；能力实验不只跑两步。若超长，先区分thinking、动作行文、工具轮数以及环境输出；只凭长度不取消训练。EOS语义对齐、reference约束或混合轨迹是后续独立干预，不悄悄写入MiMo公式复刻。

## 当前交付与缺口

- 已有：领域路由、真实任务身份准备、原生基线、三种新目标代码与CPU数值/梯度/接线测试、不可变恢复合同。
- 本轮已验证：551项整合回归、125项最终定向测试、三个新目标CPU保存恢复精确一致、wheel数学/框架源码一致。提交状态以git log为准。
- 仍缺：新实验节点/预算，领域RL训练集和无污染held-out冻结，专家训练与资格评测，HF导出实际加载，GPU完整闭环与能力实验。
- 禁止把CPU教师service fixture、checkpoint存在、进程exit0或两步工程成功写为“MiMo完整复现/能力已通过”。
