# 三题独立reload selected-r1：加载成功，WS05未完成导致评估失败

源码 `726d1c07ce9436b04d4a9447159a5b88a1926fb0`，run `/root/runs/work-state-r4-reload-selected-r1`，supervisor child264469，exit1，685.015秒。选择器清单明确只请求WS01/WS03/WS05的variant1 seed303三题，没有请求WS06。原四题reload的WS06失败保留，不因本次筛选而改变。

[机器可读摘要](selected-r1-result.json)保存实际清单、加载日志、消费审计、失败回执、母checkpoint哈希与74项Linux测试证据。全过程仅CPU只读审计；没有操作GPU、修改源码或补造消费记录。

## 加载与母checkpoint保护已通过

- 08:31:59.721 UTC：Resuming母 `work-state-train-r4/global_step_8`，设置global step8。
- 08:32:34.821：实际Loaded model。
- 08:32:35.295：实际Loaded optimizer。
- 08:32:35.314/.315：从extra_state分别Loaded rng/lr_scheduler。
- 对照准备时checkpoint_origin逐一重算全部11份母文件SHA、大小与文件集合，全部不变。未出现训练消费、新checkpoint文件或actor更新metrics。

## 失败原因不是选择器漏过滤

`work-state-ws05-v1-s303` writer A，chain `memory-8b3761efa586466c857100a89d0fae27`：实际78次工具调用（72 view、6 create），创建占位交接文件后反复读取。原trace末事件seq400明确`turn/end → max-tokens`，agent-result同样报告max-tokens；原回执finished=false、eligible=false。

严格框架在global_steps8、partition=val抛出 `TrajectoryAuditError:trajectory 0: reward_info must declare finished=true`。该A没有进入B，未通过准入，未写入最终消费。这里的max-tokens来自原DSH事件与结果，不由调用数量臆测。

## 消费与结果边界

WS01/WS03两条A/B链正常完成并提交，阶段均fresh/finished/eligible，A/B奖励均0，实际policy版本8、checkpoint identity与准备时母checkpoint-origin绑定一致。但第三题失败中止整批validation，未写出validation JSONL。

独立一次 `audit_memory_training` 原结果：2groups、0 consumed_groups、0 consumed_rows；unknown/duplicate/overlap/errors均为空，整体passed=false、consumption_verified=false、run_completed=false。不是原计划3组/6行消费通过，不补造缺失dump。远端原审计保存在 `final-audit-r1/memory-consumption-audit.json`，母哈希及失败摘要分别记录。

## 选择器CPU证据

`/root/runs/work-state-eval-selection-cpu-r1/` 的result.json确认同源码exit0；原junit.xml独立解析74tests、0failures、0errors、0skipped。pytest.log/junit/result三文件SHA均写入本报告JSON。这证明CPU参数与选择合同测试通过，不能替代真实学生长循环的完成能力。

本次确认状态可独立加载且母权重未被修改；三题新鲜评估的完整消费仍未通过，也没有任务效果或参数学习提升。后续若用更小的显式任务集合验收工程reload，必须保留选择范围和旧失败，不能称原四题全部通过。
