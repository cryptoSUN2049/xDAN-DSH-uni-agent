# Core reader 提示修订诊断：配对设计（已批准实施）

状态：用户已明确“允许开始”“批准”；先实现与CPU测试，GPU恢复后执行；不修改固定5e6b326预算复验，不替换原r4结果。属于memory-rl-evidence-and-next-experiment.md中D1/D3的前置公开诊断，不是P2封存效果实验。

## 目标与可证伪假设

实测r4前两步B未读取memory；4条实际prompt已经包含完整工具调用示例，不能继续以缺示例解释。现stage.py对已存在index也写may be missing；共用common还包含组织记忆的writer指引。假设是reader角色与文件存在状态不够明确，影响小模型的执行选择。修正文案不保证成功，必须在同条件配对中检验。

## 实验

先使用固定core公开dev WS01/03/05各4题共12题；WS06另4题作无需memory负对照，共16题。每题仅采样1个真实A，不按A成败挑选或补采；该A通过现有准入后冻结其产物，每种reader提示各执行4个独立B。最多16次A与128次B，4次B是同一任务/记忆条件下的重复采样，不能算4个独立任务，也不是训练n4组。旧B与新B读取字节相同的bundle，使用独立session。A失败单列；不伪造B、不静默补成功A掩盖失败。固定基础模型、运行版本和采样参数；每个A/B独立session累计生成上限8192，单次请求上限4096，不能将两者或上下文窗口混称。诊断B分支不作为完整在线训练样本提交TQ。

旧条件使用原prompt；新条件仅改reader指引：明确它是恢复执行者、不写memory；对inventory中实际存在的index明确可读、先检查索引再按任务需要取证；index不存在时如实告知，不暗示隐藏事实或提供答案。不增加tool示例、不改writer目标、不改业务评分与输出合同。

该处理同时修改角色表述、存在性信息与检索指引，是一个预先固定的prompt修订包，不称单一机制的因果效应。若有收益，后续再按需要分拆消融；不从组合结果断言某一句话有效。

这不是“有没有记忆”的因果消融，也不是候选训练收益；只是条件于同一真实A产物的reader使用行为比较。B分支可重用安全的stage准备和执行接口，但必须有独立branch身份，不能冒充原A/B唯一链或复用其receipt。

## 架构与API合同

真实DSH writer → validate → frozen bundle及原SHA → 两个只读branch → 各自DSH reader → 原verifier与配对汇总。

诊断控制端绑定source head、model revision、任务ID、writer receipt、bundle SHA、branch ID、prompt revision、预算。禁止从模型输出选择prompt variant；不向模型暴露truth/controller fixture。模型唯一执行循环仍为DSH，Gateway采真实tokens。

配对成员标识固定为task_id/writer_session_id/variant/repetition；两variant交替顺序执行并记录采样配置，避免固定先后顺序与运行状态混淆。每branch保存fresh result/receipt/trace；相同输入bundle字节hash必须一致。两branch写不同outputs目录，模型可见路径使用中性等结构标识，不带old/new或优劣暗示；reader无权修改bundle或其他branch。业务错误与未完成作为结果保留；证据/版本错配中止该配对。不可将控制端报告字段当模型可见指令。

## 文件清单（已实现）

- 新 examples/dsh/capabilities/diagnose_core_reader.py：有界准备/执行/配对报告；复用既有operator和stage执行能力。
- examples/dsh/capabilities/work_state/stage.py：必要时提取reader准备的纯函数，旧默认输出逐字节不变；新branch API只给诊断入口使用。
- 新 reader_diagnostic_evidence.py / reader_diagnostic_runtime.py（同capabilities目录）：原verifier重算与真实Gateway执行入口。
- tests/uni_agent/examples/test_diagnose_core_reader.py、test_reader_diagnostic_evidence.py、test_reader_diagnostic_runtime.py、test_reader_diagnostic_launch.py，以及旧test_work_state_stage.py：配对、证据、隔离、启动和失败回归。
- docs/harbor-modal-integration/core-reader-role-diagnostic-runbook.md：固定命令、预算、结果判读及恢复方法。

## 验收

当前stage.py的validate_stage_execution会将eligible=false与评分不匹配一起抛错；本诊断不修改训练准入。必须依据原结果区分可信任务失败与证据损坏，A未通过准入时记录未形成配对且不执行B。冻结/reader准备当前耦合并写固定目录，不能直接调用两次；分支准备需复用不可变冻结包，并保持独立目录与权限。

CPU先验证旧prompt/默认行为不变，目录冲突拒绝，无truth泄漏，伪receipt与bundle篡改拒绝，branch不能越界，A失败没有伪B，n4不被部分成功替换。跑相关回归及全库Ruff双门。

GPU先1题成对canary，确认真实token/工具调用与不同输出隔离；再按预定16题执行。报告A成功/完成率、B的view尝试次数；实际读取/事实使用由原trace和输出另行核验、业务成功率、幻造事实、重复动作、生成token和失败原因；按task而非64个相关采样计算不确定性。16题为诊断规模，不足证明跨场景收益。

只有明确降低执行失败且无边界回归，才设计下一版联合RL课程。若无改善，保留负结果并转向工具能力/事实使用诊断，不进一步盲目加长提示。

## 报告分母与结论边界

报告全部16题的A终态、能形成配对的题数、每variant有效与失败B数；同时报告条件配对表现和全链可用率，不用剔除A失败后的成功率冒充端到端成功率。B失败保留为预定重复的结果，不补采成功替代。统计以task聚类，只有1个A/题，不能推断对不同writer样本的稳健性。若A普遍无法完成，则先报告writer瓶颈，不把缺少B结果解释成reader差。

实施批准已收到。诊断入口、CLI与CPU测试已实现；没有启动对应GPU实验，训练合同保持原样。操作入口见 [runbook](core-reader-role-diagnostic-runbook.md)。

主结果为两条件原业务成功率的task配对差，读取比例与格式合法率为诊断指标。先列逐题原结果及A可恢复事实覆盖，成功/失败分母固定；小样本不作显著泛化承诺。Canary若导致修改提示，原canary只作调试，不能混入固定版本正式比较。后续RL启动还需确认真实成功路径与奖励区分度，不能仅因读取次数增加就宣称可学习。
