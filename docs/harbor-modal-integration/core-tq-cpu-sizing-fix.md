# Core 课程 TransferQueue CPU 资源修复

真实根因（主线程观测）：当前 Ray 总 CPU 6、可用 5；SimpleStorage 默认 8 个 actor，每个申请 1 CPU，placement group 无法整体放置，GCS 保留 pending placement group，训练等待存储而未进入正常更新。

最小修复：仅 `work-state-memory-core-v1` 的准备器命令尾部固定 `transfer_queue.backend.SimpleStorage.num_data_storage_units=2`，保留 trainer、数据、奖励和 GPU 设置。`check()` 必须检查该显式值存在且最终有效值为 2，拒绝删除或后续 override。旧课程不添加配置，保留旧默认。无需修改上游 TQ 或伪报 Ray CPU 数量。

修改文件：`prepare_memory_training.py` 与 `test_prepare_memory_training.py`。TDD：真实 shell 输出经 Hydra compose 后 core 的单位数为 2；旧课程仍为原默认 8；删除或篡改配置被拒。现有准备器全量回归和 Ruff 双门通过后由主线程固定提交、以新 run 启动。CPU 配置验证不等价于训练消费/参数更新验收。

验证完成：两项删除/覆盖用例先观察未拒绝而失败；实现后完整准备器回归 94 项通过（55.39 秒），包含真实 shell → Hydra 合成的 core=2/旧课程=8 断言。两文件 Ruff check、format --check 及 git diff --check 均通过。主线程确认新 Pod CPU cgroup 配额为 6.8 核；旧 r2 已终止并保留证据，新运行使用 `core-train-r3`，不复用失败目录。
