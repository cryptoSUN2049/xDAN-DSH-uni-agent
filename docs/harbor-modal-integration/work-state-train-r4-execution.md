# Work-state train r4：工程流程优先

2026-09-09 14:18:35 UTC+8 启动。状态：已启动，未验收通过。

- 集成源码：`5b4b01b1d0ab656e960d3514d0a3630210913022`，已推送GitHub；GPU独立目录`/workspace/rebuild/uni-agent-work-state-r4`。
- 固定DSH SDK/runtime 0.1.3a2、二进制SHA256 `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`；实际发行包名为deepseek-harness-sdk及deepseek-harness-runtime-bin。沿用已验收venv，没有重新安装。
- VERL fefb080262e1c015a0ea05f958822a6a512dc795 + preserve-finish-reason-v1显式补丁，apply/verify通过。
- 8独立train输入、4公开dev输入，各4种结构；本轮train不内联执行dev。8steps、n4、save4/8、val_before_train=False、test_freq=0，7200秒监督截止。
- 修复回归：主线程27 recipe tests，独立recipe+consumption audit共54项通过（不相加）；Ruff check及format355文件通过。
- 预检：`/root/runs/work-state-train-r4-preflight.json`，2026-09-09T06:17:35.229020+00:00。
- launch PID242996，记录`/root/runs/work-state-train-r4-launch.json`；日志同名`.log`。
- run `/root/runs/work-state-train-r4`；清单`/root/runs/work-state-train-r4-data/manifest.json`；训练日志`<run>/supervision/train.log`。
- checkpoint `/workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_N`。

## 验收顺序

1. 实际训练步数、原始奖励/轨迹、完整组唯一消费与拒绝/补采覆盖；不能将重复采样计为新增任务。
2. step4/8保存完整、版本和谱系核验，母运行正常结束后独立reload与fresh评估；合法零梯度不阻挡加载验收。
3. 单独核实任务优势、有限非零梯度、参数/optimizer变化；不能用AdamW衰减或历史动量证明新学习。
4. 任务成绩与能力提升另作对照。旧r3 failed证据不改变，训练禁内联val不等于取消评估或放宽准入。

操作顺序见[人工复跑指南](work-state-rl-runbook.md)，调度修复见[设计与失败边界](work-state-training-evaluation-separation.md)。PID存在不证明模型加载，退出码0不证明有效学习。本文件为启动检查点，最终结果必须由原始证据另行更新。
