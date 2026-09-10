# Core 课程 TransferQueue CPU 资源修复

真实根因（主线程观测）：当前 Ray 总 CPU 6、可用 5；SimpleStorage 默认 8 个 actor，每个申请 1 CPU，placement group 无法整体放置，GCS 保留 pending placement group，训练等待存储而未进入正常更新。

当前最小修复：仅 `work-state-memory-core-v1` 的准备器命令尾部固定 `transfer_queue.backend.SimpleStorage.num_data_storage_units=1`，保留 trainer、数据、奖励和 GPU 设置。`check()` 必须检查该显式值存在且最终有效值为 1，拒绝删除或后续 override（包括旧值 2）。旧课程不添加配置，保留旧默认。无需修改上游 TQ 或伪报 Ray CPU 数量。

修改文件：`prepare_memory_training.py` 与 `test_prepare_memory_training.py`。TDD：真实 shell 输出经 Hydra compose 后 core 的单位数为 1；旧课程仍为原默认 8；删除或篡改配置被拒。现有准备器全量回归和 Ruff 双门通过后由主线程固定提交、以新 run 启动。CPU 配置验证不等价于训练消费/参数更新验收。

验证完成：两项删除/覆盖用例先观察未拒绝而失败；实现后完整准备器回归 94 项通过（55.39 秒），包含真实 shell → Hydra 合成的 core=2/旧课程=8 断言。两文件 Ruff check、format --check 及 git diff --check 均通过。主线程确认新 Pod CPU cgroup 配额为 6.8 核；旧 r2 已终止并保留证据，新运行使用 `core-train-r3`，不复用失败目录。

第二层真实阻塞：r3 虽然完成 storage 创建，但 TQ Controller 占 1 CPU、storage PG 占 2、训练 actor PG 占 3，合计 6。外部 DSH runner 还需要 1 CPU，因而等待；TaskRunner 运行占用为 0，不能把 Controller 的占用归给 TaskRunner。改为 storage=1 后预算为 `Controller 1 + actor PG 3 + storage PG 1 + 外部 runner 1 = 6`，允许单个任务串行前进。

源码边界：`uni_agent/framework/framework.py:129` 的 runner 是默认 1 CPU 的 Ray task，`:1015` 提交后等待返回；该 task 内使用 `asyncio.run` 执行 runner。`examples/dsh/capabilities/work_state/stage.py:107` 固定 local sandbox，`uni_agent/sandbox/local.py:50` 用 asyncio 子进程启动 DSH/verifier，没有再次申请 Ray CPU 的嵌套任务。Gateway 使用既有 actor；runner 返回后父框架才进行 finalize/奖励调用（`framework.py:1053`、`:1378`），没有持有 runner CPU 等新 Ray task 的嵌套阻塞。这里解决最小运行容量，不宣称提升并行吞吐；是否仍有其他资源等待由下一轮真实运行验收。

修订验证：旧值 2 的篡改测试先观察未拒绝而失败；改为 1 后完整准备器 95 项通过（66.42 秒），实际 Hydra 值 core=1/旧课程=8，删除、覆盖 8、回退 2 全部拒绝；Ruff 双检查与 diff --check 通过。`task_runner.py:345` 直接 await task_instance.run，无嵌套 Ray task。失败 r3 保留，由主线程使用新 r4 验证真实运行。
