# MIG GPU 准入：区分权限不可见与实际占用

真实触发：新Pod的nvidia-smi compute PID查询返回`[Insufficient Permissions]`，旧launch把任意非空输出当实际PID，阻止空闲MIG启动。主线程已按唯一MIG UUID实查NVML compute/graphics均空，memory可读。

最小修复：prepare模块新增check_gpu_available。正常空输出保持通过；任何数值PID/未知非空输出仍拒绝。只有输出全部为明确权限标记时，读取nvidia-smi -L，要求唯一MIG UUID；NVML按该UUID取handle并回读UUID一致，compute/graphics进程均空、内存统计合法可读才能通过。异常、模糊实例、实际进程全部拒绝，不修改宿主MIG或权限，不用母卡PID查询失败推断MIG空闲。

helper返回检查方法/UUID/内存摘要，launch在独立run写gpu-admission.json作为准入时刻快照；不是GPU租约，也不保证后来无其他作业。旧memory-launch-plan保持原manifest。

修改仅prepare_memory_training.py及对应测试。TDD覆盖正常空、数值PID、权限+唯一空闲MIG、compute/graphics占用、UUID错配、NVML错误/内存不可读、多MIG/无MIG拒绝。无需运行GPU计算验证本逻辑，真实NVML只读证据由主线程保存。

验证：11项新用例先观察缺少helper而失败，再全部通过；prepare完整回归90项通过（59.17秒）。随后补充混合PID/权限标记拒绝、查询超时拒绝及launch证据落盘断言，14项针对性用例通过（78项未重跑）；两文件Ruff check/format --check通过。正常路径及旧manifest/课程约束均未变更。

主线程真实只读证据位于`/workspace/reports/core-newpod-startup-r1`：MIG总内存50868518912、已用133758976、空闲50734759936字节，compute/graphics均为空。修复后用新run `core-train-r2`，失败r1目录保留。本CPU修复完成不代表新训练或参数更新已经完成。
