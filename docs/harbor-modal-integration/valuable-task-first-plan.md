# 下一批：真实 DSH 能力任务优先

用户要求：必须跑有价值的任务验证流程；全异步、Modal和扩容留待性能阶段。

## 已确认的边界

- m2-file-write是连接诊断任务。r6五次完成全reward1，step1优化器计数推进但动量全零，后评估超时；不再重复堆步数。
- trim/normalize是字符串处理，不能称作记忆或上下文管理。
- v3-live已存在真实Cordis调用和独立verifier，但原prompt提供详细解法，旧专用启动器还带旧pin。不能原封不动当独立能力证明或新版在线RL recipe。

## 第一批：DSH架构技能基线（先eval，后决定训练）

1. 运行时能力发现：根据当前runtime的真实inventory识别可用Tool provider，查询所需能力并输出与观察一致的结果。verifier读取真实工具调用及结果，不采信模型自述。
2. 依赖故障恢复：在受控场景中触发缺失服务依赖，查看真实诊断，修复同一Plugin的Package，实际执行目标工具，最后stop/undefine并验证资源清理。不能只提交修复建议文本。

复用现有v3-live的runtime-grounding/diagnostic-recovery素材和verifier，去掉prompt中的逐步调用答案与完整修复代码；明确这是受控DSH技能任务，不是生产故障演练或记忆任务。原指导型smoke保留为对照。执行前检查verifier是否接受这种任务表述、新版runtime API和预算兼容。

文件计划：新增examples/dsh中的独立capability-eval数据准备入口及CPU测试；不修改原v3 smoke样本或放松轨迹校验。输出新的私有manifest/Parquet/config，pin当前SDK/runtime及verifier摘要；用现有单卡launcher做VAL_ONLY，严格记录真实Gateway token、receipt和失败分类。

验收：原始任务与答案不混淆；新task身份、运行和输出可追踪；至少各一条真实执行及新鲜评分；基础设施错误单列，不当普通0分；先看成功率和失败动作，再决定SFT示范/在线RL，不为非零梯度人为修改奖励。

## 第二批：记忆与上下文（独立能力合同）

- 上下文：保留问题相关的关键事实、权限和未完成目标，经历明确的上下文变化后完成后续任务；不得以压缩token数为成功指标。
- 记忆：A会话写入事实，B新会话只经授权检索恢复并完成任务，使用事实正确率和无记忆对照验证，不得把A全部对话直接塞给B。
- ContextPilot现有素材需审计实际运行依赖；固定b236 runtime未包含的能力不能静默假定已安装。此阶段新增集成设计单列，不阻塞第一批DSH真实技能基线。

## 数据与学习方法

首轮仅baseline eval；表现已满分的题不继续重复RL。弱项有可靠示范时先SFT，再用有差异的可验证奖励做RL。train/holdout独立实例与输入，所有来源/版本/预算留档。G1工程验收与效果/泛化结论分别报告。

## 审计后的执行修正

- 先仅执行runtime-grounding基线：指定Tool能力查询目标，prompt不提供工具调用名、参数示例或真实结果。属于运行时查询技能，不宣称开放式自主发现。
- diagnostic-recovery旧projector未严格绑定事件顺序、同一Plugin成功更新、最终清理；暂停纳入训练，须补强独立验证后再跑。
- 原v3 loader要求八类完整registry，准备入口先完整验证再选定任务，不修改原registry合同。
