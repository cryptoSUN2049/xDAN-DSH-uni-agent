# N0 准备器设计：固定课程与新运行身份

本批只实现CPU准备，不启动GPU。复用已有16/8生成器、4/2选择器和v2版本器；禁止复制旧venv、改评分器、修改旧目录。生成清单提供后续train/audit/delta/reload准确argv与预算，实际执行/自动串联留到下一验证批次，不能把计划步骤标为通过。

新增 `examples/dsh/ops/prepare_native_rebuild.py` 与 `tests/uni_agent/examples/test_prepare_native_rebuild.py`。输入：新checkout与预期完整commit、新venv、新runtime、新输出prepare目录、checkpoint根、唯一run名称、已通过r4 launch-manifest及外部SHA。基线DATA_ROOT/Parquet由原manifest定位并逐字节校验；原prompt根由旧PYTHONPATH第一项取得，不读取旧checkout源码。

输出：16/8→4/2-v1→4/2-v2课程、新train与reload launch-manifest、顺序计划与准备证据。模型路径可复用固定snapshot，必须另记录缓存复用；PYTHON_BIN/DSH_VENV/PATH/PYTHONPATH与全部输出路径改到新环境，不继承旧trace/result目录。训练保持r4预算两步/4train2eval/batch2/n4，独立reload保留4条train供数据加载器恢复；分别2700/1800秒。

业务等价：逐行比较旧新6条完整row；只允许prompt中旧checkout绝对fixture前缀替换为新checkout，metadata、fixture bytes/hash、奖励身份和scenario顺序不变。对应数据manifest与Parquet SHA需匹配。固定原DSH runtime d1a467…、v2 verifier bundle60f49…；不从候选数据自认身份。

失败规则：输出根/run根/checkpoint根必须新建、不接受symlink或checkout内输出；任何前置/hash/预算/等价失败即抛错，保留私有失败准备目录供诊断，但不写成功计划。每个CLI有CPU timeout。读取基线文件有大小/路径检查，新进程运行现有CLI，参数数组无shell。输出JSON用独占写入0600；顶层目录0700。

测试：实际三级准备器生成数据；证明6条逐字等价和运行根隔离；拒绝源manifest/Parquet篡改、业务变化、旧输出覆盖、错误runtime/commit、非法run名。检查生成train/reload argv与真实CLI对应，无模型/GPU调用。先失败测试，再最小实现，再Ruff和相关回归。
