# 四例上下文 baseline 准备

`prepare_context_eval.py` 是独立薄接线，复用已固定的 context_tasks/context_verifier，
不修改 M1 的字段或评分规则，不启动 DSH、GPU 或训练。

```bash
python -m examples.dsh.capabilities.prepare_context_eval \
  --repository-root "$TASK_REPO" \
  --output-dir "$CONTEXT_PREPARATION" \
  --run-root "$CONTEXT_RUN" \
  --eval-id context-baseline-r1 \
  --runtime-executable "$DSH_RUNTIME_EXE" \
  --environment-digest "$DSH_RUNTIME_SHA256" \
  --runner-python "$DSH_PYTHON"
```

变量由本次固定部署填写；digest 使用 sha256: 前缀。选定 Python 必须解析同一个 runtime，
SDK/runtime 包版本都为 0.1.3a2。准备目录及独立运行目录都必须不存在，且不能相互包含。
仅创建准备目录；使用固定 checkout 执行此模块，准备时源码所在 checkout 与传入 root 必须相同。

输出：

- eval.parquet：4 个实例，`prompt` / `extra_info.tools_kwargs.task.metadata`，split=test。
- task.yaml：sdk-minimal，空 patches，4096 总输出预算/1024 每轮；context 独立 verifier 身份。
- cases/：原固定两族四例的合同和 source 文件。
- preparation-manifest.json：源文件及所有产物 hash、runtime 路径/版本/hash、独立执行目录、
  inference_arguments、所需环境。它不是已运行的验收报告。

主线启动器读取 `inference_arguments`，传给
`python -m examples.inference.parallel_infer_verl`，并明确追加本次锁定的 `--model-path`
与 GPU/engine 参数。运行前创建独立 run root；从 repo root 使用指定 Python 启动，
应用 manifest 的 DSH_RUNTIME_MODE/PYTHONPATH。不得直接使用默认多卡参数部署单卡机器。

参数包含 `--dsh-strict-audit --require-result --n 1 --limit 4` 及独立 trace/result/log/
inference-evidence 路径。每次复跑必须使用新 run root（重新准备一个评估包）；保留旧证据。
主线还应先比对 source/runtime/产物 hash、确认 GPU 占用，并锁定实际模型版本。

严格 runner 开启 require_finished_episode、require_verifier_reward、轨迹审计。
`DshArchitectureTask._task_result` 将可信 score.reward 写为 verifier_reward 并生成回执，
与配置和每行 metadata 的 `dsh-context-file-evidence` / version=1 / bundle 身份一致。
这里没有自行伪造 verifier_reward、Gateway token 或训练准入。

5 项新准备器测试、15 项 context 评分测试及严格 inference 回归共 60 项通过。
其中直接调用真实 parser、TaskConfigResolver.from_file 与 init_config 验证实际接线；
runtime package 探针在 CPU 测试中为 fixture，不代表远端部署已验收。

范围始终是 file-evidence-only，context_switch_verified=false。四例没有独立训练 split，
不是大规模训练数据，也不证明泛化、真实 context 切换或跨会话记忆能力。
