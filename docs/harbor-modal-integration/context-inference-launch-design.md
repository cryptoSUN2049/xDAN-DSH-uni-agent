# Context v2：清单驱动 inference 启动

设计/实施范围：已批准的原生 v3 工程集成。解决 r3 手写 `PYTHONPATH=.:verl` 在 verifier cwd=data 时失效；r4 已用绝对路径恢复。只新增 launcher 与测试，不改评分、不操作当前 GPU。

链路：已准备 manifest → 摘要/路径/配置检查 → 在 task workdir 用所选 Python 导入 verifier 并核闭包/runtime → 原子创建新 run root → 记录 argv/关键环境/输入/source/model文件摘要 → 既有 owned-process-group supervisor → 原生 parallel_infer_verl → 结果记录。

- 输入 `--manifest`、`--model-path`、可选单卡并发/显存/window/wall参数；不接任意 shell 或任意尾 argv。
- 使用 manifest.environment 的绝对 PYTHONPATH，要求恰为本 checkout 与本 checkout/verl；覆盖调用者相对 PYTHONPATH。在 data cwd 预检绝对导入路径与闭包摘要。
- 移除继承的 RAY_ADDRESS、PYTHONHOME、PYTORCH_CUDA_ALLOC_CONF；RAY_TMPDIR 强制为新run绝对路径摘要派生的 `/tmp/dsh-context-<12hex>`，已存在则拒绝，避免接入共享Ray及过长Unix socket路径。实际PATH/RAY_TMPDIR等关键环境写入启动记录。
- 只读记录集成仓库实际 HEAD/branch 与 VERL 实际 HEAD/branch（detached记null），部署锁 integration 声明另列；不fetch、不升级、不改repo。
- VERL实际HEAD必须等于已校验部署锁的 `integration.verl_revision`，不一致在导入/启动前硬拒绝。集成仓库允许当前新功能提交，只记录实际HEAD，不强制等于历史M1 `code_revision`。模型revision仍是部署声明＋本地字节测量，不是外网Hub版本证明。
- 实际复核 manifest.sources 与 files 的每份字节摘要，路径不得逃出对应根；校验 task.yaml、parquet、fixture 与 runtime 绑定，verifier命令只能是本v2模块。清单引用文件缺失/篡改/旧代码失败时不创建 run。
- manifest.inference_arguments 必须与其已核文件和run路径形成的固定参数完全一致；所有输出在新run里，禁止重复或覆盖；不接受任意命令注入。
- model目录只允许已知Qwen3-4B形状，实际记录配置/tokenizer/权重文件SHA256。既有student revision来自部署锁，文件摘要是本次测量，不虚称重新从Hub验证了revision。
- 复用现有 `deployment.services.harbor_training_supervisor.supervise` 的新进程组与墙钟终止；本地任务无需Harbor controller，health回调为空。记录此处仅证明owned进程组终止，不自动宣称所有独立Ray后台资源均清理。
- 准备器不再手工写remote启动片段；一条module命令启动。默认4dev，strict n1；该入口不做训练。

文件：新增 `examples/dsh/capabilities/launch_context_inference.py`；新增对应CPU测试；更新context runbook。测试先RED：跨cwd导入失败/摘要错误阻止启动，篡改输入/source、输出逃逸/旧run、模型形状错误；成功路径断言固定argv/env和有界supervisor接线。无需GPU证明这些边界。

实施结果：新增launcher12项CPU测试通过，连同context v1/v2共95 passed；Ruff check/format通过。包含实际启动CPU sleep子进程并以owned supervisor墙钟终止的验证，以及继承Ray/allocator环境剥离、旧Ray目录拒绝与VERL pin负例；未启动GPU、未变更远程checkout。操作文档已改用一个module命令，禁止先建run目录。
