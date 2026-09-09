# 独立评估任务选择：最小工程补验

2026-09-09。r4母训练8/8与最终消费已通过；独立reload实际恢复step8，但WS06 writer请求只读写入后不准入，严格val在汇总前退出。当前保持任务/verifier/权限/VERL身份不变，补充仅val/reload可用的显式任务子集，隔离失败与消费落盘；不重跑训练。

## 目标与路径

固定母checkpoint → 新准备器版本 → 明确选择的原始dev task IDs → 原DSH/Uni-Agent/VERL严格评估 → 独立run原始结果。完整task manifest仍是原12条映射，原任务事实与真值不改，只过滤validation.parquet并绑定选择清单。默认仍四dev；训练禁止任务筛选。旧四题reload失败完整保留，不能追认成功。

## 文件和合同

- examples/dsh/capabilities/prepare_memory_training.py：可选evaluation_task_ids，CLI重复--evaluation-task-id。
- tests/uni_agent/examples/test_prepare_memory_training.py：模式限制、默认行为、单/多项、顺序/实际parquet、清单篡改与母谱系。
- work-state-rl-runbook.md：手动命令与多run结果边界。

只允许非空、无重复、已知validation IDs。选择文件记录原完整任务清单SHA、requested/resolved IDs与顺序；所有文件进入原manifest摘要。check对照canonical任务定义重建预期选择与实际parquet（metadata/UID/行数/顺序），VAL_MAX_SAMPLES匹配子集。train/未知/训练ID/重复/空选择拒绝。mode=val/reload仍严格，不改reward、eligible或TQ；独立母SHA与当前recipeSHA分别记录，母runtime/VERL/模型/checkpoint绑定不放宽。

## 测试与执行

先RED选择测试，再实现和完整recipe/audit回归。Ruff双门与review后commit/push；GPU新checkout固定新SHA，母CK只读。优先三条原合法dev为一组补验；如有新失败，继续缩为单任务独立run，原失败不删除。旧WS06的真实拒绝结果仍列于总表，不能以筛选后的分母宣传能力提升。需要统一新一轮四题结果时再对WS06单题补验，不将阶段性补验伪装成完整benchmark。

第一阶段只确认可复现的加载、真实执行、实际消费与结果记录。准入策略是否允许环境已拦截且无副作用的错误动作作为合法负例，是另一个训练合同设计问题，本次选择器不暗中修改它。

## 候选检查点

实现与选择/篡改/跨母SHA回归已落盘。两次本机全recipe测试分别在已通过21/28项后遇到既有check导入子进程60秒超时，未见选择器断言失败；本机其他进程资源负载较高，未终止它们。Ruff双门与diff检查通过。代码先作为候选提交，经GitHub部署新Linux checkout，在已有venv用CUDA_VISIBLE_DEVICES空值完成CPU回归，通过后才启动补验；本段不宣称完整回归已通过。
