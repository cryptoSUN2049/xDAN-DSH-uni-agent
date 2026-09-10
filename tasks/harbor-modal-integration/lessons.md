
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

## 换Pod恢复：解释器与MIG（2026-09-10）

新Pod220.120:13918保留workspace，但旧venv/bin/python指向容器/usr/local/bin/python已缺失；系统Python3.11不能替代旧3.12.3。固定uv0.9.0与CPython3.12.3装到持久盘，仅补symlink仍因pyvenv.cfg home旧路径找不到encodings；保留原cfg备份后修home到持久解释器bin才成功。实际torch2.11cu130前后向finite、DSH0.1.3a2通过。nvidia-smi整卡统计N/A不代表CUDA坏；本次是MIG2g48gb、CUDA实测50868518912bytes。新/root/runs不存在，创建父目录，不提前创建正式run目录。新Git fetch认证仍可用。以上实际恢复不等于训练完成。

## TQ初始化停滞不是GPU问题

2026-09-10新Pod仅Ray CPU6/可用5，固定VERL的SimpleStorage默认8个CPU1 placement槽。TQ无超时等待pg.ready，Controller已就绪却没有storage/model worker。普通raylet待任务数0不能排除GCS pending placement group；必须核两种队列。原r2无首步，保存GCS/日志后仅SIGTERM owned PG11802，监督exit-15/1120.028s，所有相关进程退出。generic reason=training-exited不是自然训练成功，结合operator-stop解释。新core显式2存储单元，保留其他训练合同。

## CPU预算必须覆盖任务执行，不只服务启动

2026-09-10 core-r3将TQ从8降2只解决storage placement；实际CPU6被Controller1+Storage2+actor PG3耗尽。模型PG内部空闲2CPU不能供组外runner使用；裸ray.remote任务默认1CPU，首writer输入已生成也不代表DSH执行。应预算Controller1+Storage1+actorPG3+串行runner1=6，并核下游local子进程无额外Ray任务需求。根保存debug_state/GCS/train日志后仅SIGTERM owned PG15980；无首步/梯度/checkpoint，不能把模型加载计为任务链路通过。后续在首个DSH子进程和完成组出现之前，不宣布CPU问题整体解决。

## 模型重复工具错误须核实际token；worker raise不等于训练退出

2026-09-10 core-r4首writer重复create modules.md；实际Gateway NPZ里保留前一assistant调用、mask0的File already exists反馈以及随后mask1的再次create，执行session.py哈希匹配。此例是模型未利用反馈，不能仅凭重复行为断言SDK丢上下文。详见docs/harbor-modal-integration/core-r4-tool-feedback-audit.md。同组一个sibling失败会整组拒绝并写TQ failure；train入口fire-and-forget，worker最后RuntimeError不直接传播成trainer退出。必须沿future消费链及ReplayBuffer refill核查；本轮05:49:07实际拒首组后自动创建第5/6链，作业继续。拒绝组不计有效消费，也不以持续采样冒充已更新参数。
