# evolution → Harbor：首批最小接线清单

2026-09-08，只读设计。已与 `verl_six_month_audit` 对齐新 scorer；初版为只读清单，末尾实施合同已由主线程批准，本批不启动 Docker/GPU。M1 的新版 4 train / 2 holdout 训练与独立 reload 仍独立保留；本批 M2 只选择一个公开 `redact-holdout-01` 场景做 VAL_ONLY / 同题工程复验，不宣称独立留出或 RL 提升。

## 已有合同与当前限制

- 新 `uni_agent/tasks/harbor_dsh/evolution_scoring.py` 提供 `EvolutionBinding → load_evolution_binding → FrozenEvolution → score_evolution → require_evolution_admission`。binding 固定 `kind=evolution-v2-lifecycle-v1`、完整 TaskRef、fixture/metadata 的绝对路径与摘要、两份原 verifier 源文件摘要。
- `score_evolution` 接收原始 trace/run bytes、各自摘要及 Gateway session；返回原 `_score_episode` 的小数 reward、accuracy、eligible、七项 components/hard_veto、evidence 与身份摘要。**保留小数 reward**，不可套 T2 的 `int(passed)`；hard-veto / 证据错误必须拒绝准入，不能变成可训练的 0。
- scorer 不是独立 verifier CLI，也尚未接 executor/Task。其源码依赖 Pydantic、`.protocol`；B 已移除对 T2 verifier 的 JSON helper 依赖。镜像不能照搬原 T2 的纯 stdlib 依赖声明。
- `prepare_m2_training.py:110` 强制只有一个 TaskRef，`:56` 的 `_rows` 复制同一 instruction；`HarborWorker` 与 executor 只收一个 task_dir。`train_count=4/heldout_count=2` 仍是同题复制，不能变成 M1 的六个独立场景。
- `task.py:97` 和 `prepare_m2_training.py:117` 把“存在 patch”当成“T2”。evolution 使用同一 patch，**业务评分类型必须按 operator binding.kind 显式选择**，patch 只负责组合身份校验。

## 路径与身份映射：必须显式写入 manifest

| 身份 | 本地 M1 源值 | Harbor 目标值 |
| --- | --- | --- |
| fixture bytes | 原 `redact-holdout-01.json` | agent 镜像 `/app/fixture.json`、独立 verifier `/tests/fixture.json`；bytes 相同 |
| prompt 中 fixture 绝对路径 | `/workspace/rebuild/uni-agent-g1-v2/examples/dsh/fixtures/evolution-v2/redact-holdout-01.json` | `/app/fixture.json`；两个出现位置都必须一致 |
| metadata.fixture_path | `examples/dsh/fixtures/evolution-v2/redact-holdout-01.json` | `fixture.json`，相对 agent workdir `/app` |
| metadata.fixture_digest | 原 fixture bytes SHA | 不变 |
| patch bytes SHA256 | `edace17a8096ec41e572c10fc7ad96f0d9a62c0a6ff9c8271694b4c1b1024aeb` | 不变 |
| ordered patch paths | `["examples/dsh/evolution.patch.yml"]` | `["/opt/dsh-patches/evolution.patch.yml"]` |
| metadata.patches_sha256 | `sha256:a677aeff3ee7d9dbdc93e83891355442bd06ff5aa067118e6871e37e027d4db6` | `sha256:20d51a73b697f36f397b22f408401cce14625238a95ae2d83aff317de6dd906d` |
| metadata.environment_digest | 新版 runtime executable `sha256:d1a467...` | 保持 runtime executable 摘要不变；镜像由独立 DshRelease.image_digest 绑定 |
| metadata.scenario/task/candidate/verifier | 源 row 的实际字段 | 保持原值，不重命名 candidate 或更换原七项评分规则 |

打包器保留原 row、原 prompt、原 metadata 的摘要与映射表；冻结转换后 prompt/metadata 的摘要。复用 `prepare_evolution_dataset._prompt` 渲染目标路径前，先断言源 row prompt 等于同函数以源路径渲染的结果，确保除路径外业务指令未漂移。只替换具体 fixture 路径，不盲目全局替换整个仓库 root。

agent 镜像只接收公开 fixture 和 patch，不接收 verifier 源码或参考答案。它读取的文件不是 oracle；评分始终使用独立 verifier 中受 TaskRef 约束的原始 fixture。不要把 root 容器中的 chmod 只读文件称为不可篡改沙盒。

## 最小文件改动点

| 文件 / 当前入口 | 下一批必要改动 |
| --- | --- |
| 新 `examples/harbor/prepare_evolution_task.py`；参考 `prepare_t2_task.py:56` | 只选择上述单场景，复用原 row/prompt/fixture；新 output/task + 外层 sidecar；生成 agent fixture COPY、metadata、原 scorer 源码、双镜像固定值、所有文件 hash、source→deployment 映射。拒绝覆盖和未允许的场景/变化。 |
| 新 `examples/harbor/evolution_verifier.py`；参考 `t2_verifier.py:52` | 读取可信上传的 session/run/status 与新增 binding；核实际 session/完成/摘要，再调用同一新 scorer，写 `reward.txt` 小数原值与完整 `evolution-report.json`。eligible=false/异常 exit2，不写 reward。 |
| `uni_agent/tasks/harbor_dsh/task.py:55,97,195,303,384` | 新可选 operator-only `evolution_binding`，与 t2_fixture 互斥；构造时加载冻结 fixture/metadata。所有有 patch 任务必须恰有一个合法业务 binding。下载证据校验后调用 `score_evolution` + `require_evolution_admission`；另核 metadata.environment_digest=请求 runtime executable SHA、profile/patch digest=实际 release。receipt 绑定 kind、fixture/meta/source 摘要，旧 T2/file receipt 格式保持兼容。 |
| `uni_agent/tasks/harbor_dsh/trajectory_audit.py:81,136` | 增加同名可选 operator kwarg，在 `_verify_saved` 独立重新评分并重建完整 receipt；不得从 receipt 自行采纳评分类型或 metadata。未知/双重/missing binding 拒绝。 |
| `uni_agent/tasks/harbor_dsh/registration.py:248` | `validate_registered_trajectories` 增加并传递 evolution_binding。此处是显式函数签名，漏改会在 Gateway 完结准入时报 unexpected keyword。 |
| `examples/harbor/prepare_m2_training.py:88,117,150,184` | 新 `--evolution-binding`；冻结并核 task/tests 的 fixture/metadata；与 t2 参数互斥；同时传入 task YAML 与 launch.postprocessor。`_rows` 不能再假设 fixture 有 T2 的 case_id/split，使用 evolution metadata 的 scenario_id/split。项目名和 scope 标记同题工程；仍只一个 TaskRef。 |
| `uni_agent/tasks/harbor_dsh/executor.py:256,299` | TaskRef 校验后读取任务内固定评分描述，显式选择 evolution；从 `request.task_ref` 构造独立 verifier 使用的 binding，把路径重绑定为 `/tests/fixture.json`、`/tests/metadata.json`。仍检查镜像/patch；传递可信 binding 给 Trial，不能取 agent 输出作为 binding。 |
| `uni_agent/tasks/harbor_dsh/isolated_trial.py:254,281` | 窄增 evolution 的可信 binding 参数并冻结 bytes；仍使用现有 TraceArtifacts 流程、artifacts=[]、无 agent host mount、独立 verifier。无需重写 Harbor 环境生命周期；已有 T2 trace 传输路径可复用。 |
| `uni_agent/tasks/harbor_dsh/trace_artifacts.py:149` | 仅对 evolution 增加固定 `/audit-input/evolution-binding.json`，小文件有界、单次、来自 host 参数。原 session/run/status 三文件和来源校验不变；不接受任意学生文件或路径。 |

### 防止 TaskRef 自引用

完整 EvolutionBinding 自带 TaskRef SHA，**不能放进参与 TaskRef 哈希的 task/ 文件中**。任务内部放不含 TaskRef 的固定 `evolution.json`（kind、相对 fixture/metadata 路径、source SHA）；先完成 task 文件哈希，外层 manifest 再写完整 binding。executor 核 task hash 后为 verifier 注入完整 binding。Task 与训练侧使用 Pod 重新生成的外层 binding，保持各自主机的真实绝对路径；仅 bytes/hash/TaskRef 跨主机相同。

新增第四个上传文件是 controller-owned 评分输入，不能算第六类 worker 输出证据。当前对外五类 `dsh_trace/dsh_result/harbor_result/verifier_log/reward` 可保持不变；完整评分 report 应打印到 verifier stdout，训练侧另按原始证据重算，避免必须改 ArtifactKind。

### 镜像与可直接复用的模块

- agent 基于已核验 T2 DSH 0.1.3a2 b016 镜像，仅 COPY 单个 public fixture（继承固定 patch）；这会产生新 agent image digest，不能继续声称 b016c... 已含 fixture。无需重建 wheel、训练环境或模型。
- verifier 使用已固定 b016 DSH amd64 base 的 Python/Pydantic、network=none；复制新 CLI/scorer/protocol 与两份原 verifier，父 `__init__.py` 为空以免导入训练框架。复用已固定 b016 verifier 父镜像中现有 Pydantic，不安装新依赖；记录版本与父镜像，实际验证导入。也可后续单独拆纯评分 seam，但本批不引入另一评分实现。
- `train_m2_online_rl.py:65` 整体透传 launch.postprocessor，`audit_m2_training.py:87` 同样复用该对象，原则上无需改两者；覆盖测试确保新增参数经过 registration 正常到达。
- `harbor_agent.py`、release patch allowlist、worker HTTP/ledger/protocol、controller、token/receipt transport、五类 artifact、cleanup inventory、VERL 和 DSH runtime 均可复用。T2 transport 常量名称不应被误用为 evolution 的业务评分身份；无需为改名字做大范围重构。

## 必须完成的验证与明确延后项

1. CPU 打包：跨 Mac/Pod 相同 TaskRef；原行仅批准的路径/runtime 映射变化；fixture/metadata/source 错 hash、错 patch 路径、错误绑定类型、互斥字段、既有 output 均拒绝。
2. scorer 原规则对照：原 reward/accuracy/components 完全保留；包含小数 reward、未调用 candidate 的低分、hard-veto 拒绝，避免全部转成二值。
3. Task + trajectory 双重复验：相同真实 evidence 准入；错 metadata、错 reward、错 TaskRef、错 session、来源未知 binding 不能入训练；file/T2 旧 optional-only 配置回归。
4. 独立 Docker：正例、小数失败例、未调用 candidate、篡改证据分别给预期 reward/拒绝；agent/verifier 完整清理后才报告成功。
5. 一个 public 场景学生 VAL_ONLY：真实 Gateway tokens、独立 verifier、Task 及 postprocessor 消费审计全通过后才宣称 Harbor 工程复评接通。M1 的 4/2 留出结果单独报告。

多 TaskRef 明确延后：未来需同时增加固定 TaskRef→task_dir 的 worker 路由、逐 row 的 operator 已批准任务/fixture/metadata 选择、批次 audit 与 registration 策略映射；每场景独立 image/TaskRef 或经过设计的共用镜像。当前不扩大该分发实现，也不把同题复制标记成六题课程。

## 本批实施合同（主线程已批准）

- `task/evolution.json` 恰含 kind、fixture_sha256、metadata_sha256、source_sha256s，不含 TaskRef；执行器有界读取，校验固定 tests/fixture.json、tests/metadata.json 和部署 metadata。
- executor 将 request.task_ref 注入 EvolutionBinding；fixture_path=/tests/fixture.json、metadata_path=/tests/metadata.json；canonical JSON bytes 最大 64KiB。`IsolatedDshTrial` 使用独立 `strategy=evolution-v2-lifecycle-v1` 和 `evolution_binding: bytes`，T2 原 strategy/三文件不变。
- TraceArtifacts 只在 evolution 分支上传固定第四文件 `/audit-input/evolution-binding.json`；bytes 来源为 executor，不读取学生产物。构造时校验固定路径，保存 bytes 快照；三份原始桥接文件的全部校验继续保留。
- 新 CLI `python -m examples.harbor.evolution_verifier --input-dir /audit-input --output-dir /logs/verifier`。默认源码根由已导入模块位置决定 `/opt/evolution-verifier`；绑定仅能指向固定 `/tests` 两文件。CPU 单元测试可通过内部函数显式传入隔离 fixture/metadata 路径，CLI 不开放该覆盖。
- CLI 对已核对完成的 status/run/trace调用共用 scorer，写完整 evolution-report.json + 原小数 reward.txt；异常/hard veto exit2，无reward；不得覆盖既有输出。
- TDD 分三片：独立 verifier 输入/评分；第四可信文件传输和 strategy；executor TaskRef 注入与错误文件拒绝。仅模拟 Docker 边界，主线程随后负责真实容器验收。

## 本批执行端实际结果

- executor / isolated_trial / trace_artifacts 与新 evolution verifier CLI 已实施；新增第四可信 binding，不改变 T2 的三文件路径、旧 answer 流程或五类对外证据。
- 元数据 runtime 摘要保持原值并核对 `request.dsh_release.runtime_sha256`；镜像身份继续独立由 task TOML/release 校验。
- TDD 红灯已分别观察到缺 CLI、构造函数不接受 binding、executor 错走 T2/未拒绝错误描述；对应实现后组合 **170 passed，1 条既有 Ray deprecation warning**。八个本批代码/测试文件 Ruff check、format 检查通过。
- 测试命令为 `python -m pytest tests/uni_agent/examples/test_harbor_evolution_verifier.py tests/uni_agent/examples/test_t2_harbor_verifier.py tests/uni_agent/tasks/test_harbor_dsh_executor.py tests/uni_agent/tasks/test_harbor_dsh_isolated_trial.py tests/uni_agent/tasks/test_harbor_dsh_trace_artifacts.py tests/uni_agent/tasks/test_harbor_evolution_scoring.py tests/uni_agent/tasks/test_harbor_evolution_admission.py -q -p no:cacheprovider`。使用 `/private/tmp/uni-agent-cpu-20260907/bin/python`；PYTHONPATH 顺序为本仓、本仓/verl、CPU venv site-packages、Harbor 0.16.1 venv site-packages，防止后者 tokenizers 版本遮蔽前者。无依赖安装或升级。
- Docker/SDK 模型调用由主线程下一批验收；本批使用真实本地文件、原评分函数和 Harbor 对象构造，模拟有副作用的容器执行边界。
