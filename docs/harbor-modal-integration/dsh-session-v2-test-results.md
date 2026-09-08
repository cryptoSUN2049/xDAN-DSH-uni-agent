# DSH Session v2 聚焦兼容性测试结果

日期：2026-09-08，Asia/Singapore。结论：最新 DSH 的 **388 项源码测试和 1 项真实 built worker 测试通过**；完整 Uni-Agent worktree 的 **84 项适配/审计回归通过**。未修改 DSH 源码、依赖、运行 pin，也未运行模型或 GPU 训练。测试缓存禁用，结果存于 `/private/tmp`。

## 版本与证据范围

- DSH：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp`，HEAD `b2369692ea530007075ebcd18d39fdba0bbd3982`；测试前后 `git status --porcelain=v1` 均为空，HEAD 未变。
- Uni-Agent：当前 `harbor-modal-integration` worktree，HEAD `bf742c960ae9d35126c125e107e26b151e994074`，另有本轮未提交 Harbor worker/executor 修改。本结果对应这一工作区快照，不能只用 HEAD 复现新增测试。
- Node `v22.22.0`，pnpm `11.7.0`，Vitest `4.1.8`；Python 使用 `/private/tmp/uni-agent-cpu-20260907`，Harbor `0.16.1` 仅作为补充依赖。
- 既有 `tasks/sync-dsh-architecture/verification.json` 记录构建、类型检查和 converter 18 项通过，涉及 checkpoint `ce4ffc5530` / reviewedCode `a3a90039...`。这是之前的交接证据；本轮独立复跑下列聚焦测试，不重跑全仓构建。
- 当前运行 pin 仍是 `7840bced35ee07ebefbdce0106b56dbc00bdc3ef`。既有训练/update/reload 证据继续只属于该基线。

## 最新 DSH 源码：8 文件、388 项，exit 0

在 DSH 根目录实际执行：

```sh
pnpm exec vitest run \
  packages/session/session-format-v0-to-v1/tests/migration.spec.ts \
  packages/session/session-format-v1-to-v2/tests/migration.spec.ts \
  packages/session/session-format-v1-to-v2/tests/validation.spec.ts \
  packages/session/session-format-catalog/tests/current.spec.ts \
  packages/session/session-persistence-jsonl/tests/jsonl.spec.ts \
  packages/session/session-persistence-jsonl/tests/generation.spec.ts \
  packages/core/session/tests/seq-ranges.spec.ts \
  scripts/trace-training/converter.spec.ts \
  --configLoader runner --no-cache --maxWorkers 2 \
  --reporter=default --reporter=json \
  --outputFile.json=/private/tmp/dsh-session-v2-vitest-20260908.json \
  > /private/tmp/dsh-session-v2-vitest-20260908.log 2>&1
```

| 测试文件 | 通过数 | 直接覆盖 |
| --- | ---: | --- |
| session-format-v0-to-v1 / migration | 10 | 首段相邻迁移与旧事件语义 |
| session-format-v1-to-v2 / migration | 35 | embedded stream、失败/重试 attempt、继承切点、引用与 provenance 拒绝 |
| session-format-v1-to-v2 / validation | 73 | v2 header、事件/stream 与关系验证 |
| session-format-catalog / current | 2 | 当前格式 catalog 解码与验证 |
| session-persistence-jsonl / jsonl | 171 | 真实临时文件、write/read handle、flush/close、重新打开及历史版本选择 |
| session-persistence-jsonl / generation | 70 | v2 successor 发布、历史原件不变、竞争/损坏/写入失败处理 |
| core/session / seq-ranges | 9 | inclusive seq 与 exclusive offset 的范围语义 |
| trace-training / converter | 18 | 真实转换器读取 v0/v2 fixture，重建请求/响应、attempt 与原始字节来源 |

总计 388 passed，0 failed，0 pending，6.72 秒。JSONL 测试实际调用 `runPersistenceContract` 与 `runLiveWritePathContract`；包含“flush 后新实例可读取”“close 后第二 write handle 继续写入”“reopen 追加同一 artifact”“v0/v1/v2 同目录选择正确代际”。这些是实际 Session/文件实现测试；部分失败与竞争分支使用故障注入，不是生产崩溃或断电演练。

## 真实构建产物：1 项，exit 0

在 DSH 根目录执行现有、无需模型的 built worker 测试：

```sh
pnpm exec vitest run --config vitest.e2e.config.ts \
  packages/session/session-persistence-jsonl/tests/built-migration-worker.e2e.ts \
  --configLoader runner --no-cache --maxWorkers 1 \
  --reporter=default --reporter=json \
  --outputFile.json=/private/tmp/dsh-session-v2-built-worker-20260908.json \
  > /private/tmp/dsh-session-v2-built-worker-20260908.log 2>&1
```

结果 1 passed、0 skipped，0.437 秒。测试通过 plain Node 加载现有 `lib/` 和 bundled `worker.cjs`，写入临时 v0 header，真实 `open(id, 'write') → close() → service.flush()` 后读取 `session.v2.jsonl`，确认版本为 2。本例是空历史日志的真实进程迁移；含事件的详细迁移已由上面的源码测试覆盖。未重新构建产物，不能据此单独证明全部 `lib/` 与 HEAD 字节一一匹配。

主进程另独立运行了最新版 Python SDK + built CLI 的 initialize/shutdown，结果文件 `/private/tmp/dsh-v2-sdk-boot-result.json` 为 `passed`，revision 同为 `b236969...`，scope 为 `latest-built-cli-sdk-initialize-shutdown-only`。本报告读取该结果，未重复启动。主进程此前 source CLI 启动报 `FiberState` export 缺失；**这是 source 启动路径问题，不能扩大为已通过的 built CLI 初始化或 built migration worker 故障**。

## 完整 Uni-Agent：6 文件、84 项，exit 0

在当前 Uni-Agent worktree 执行：

```sh
env PYTHONPATH=.:verl:/private/tmp/uni-agent-cpu-20260907/lib/python3.12/site-packages:/private/tmp/harbor-h0-20260908/lib/python3.12/site-packages \
  /private/tmp/uni-agent-cpu-20260907/bin/python -m pytest \
  tests/uni_agent/agents/test_dsh_agent.py \
  tests/uni_agent/agents/test_dsh_runner.py \
  tests/uni_agent/agents/test_dsh_harbor_agent.py \
  tests/uni_agent/tasks/test_dsh_trajectory_audit.py \
  tests/uni_agent/tasks/test_dsh_ops_audit.py \
  tests/uni_agent/tasks/test_harbor_dsh_executor.py \
  -q -p no:cacheprovider \
  --junitxml=/private/tmp/dsh-session-v2-unia-pytest-final-20260908.xml \
  > /private/tmp/dsh-session-v2-unia-pytest-final-20260908.log 2>&1
```

| 文件 | 通过数 | 证据层次 |
| --- | ---: | --- |
| test_dsh_agent | 12 | FakeSandbox 驱动真实 adapter，配置、helper 身份、失败处理 |
| test_dsh_runner | 3 | FakeHarness 驱动真实 runner，trace/hash 与 Gateway 配置 |
| test_dsh_harbor_agent | 21 | Harbor 类/工厂及 bridge，环境和模型执行使用替身 |
| test_dsh_trajectory_audit | 13 | 真实审计逻辑读取合成轨迹、原始字节和回执 |
| test_dsh_ops_audit | 9 | 真实消费关联与篡改拒绝逻辑，使用测试产物 |
| test_harbor_dsh_executor | 26 | FakeTrial/模拟 Docker 查询驱动真实 executor |

总计 84 passed，0 skipped，5.54 秒；仅 1 条 Ray API deprecation warning。**这些通过证明当前适配/审计逻辑回归没有失败，不是最新 DSH 模型事件流或真实 Harbor 学生执行兼容证明。**

保留两次收集失败，避免把测试环境问题混入 Session v2 结论：首次缺少 `verl` 路径，exit 2；第二次补路径但 Harbor site-packages 抢先提供 `tokenizers==0.23.2`，与 CPU transformers 要求冲突，exit 2。最终仅调整 `PYTHONPATH`，让 CPU 依赖优先，未安装/升级依赖，也未跳过验证。失败日志分别为 `/private/tmp/dsh-session-v2-unia-pytest-20260908.log` 与 `...-retry-20260908.log`。

## 后续门槛

现在可确认：Session v2 相邻迁移、attempt 处理、文件持久化合同、离线转换器及一个 built worker 场景实际通过；built SDK 可初始化与关闭。仍需在升级 pin 前验证最新 Linux SDK/runtime wheel、真实模型 rollout 的事件/trace/finish 字段、Harbor 真实 worker 回传，以及更新后的训练与独立 reload。不能用这批 473 项测试的总数替代任何一个缺失的运行层证据。

机器结果 SHA256（无 `sha256:` 前缀）：

- DSH Vitest JSON：`d332f5f3c63e3de557a5ce5d722beef4f509536510161a51895ac76982d7d024`
- built worker JSON：`2657b6742b9ad05050553ae66fb0e3c3d9dd30a19db1a1ace205e3c96a9cb220`
- Uni-Agent JUnit XML：`9f11b8f7cf8e10db95287d7f41b7666440eee6563b195458753ad76fc743b401`
- 主进程 SDK boot JSON：`9365802ba3ec3f92567a46823669e1bd9ef45ed3bad221e09a8cb0068290d587`
