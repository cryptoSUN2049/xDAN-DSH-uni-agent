# r4 checkpoint：三题独立评估补验

状态：2026-09-09 16:26:10 UTC+8启动，待真实评估验收。launch PID264372。无新训练、无奖励或准入规则修改。

- 新recipe SHA：726d1c07ce9436b04d4a9447159a5b88a1926fb0；GPU目录/workspace/rebuild/uni-agent-work-state-eval-r1。
- 母训练SHA：5b4b01b1d0ab656e960d3514d0a3630210913022；母step8：/workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_8。
- 新run：/root/runs/work-state-r4-reload-selected-r1；清单同名-data/manifest.json。launch内部执行完整check后才使用GPU。
- 显式选择：work-state-ws01-v1-s303、work-state-ws03-v1-s303、work-state-ws05-v1-s303；validation实际3题/3结构。完整任务定义仍12条，不删旧WS06失败。
- Linux既有venv实际回归74项通过/285.36秒，CUDA_VISIBLE_DEVICES为空；原证据/root/runs/work-state-eval-selection-cpu-r1/{result.json,pytest.log,junit.xml}。SSH断连后检查原result确认exit0，未重复运行。此前Mac导入超时不是完整通过记录。
- 固定原DSH0.1.3a2与VERL fef+结束原因补丁，不重复安装、不重训母模型。

验收：真实加载model/optimizer/RNG/scheduler、三题A/B原始回执与唯一消费、无训练更新、母checkpoint全部文件SHA不变。旧四题reload失败见[原报告](work-state-train-r4-reload-result.md)，准入含义见[说明](work-state-admission-semantics.md)。选择后的结果不得宣传成四题全部通过或模型能力提升。
