# Harbor 复用固定 M1 v2 准入：最短独立迁移

状态：只读设计，等待原生 M1 v2 验收；本文件不表示已接通或训练成功。当前原生 GPU 使用源码 `2df91d7de31b9ecacefeaad1c54dbea80028eead`。不得修改运行中的 `examples/dsh/evolution_verifier_v2.py`、两个父评分源码或现 v1 kind 的行为。

## 结论与更短路径

建议新增一个 Harbor v2 adapter，通过**有界子进程调用现有固定 v2 CLI**。不要在 Harbor 复制 `_complete_pairs` / completed-policy-failure 条件，不修改 v1 scorer，也不要通过改 eligible 标记伪装 v2。原 v2 本身是 stdlib，私有临时源码快照 + CLI 比提取公共规则更短，也不需要改变本轮 GPU 正在绑定的源码 bundle。

若原生 v2 尚未产生有效准入与参数更新证据，先完成原生诊断；提前增加 Harbor 平台不能改善模型执行能力。现有 Harbor v1 Docker 测试继续按其原准入解释，不能与 v2 混报。

## 固定身份与规则

现场只读计算：`bundle_digest=sha256:60f49dcb519576bbe09839371ec3220775aa42aaf5e780a7f5d843c71552ea82`。必须沿用现 `bundle_digest()` 算法：**三个 basename → barehex SHA map，sorted compact JSON，无newline，然后SHA**，不能换成带目录名或带sha256前缀的新算法。

| basename | SHA256 barehex |
|---|---|
| evolution_verifier.py | 067668803e5f6fdb5f64cd44a17e2f4baef8835e4681a02cdf35d9f6bb4e3748 |
| verifier.py | eb5e0d68779739d04e1038534e5f2799a44cf299e7325ba2f6bef5c793ecf2cd |
| evolution_verifier_v2.py | 310460e0ef7a7f9876a5b7069f351f080d990d05fef526c71b3af03975ac0934 |

新增显式 `kind=evolution-v2-lifecycle-admission-v2`（名称区分课程版本与准入版本）；Harbor TaskRef id仍单个 `evolution-redact-train-01`，version改 `v2`、新完整目录SHA。task metadata 的 task_version/verifier_version必须都为字符串 `2`，verifier_code_digest必须上述完整bundle，verifier_id保持原值。

七组件 reward/accuracy保持原值。v2仅对 `hard_veto == ['missing_pre_define_inspection']` 且 reward=accuracy=0、finished=true、最后 turn/end reason严格completed、工具call/result完整配对的样本准入。混合其他hard veto、未完成、坏配对仍拒绝。原v1已准入路径不因迁移突然加新业务限制；来自Harbor的通用身份/完整性检查须单独归为证据准入层，不能声称新增规则是原v2业务评分。

## 新 adapter 输入与生命周期

建议 `evolution_scoring_v2.py` 暴露 `EvolutionV2Binding`、`FrozenEvolutionV2`、`load_evolution_v2_binding`、`score_evolution_v2`、`require_evolution_v2_admission`。与现v1同一 TaskRef/fixture+metadata外部SHA/run+trace SHA/session API，新增明确完整 verifier bundle身份。Task和audit只能从operator参数选此kind，worker marker必须与TaskRef冻结文件一致；不从receipt或reward猜kind。

流程：

1. 主机先按现trace/run/status规则验证试次、session、finished、hash、runtime/profile/patchpaths；加载operator绑定fixture/meta一次，持有bytes。严格JSON拒绝歧义；这里不是学生重新生成轨迹。
2. 验证三个源文件hash与固定bundle；把读到且验过的三份bytes写入独立0700 temp/src/examples/dsh，补empty init。原checkout/source不改，避免验证后重新读取另一版本源码。临时文件0600。
3. 同一temp写入fixture.json、原始session.jsonl、派生task-result.json。envelope.schema使用CLI所需 `dsh.uni-agent.task-result.v1`；metadata来自冻结operator，response仅来自已验证run.final_response，dsh来自已验证run，finished由已验证执行状态提供。**这是内部评分adapter输入，不是历史M1原始产物或可信学生fresh receipt**。
4. fixture读取位置需要显式内部映射：原Harbor metadata.fixture_path=`/app/fixture.json`，私有envelope副本改成`fixture.json`，DSH_TASK_WORKDIR=temp。原metadata bytes/SHA仍保留；报告记录该内部映射与派生envelope SHA，不偷偷改Task metadata或原run。fixture_digest、operation、输入、代码、任务ID、runtime、patchpaths与源bundle均不变。单元测试证明此路径映射不改变评分。
5. 通过绝对 `sys.executable`、`-I` 与固定 `-c` bootstrap（sys.path仅插入temp/src，调用原模块main）启动子进程；无shell，无共享 `os.environ` mutation，env清单仅含必需DSH_*变量，剔除模型凭证/代理。设置固定10秒timeout，stdout/stderr写私有文件后有界读取（建议各256KiB），异常/超时/非零/非单JSON对象立即拒绝；不重试。固定原v2代码不spawn子进程，subprocess.run timeout可回收该owned进程。
6. env准确提供：DSH_TASK_RESULT_PATH、DSH_ARTIFACT_SHA256、DSH_TRACE_PATH、DSH_TRACE_SHA256、DSH_DSH_SESSION_ID、DSH_TASK_WORKDIR；DSH_TASK_ID/TASK_VERSION/ENVIRONMENT_DIGEST/VERIFIER_ID/VERIFIER_VERSION/VERIFIER_CODE_DIGEST从冻结metadata映射。所有SHA对应本次私有实际bytes。
7. 原CLI输出reward/accuracy/eligible/finished/evidence/extra_info作为语义结果。检查scalar有限、bool类型、finished=true、eligible=true后才准入；Harbor reward.txt保留float并与训练重算精确一致。`fresh`/`issued_at`只是内部子进程输出，**不得作为Harbor信任依据，也不进入跨次确定性比较**。
8. 独立Harbor report与训练receipt记录kind、TaskRef、fixture/meta/bundle、原trace/run SHA、原v2 admission_kind/original_eligible。Task侧再运行同固定CLI复验，不依赖worker自报通过。内部envelope含随机temp路径的绝对字段时其hash仅单次诊断，不要求跨独立重算相等；可用固定相对fixture路径使metadata稳定，但不把过程路径视为业务身份。
9. finally清理私有temp，已有worker/supervisor总deadline继续生效；10秒子进程开销计入当前verifier/Task预算，不增加AgentLoop或模型调用。

## 精确文件列表（后续实现，不在本轮修改）

- 新 `uni_agent/tasks/harbor_dsh/evolution_scoring_v2.py`：上述薄adapter与绑定，**不得重新实现v2条件**。
- 新 `examples/harbor/evolution_verifier_v2.py`：沿用四份host bridge输入，只选固定v2 adapter，独立report schema/kind。
- `uni_agent/tasks/harbor_dsh/task.py`、`trajectory_audit.py`：增加optional operator-only evolution_v2_binding；与t2_fixture/evolution_binding互斥，Task与审计重算、receipt新身份。
- `uni_agent/tasks/harbor_dsh/executor.py`、`isolated_trial.py`（如当前白名单需要）：显式新kind，marker完整三文件bundle校验；共用原trace handler。`trace_artifacts.py`若只透传独立binding不判断kind则零改动，不另建上传协议。
- 新 `examples/harbor/prepare_evolution_task_v2.py`：只读已绑定 `dsh.redact-curriculum.v2` 的4/2来源，固定挑一个redact-train-01；**单公开工程task**。复用原prompt，只映射fixture路径；固定runtime d1a467与Harbor patchpaths；旁置原→部署metadata/source provenance；TaskRef version=v2。复制v2 CLI/adapter/原三文件bundle及必要contract闭包进入独立verifier镜像，agent镜像若fixture/patch完全一致可复用，无需重建agent。
- `examples/harbor/prepare_m2_training.py`、必要 `audit_m2_training.py` 或现registration审计wrapper：新的optional operator-only binding透传，旧lane默认完全不变。
- 新 tests：`test_harbor_evolution_scoring_v2.py`、`test_harbor_evolution_admission_v2.py`、`test_harbor_evolution_verifier_v2.py`、`test_prepare_evolution_harbor_task_v2.py`，及现marker/parser/prepare回归的最小补充。
- **不改** `examples/dsh/evolution_verifier_v2.py`、`evolution_verifier.py`、`verifier.py`、正在运行GPU配置/数据，也不改旧Harbor v1 kind含义。

## 测试门与后续实跑顺序

1. 原CLI vs新adapter使用同fixture/trace/response：正常1、小数.25、missinginspection完整结束0且eligible=true；逐项对reward/accuracy/eligible/admission_kind/components/hard_veto/evidence，忽略issued_at。原v1对同完整失败仍eligible=false，明确版本差异。
2. 非completed、missingresult、重复call/result、bad result isError、多个hardveto、shell/escape：按原CLI结果一致拒绝或保留eligible=false，不为了非零放宽。
3. 错TaskRef/version/kind/fixture/meta/三个source中任一个/bundle/run/trace/session、伪装原v1 code digest全部拒绝；内部路径映射只准fixture_path，不允许覆盖业务metadata。
4. 子进程timeout/nonzero/输出过大/坏JSON/NaN/错误bool、无泄漏环境、临时目录清理；并行Task调用证明不共享环境，不干扰本轮M1。
5. marker→TaskRef→四文件worker上传→独立CLI→Task/audit全部身份一致；交换v1/v2 binding拒绝；fractional reward与0分准入留到Gateway TQ中，原tokens/logprobs不重建。
6. CPU全回归后先新run的Docker scripted“完整policy失败0分可准入”与成功/恶意负例，再学生VAL_ONLY，最后新run训练。脚本路径只证明集成，不宣称学生或RL效果。原M1 v2与Harbor v2训练证据分开记录。

## CPU 第一实现批次结果

已实现新 evolution_scoring_v2.py、Task/audit 的 `evolution_v2_binding` 独立operator字段及对应两份tests；尚无新worker/packager/独立Harbor CLI接线。20个scorer测试 +4个Task/audit测试，加既有lane回归共119passed；Ruff全部通过。子进程使用 `sys.executable -I -B`、10秒、纯DSH_* env和私有源码快照；原bundle复核仍为60f49d...，三个原源码git diff为空。Task receipt新增 `evolution_v2_binding` 中kind/fixture/meta/source map/bundle身份，独立audit重算原CLI准入，不导入fresh/issued_at；admission_kind/original_eligible在语义评分结果中保留，此批receipt只固定身份和scalar，不把内部CLI诊断时间写作外部证明。

实测CPU合成轨迹：缺前置inspection但完整finished的0分允许Task→audit准入；.25保留；unsafe与缺result拒绝。该测试不是GPU rollout或学习效果。API：`load_evolution_v2_binding(binding, task_ref, repository_root=...)`；`score_evolution_v2(frozen,task_ref,trace,trace_sha256,run_raw,run_sha256,gateway_session_id)`（全keyword）；`require_evolution_v2_admission(evaluation,reward)`。binding沿用v1路径/hash字段，加固定 `verifier_bundle_sha256`，kind=`evolution-v2-lifecycle-admission-v2`、TaskRef.version=`v2`。
