# Core reader 角色诊断：单变量设计

状态：设计待确认；不修改正在运行的4232df3预算实验，不替换原r4结果。属于memory-rl-evidence-and-next-experiment.md中D1/D3的前置公开诊断，不是P2封存效果实验。

## 目标与可证伪假设

实测r4前两步B未读取memory；4条实际prompt已经包含完整工具调用示例，不能继续以缺示例解释。现stage.py对已存在index也写may be missing；共用common还包含组织记忆的writer指引。假设是reader角色与文件存在状态不够明确，影响小模型的执行选择。修正文案不保证成功，必须在同条件配对中检验。

## 实验

先使用固定core公开dev WS01/03/05各4题共12题；WS06另4题作无需memory负对照，共16题。每题n4、两种reader提示，A采样固定且只执行一次；真实A产物冻结后，旧B与新B均读取同一份bundle，使用独立session。A失败单列；不伪造B、不静默补成功A掩盖失败。固定基础模型、预算8192、运行版本和采样参数。诊断B分支不作为完整在线训练样本提交TQ。

旧条件使用原prompt；新条件仅改reader指引：明确它是恢复执行者、不写memory；对inventory中实际存在的index明确可读、先检查索引再按任务需要取证；index不存在时如实告知，不暗示隐藏事实或提供答案。不增加tool示例、不改writer目标、不改业务评分与输出合同。

这不是“有没有记忆”的因果消融，也不是候选训练收益；只是对相同A产物比较reader使用行为。B分支可重用安全的stage准备和执行接口，但必须有独立branch身份，不能冒充原A/B唯一链或复用其receipt。

## 架构与API合同

真实DSH writer → validate → frozen bundle及原SHA → 两个只读branch → 各自DSH reader → 原verifier与配对汇总。

诊断控制端绑定source head、model revision、任务ID、writer receipt、bundle SHA、branch ID、prompt revision、预算。禁止从模型输出选择prompt variant；不向模型暴露truth/controller fixture。模型唯一执行循环仍为DSH，Gateway采真实tokens。

每branch保存fresh result/receipt/trace；相同输入bundle字节hash必须一致。两branch写不同outputs目录，reader无权修改bundle或其他branch。业务错误与未完成作为结果保留；证据/版本错配中止该配对。不可将控制端报告字段当模型可见指令。

## 文件清单（拟）

- 新 examples/dsh/capabilities/diagnose_core_reader.py：有界准备/执行/配对报告；复用既有operator和stage执行能力。
- examples/dsh/capabilities/work_state/stage.py：必要时提取reader准备的纯函数，旧默认输出逐字节不变；新branch API只给诊断入口使用。
- 新 tests/examples/dsh/test_diagnose_core_reader.py：身份、相同bundle、分支隔离、真存在信息、失败保留与不进入训练的回归。
- docs/harbor-modal-integration/core-reader-role-diagnostic-runbook.md：固定命令、预算、结果判读及恢复方法。

## 验收

CPU先验证旧prompt/默认行为不变，目录冲突拒绝，无truth泄漏，伪receipt与bundle篡改拒绝，branch不能越界，A失败没有伪B，n4不被部分成功替换。跑相关回归及全库Ruff双门。

GPU先1题成对canary，确认真实token/工具调用与不同输出隔离；再按预定16题执行。报告A成功/完成率、B实际读index/证据比例、业务成功率、幻造事实、重复动作、生成token和失败原因；按task而非64个相关采样计算不确定性。16题为诊断规模，不足证明跨场景收益。

只有明确降低执行失败且无边界回归，才设计下一版联合RL课程。若无改善，保留负结果并转向工具能力/事实使用诊断，不进一步盲目加长提示。
