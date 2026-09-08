# Evolution 生命周期课程接入 Harbor：只读最小增量评估

状态：设计建议，未实现、未启动资源。前提是原生 DSH M1 给定合法 redact_email 实现的 4 train / 2 holdout 课程先产生真实可解释效果。不是 T2 自编工具任务通过，也不扩大到 Modal / 全异步。

## 决策

值得把现有 trace 任务的评分配置收敛为两个明确受限 kind：`t2-log-tool-strict-v1` 与 `evolution-v2-lifecycle-v1`。不另建 DSH Agent / Harbor bridge / worker / token loop。原 file-answer smoke 仍保留既有路径。**runtime patch 不是评分类型**：两课程可以使用同一固定 evolution.patch 和 SDK 镜像，不能继续用“有 patch ⇒ T2 strict”选择评分。

新 task id/version、TaskRef 文件 hash、fixture/meta/source bundle hash 与 `kind` 一起冻结，kind 由操作员 task 文件和独立审计配置提供，不能由 prompt、学生结果或 worker reward 选择。协议已有 RequestPolicy.task_refs 白名单（protocol.py:129–147），最短方案可保持 HTTP JobRequest 不变：worker 从冻结 task 文件解析 kind，TaskRef hash 绑定；训练 Task/audit 独立 operator binding 必须匹配 TaskRef/kind。避免为此引入通用插件系统。

## 原评分合同，完整保留

`examples/dsh/evolution_verifier.py:_score_episode`（247–432）返回 `(reward, accuracy, details, evidence)`，七组件权重为 grounding .10、package_validity .15、lifecycle .15、behavior .25、recovery .15、containment .10、evidence .10。hard_veto ⇒ 0；业务错误最高 .40；未调用候选最高 .25。不能改权重、阈值或为得到非零删除 hard_veto。`_fixture_expected`（167–186）独立执行固定 operation 的 Python oracle。

Harbor 入口应重用 `_load_trace` 与 `_score_episode`，而不是调用旧 CLI `verify()` 并伪造其 DSH_TASK_* envelope/旧 fresh receipt。Harbor 具有新可信 TaskRef 与 trace/run/status/hash/session 合同；独立构造**评分输入** `{metadata: frozen_metadata, response: run.final_response, dsh: verified_run_identity, finished: true}`，清楚标注不是原 DSH task receipt。固定 metadata 至少 operation/candidate_tool_name/scenario_id/fixture_digest/profile/patches_sha256，不得用学生 trace 中自报 metadata 覆盖。

准入必须谨慎：旧 `_score_episode` 的 `details.eligible = not hard_veto`（425附近），T2 则把结构不可信与普通任务失败分开。**本迁移不悄悄改 eligible 语义**。默认保持原生 M1 同样准入政策；例如 missing_pre_define_inspection 的 0 分是否进入优化必须先核 M1 Task/audit 实际处理，并在等价测试中固定。若原 M1 将这类样本拒绝，不应仅在 Harbor 改成接受；需要独立课程/准入设计决定。hash/session 错误一律基础设施拒绝，不给任务0分。

## 可直接复用及最小文件变更

- 不改 `DshHarborAgent`、`DshAgent`、`BorrowedHarborSandbox` 和 Gateway：输入仍 instruction，执行仍唯一真实 DSH loop；已固定 agent 镜像含相同 patch，无须重建 agent image（先核新课程 patch 字节完全一致）。
- `trace_artifacts.py`：直接复用宿主有界原始 session.jsonl/run.json/status.json 采集、trusted gateway/trial 身份与独立 verifier 上传。该机制只验证执行证据，不应分叉成第二 handler。
- `harbor_release.py`：保留固定 patch 身份，新增两个有限 scorer-kind 常量及白名单，或一个轻量固定合同模块；不要把 kind 混作 patch hash。
- `isolated_trial.py:_validate_task/__init__/create_isolated_trial`：两种显式 trace 策略共用 artifacts=[]、无 host mount、固定 patch、session/预算门与同 handler；原 answer 分支不变。
- `executor.py:execute_job`：从 TaskRef 已验证的冻结 task metadata 选择上述 kind，而非当前约301行无条件 strategy=T2_STRATEGY。仅允许两种；未知 kind 拒绝。
- 新 `examples/harbor/evolution_verifier.py`：独立镜像入口，复用三文件身份检查（可把现 t2_verifier 的纯证据读取薄函数提取共享，但不移动/改变 T2 评分）；从 tests image 固定路径读取 fixture+metadata/hash，原 `_score_episode` 输出有限 scalar reward 与完整组件报告。保留 finished/eligibility，并用新 report schema。
- 新 `examples/harbor/prepare_evolution_task.py`：从既有 M1 固定数据选 case，保持原 instruction/合法实现/输入/metadata，不重新创造任务；冻结独立 tests image、TaskRef、operator fixture/meta binding。4+2 的来源划分原样保留，不把公开可见课程称隐藏。若原 prompt 要 view fixture，agent image/task 需提供同原只读输入位置（或经已批准等价课程调整prompt）；不能漏文件导致奖励失真。
- `task.py`：新增受限 `EvolutionFixtureBinding` 或 tagged union，保持既有 t2_fixture 兼容；新 `_verify_evolution_business` 用相同 rawtrace/run/frozenmetadata 重算完整 reward，不把 reward cast 为 bool。替换 `_fixture_lane`（97–103）“有patch就是T2”假设。receipt 新增 scorer_kind / frozen-meta hash / fixture hash，保留真实 worker result 和旧 T2 独立严格复验。
- `trajectory_audit.py`、`audit_m2_training.py`：传入同可信 operator binding并重读固定输入，不从 receipt 决定 scorer；原 Gateway tokens/masks/logprobs不重建，训练 TQ join 与 scalar reward 仍精确一致。必要配置准备入口追加对应 binding，registration/server 协议无需新实现。

## 测试门与收益判定

1. CPU：相同原生 M1 已验证 events/fixture/meta，在原评分与 Harbor 入口及训练审计三处逐组件、reward、accuracy、eligible 一致；包括业务正确/错误、缺调用、漏cleanup、hard veto、最终报告错误。不是只测“有非零”。
2. 独立负例：换 kind/TaskRef、错 fixture/meta/source hash、伪造 response、错 session、重复/畸形事件必须拒绝；T2 旧 strict 全回归，禁止把 fractional reward 当其 boolean passed。
3. 固定 Docker scripted：实际 DSH 同路径生成证据，独立 verifier 和训练侧重算一致，正例/部分失败/拒绝各有真实证据，清理 independently verified。脚本不证明学生学习。
4. 学生同课程：新 run_id 与固定 adapter/base/task/images；原生 M1 vs Harbor 奖励组件可比较。之后 GRPO 需真实组内差异、有限梯度、optimizer step和LoRA数值变化、TQ消费审计与独立reload；不把接口通过当训练效果。

## 必须记录的边界

旧 evolution scorer 是既有课程评分，不等同 T2 的严格同 Plugin/Run 全calls验收。源码 recovery 仅检查最后 stop/undefine 成功标志，未严格核清理同一个实例；run_valid 等 `.get(is_error)` 对缺结果的默认行为也弱于 T2 strict。本次不能以迁移名义改分数，但应保留这些已知限制，报告“给定实现的生命周期课程”，不得宣称对抗性安全、任意动态 RSI 或自主实现能力。

host trace hash 只能证明转移字节一致；agent root 可改本容器runtime/trace，仍非外部不可篡改行为证明。独立 verifier 保护评分代码，不能自动提升原始事件的信任等级。

更短路线：先在原生 M1 获得可复验课程收益与独立reload，再做上述评分接线。如果 M1 没有有效行为变化，先诊断提示/schema/准入/优化信号，暂不扩 Harbor；迁移沙盒不会解决模型不会执行的问题。

## 第一实现批次：冻结评分输入与纯 CPU 重算

新增 `uni_agent/tasks/harbor_dsh/evolution_scoring.py`，仅支持 `evolution-v2-lifecycle-v1` 与 redact_email。`EvolutionBinding` 固定 TaskRef、fixture/metadata 绝对路径及各自 SHA、原 scorer 两源码文件 SHA；加载后持有 immutable bytes，评分不重新读取输入文件。`score_evolution` 接受宿主已经绑定来源的 trace/run bytes、各自预期 SHA、Gateway session 与同 TaskRef，使用 run.final_response 构造纯评分 envelope，复用 `_load_trace` / `_score_episode`，返回原 reward/accuracy/details/evidence；不生成旧 DSH fresh receipt。

独立输入结构或身份错误抛异常；业务 hard_veto 保留原 reward=0/eligible=false，`require_evolution_admission` 明确拒绝该样本，与 `uni_agent/tasks/dsh/trajectory_audit.py:197` 一致。安全普通失败的小数分保留。T2 scorer 及旧 file lane 本批不变。

测试覆盖六种原评分等价（正确、业务错误、无候选、漏清理、hard veto、最终报告错误）、冻结文件变动后仍用原 bytes、TaskRef/kind/fixture/metadata/scorer hash 身份、trace/run/session/重复事件以及小数准入。CPU fixtures 是合成测试证据，不是新学生轨迹。

部署接线待下一批：原 metadata 的相对 patch list digest 与 Harbor `/opt/...` 不相同，不能因 bytes 相同而绕过校验。打包器须显式记录并冻结部署路径 metadata 转换和原 metadata 身份；原 prompt 的 fixture 绝对路径须真实提供或另行记录明确迁移。纯 scorer 不自动改 metadata。

第一批验证结果：18 个新增 scorer/绑定测试 + 7 个原 evolution verifier 回归，共 25 passed；新增 Python 文件 Ruff check / format --check 通过。冻结字段另含 fixture_path（用于打包部署位置合同）。本 module 无 T2 scorer/oracle import；仍依赖 Pydantic 与既有 protocol.Contract/TaskRef，后续独立 verifier 镜像需固定这些依赖，不能按纯 stdlib 镜像直接复制一个文件。此批没有 CLI、worker 选择 kind、Task/audit 接线、打包器或 GPU 部署；不宣称 Harbor 新课程已经打通。

## 打包批次：一个公开 redact-train-01

新增 `examples/harbor/prepare_evolution_task.py` 与 CPU tests。输入外部 SHA 绑定原16/8 source manifest，校验全源 Parquet bytes、固定 scenario fixture、原 scorer/source metadata 与 patch bytes；只取 `redact-train-01`，不将单任务重复包装成4/2或隐藏验证。CLI 接 `--root --source-dir --source-manifest-sha256 --output --agent-image-digest [--verifier-image-digest]`。

`task/evolution.json` 固定 `{kind,fixture_sha256,metadata_sha256,source_sha256s}`，无 TaskRef；fixture/metadata 在 task/tests/。旁置 manifest 包含 TaskRef、训练 operator evolution_binding 与完整原 row/metadata 摘要及 source SHA。只把原 `_prompt` 中 fixture绝对路径映射 `/app/fixture.json`；metadata 部署 fixture_path、patches_sha256、environment_digest 变化须逐字段记录，不修改原评分或实现代码。

agent 与 verifier Dockerfile 父镜像均固定本地 `uni-agent-dsh:t2-log-tool-r1`，构建前必须 inspect imageID `sha256:b016c85140a58f7d842eadb0238925ee1c347143cc7bede5b9b35bfa38747dca`，不拉取、不联网安装依赖。agent COPY fixture 到 `/app/fixture.json` 并只读文件模式；独立 verifier network_mode none，COPY 最小闭包 src 到 `/opt/evolution-verifier`、fixture/meta到/tests，已有Pydantic由父镜像提供。worker负责第四份独立 operator binding 输入，打包器不伪造试次/session。TaskRef摘要不含旁置manifest，避免自引用。prepare不build、启动Docker/GPU或训练。

测试：可信源/patch/fixture/source SHA错配失败、禁止非固定scenario、原instruction除路径外逐字不变、原metadata→部署metadata差异穷举、闭包文件齐全、TaskRef重算一致、旁置binding与task marker一致、固定父镜像/no-pip/networknone、拒覆盖与私有文件。

打包批次完成 CPU 验证：9 新测试；连同 selector/原 scorer/冻结 scorer 共44 passed，Ruff check / format通过。`metadata.environment_digest` **保持原固定runtime binary SHA d1a467...**，绝不替成agent imageID；后者独立由release/TaskRef约束。实际映射差异只有 fixture_path 与 patches_sha256。最小5文件闭包已在独立cwd、仅指向打包src的PYTHONPATH下子进程import验证，尚未Docker build或部署。
