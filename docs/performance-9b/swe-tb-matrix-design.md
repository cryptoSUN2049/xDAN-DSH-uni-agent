# TB2.1 / SWE Verified 三模型评测队列

用户已批准跨 benchmark 执行；实现独立 driver，不改变旧 checkpoint 队列。

接口：`python examples/harbor_opd_rl/eval_benchmark_matrix.py MANIFEST [--benchmark LABEL] [--probe-only]`。
Manifest 必填 `output,gpu,python,env,datasets,versions`；可选 `stop_file,gpu_wait_seconds`。
Datasets 顺序执行，每项 `label,data,sha256,tasks,n,task_config,task_config_sha256,probe_ids`；probe_ids 必须为3个预先固定完整 instance_id。
Versions 固定顺序 base/opd12/rl60，项 `label,checkpoint,run`，base 的 checkpoint 为空，run 可指向 pipe-s2-opd 以读取相同训练侧参数。

每个 benchmark：校验 parquet/config 哈希及唯一任务身份 → 各模型固定3题×1冒烟 → 各模型全量n次 → 相对base配对报告。
冒烟仅以加载和基础设施完整性验收，0分也可通过。每输出basename为前置phase加hash短名，避免Ray临时目录前24字符碰撞。
所有原始评测仅一次；infra缺失可调用原补测器一次，不重复已有0分；base补测也支持：要求空恢复路径、固定model_path并记录config哈希，不尝试读取actor；绝不重跑全量替代。
完整性需验证receipt、精确任务身份、checkpoint和配置绑定。所有已存在不完整尝试留证据，恢复不覆盖、不重启；已完成可复用。
单输出目录独立flock；GPU空闲等待有期限；stop_file在每次新评测/补测前检查，存在则安全退出，已进行的评测不强杀。

测试：固定身份/哈希、base与checkpoint加载绑定、完整零分通过、缺失拒绝、短目录唯一、全版本探针先于全量、恢复不重复、stopfile阻止启动。真实部署/额度/数据去污染由主线程审核。

`--probe-only` 只执行选定benchmark三模型探针，状态写入 `status-<label>-probe.json`，不进入full；相同manifest正常启动时复用相同短目录的完整探针，正常状态文件无 `-probe` 后缀。费用额度由外部stop_file控制，本开关不代表全量授权。
