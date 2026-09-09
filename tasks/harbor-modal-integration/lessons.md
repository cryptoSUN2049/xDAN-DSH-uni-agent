
## 有价值任务持续推进

- 用户要求持续推动G1时，概念解释与任务分类是主线中的沟通，不能替代真实实现、运行与验收。
- 新奖励器必须区分可信任务失败（0奖励、可准入）和不可信证据（拒绝准入）；只保留成功样本会导致RL失去负例。
- Runtime工作目录HEAD不能证明已有构建产物的源码身份；按发布exe/wheel摘要复验。
- 新launcher环境变量必须对照底座实际读取名，LOW_VRAM不叫LOW_VRAM_MODE。

- 当前tokenizers词表大小查询并非廉价：GPU CPU实测1000次get_vocab_size耗时18.004秒。不要在逐token校验循环中调用len(tokenizer)；按sample取一次。修后84条真实tokenizer检查4.65秒通过，所有prefix/mask条件保持。

- SFT聚合loss不能代替关键动作成功率：batchsize1下native dev指标对decision等权平均，定义步骤只占每case的1/14。本轮mask/监督token分母正确，但低平均loss仍伴随非法JSON与错误注册API。后续单列关键动作与自主完整任务结果。
- PEFT加载已有adapter会将BF16 adapter升为FP32。比较checkpoint时记录dtype变化，先做无损规范再核数值delta；不能把cast本身计作学习，也不要放松通用比较器的严格dtype合同。
- Harbor可复部署必须固定agent与独立verifier两枚实际镜像；只固定verifier Dockerfile父镜像不等于运行固定发布物。

## 2026-09-09 原生多轨迹评估分数语义

- 固定 VERL 的 training rollout dump 保留阶段原分数，validation dump 为同一 session 每条轨迹写入最后阶段分数。不能用同一逐阶段比较规则审计两种输出。
- 原始 A/B receipt 仍须各自严格重评分；validation 行另与已验证同链终态 B 奖励比较。不得覆盖原回执或放宽轨迹准入。
- 测试必须执行实际 validation dump 路径；用 training `_log_rollout_data` 模拟 validation 会掩盖本次错误。
- 修复离线审计器时，保留旧失败报告，以新审计 SHA 复核原运行，不能改母实验源码身份或要求无意义重训。

## RSI 实测：合法失败、摘要语义与初始化耗时

- H0 r1 两题均合法完成且reward0：inspection为父策略拒绝；文件题成功读取但value误写为整行。比较时把权限限制与模型输出错误分开，不能将所有零分归于Harness。
- runtime-binding中的receipt_sha256是文件字节SHA，而trajectory/proposal proof中的receipt_sha256是canonical receipt身份。字段同名不能据此强行判定相等；必须核各生产函数定义及原绑定链。
- H0监督314.622秒，任务生成51.7秒；P监督265.645秒，任务生成49.7秒。Ray/worker启动、模型加载、JIT属于不同阶段。CPU actor的CUDA runtime警告不代表GPU worker不可用，必须结合真实GPU内存、CUDA graph及任务回执判断。
- SSH banner观察超时不代表作业停止。本次重试确认原PID继续运行并已加载约30GB显存，未重启或重装。

## 工程验收不能替代充分训练

- 用户再次追问“只是简单跑，是否训练不充分”：必须明确区分少量任务的链路验证与能力学习。短课程8步/6独立任务/2非零梯度步不构成充分训练；H0/P/H1固定权重评估不能算训练量。
- 工程底座已证明后，不无限重复简单验收或只扩展控制端检查。每个后续实验记录独立任务族/实例、实际消费、有效更新步、奖励分布、学习曲线与独立评估；扩大覆盖和难度后按结果决定训练量，不把重复采样计成新增任务或盲目加步数。

## 误发需求不改变训练主线

用户确认聊天面板讨论来自其他会话：停止面板实现，已有设计仅为未实施草稿，不计入训练 goal；恢复固定脚本重复训练、有效更新及独立 reload 验收。

## 记忆目标不能收窄为文件操作

用户澄清：目标包括跨任务场景的专家级记忆/context管理决策，而非仅写handoff/index。方案必须覆盖何时保存、保存什么、证据与假设分离、选择性检索、冲突更新、真实offload/compact、克制与停止。当前小配置课只是起点，未实现机制不追认。A延迟奖励0不是A记忆质量0。
