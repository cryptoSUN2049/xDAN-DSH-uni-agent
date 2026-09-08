# T2 同业务接 Harbor：最小增量设计（只读调研）

状态：方案，不代表已实现或已通过。已完成的原生DSH六公开case、学生baseline与SFT step1由各自运行记录证明；本页不将它们转换为Harbor成功记录。先用一个公开dev case贯通，再扩展其余case。继续同步单卡，无Modal或全异步要求。

## 目标与复用边界

RunPod VERL/Gateway → 原注册controller/SSH → Mac worker → Harbor Docker内唯一DshAgent循环 → 独立Harbor verifier容器 → 原worker manifest/client/Task/postprocessor。复用现有固定DSH0.1.3a2 SDK镜像作为父镜像，agent环境只添加冻结evolution.patch.yml，不安装VERL或另写agent循环。

已有直接复用：

- `uni_agent/agents/dsh/harbor_agent.py:run` 借用environment并执行DshAgent；保存宿主私有agent日志 `dsh/session.jsonl`、`run.json`、`agent-result.json`、`status.json`，核对session/hash/结束。
- `sandbox/harbor.py` BorrowedHarborSandbox；既有controller、registration、worker HTTP/ledger/client以及manifest opaque artifact传输。
- `tasks/harbor_dsh/executor.py:_collect_evidence` 当前回传5种artifact：dsh_trace/dsh_result/harbor_result/verifier_log/reward；桥接状态和完整agent-result额外在宿主校验，不需为T2建立第二协议。
- `examples/dsh/capability_tasks/log_tool/verifier.py:verify_trace`及oracle作为同一公开输入业务/生命周期判定器。复用判定，不复制DSH旧receipt。

## 不能直接复制m2-file-write的原因

1. `executor.py:_build_trial_config`（当前约247行）拒绝任何patch；构建kwargs固定patches=[]。`_collect_evidence`和`harbor_dsh/task.py:verify_downloaded_evidence`也固定空patch digest。T2需要evolution.patch.yml提供cordis-host-runner/tool-cordis，单改instruction不会获得工具。
2. `isolated_trial.py:_validate_task`仅允许artifacts=["/app/answer.txt"]；专用有界Docker tar读取只支持这个4096字节答案。T2评分依据DSH trace，不能把任意答案字符串塞到该路径冒充执行证据，也不能把4096限制静默放大为任意下载通道。
3. 当前独立verifier Ubuntu镜像只有shell cmp，没有Python oracle或trace解析器。
4. DshHarborAgent保存的私有宿主trace发生在agent循环结束后，现独立verifier不会自动看到该宿主目录。恢复agent host mount会破坏既有隔离。
5. 训练侧当前仅核验Harbor reward与桥接身份一致，不理解T2业务；T2接入后应以冻结的公开fixture重新运行同一个strict verifier，使可准入0分与不可信轨迹区分在训练侧也保持一致。

## 最短实现分批

### A：冻结一个公开task/release

新增 `examples/harbor/t2-log-tool-dev-01/`：instruction.md、task.toml、agent environment Dockerfile/compose、tests/Dockerfile/compose/test.sh及公开fixture。instruction复用task_bundle的公开业务合同/inputs，不能放学生实现或oracle答案。第一批只此case；后续四train两dev需各自task身份，不能原地修改已注册TaskRef。

Agent Dockerfile FROM 当前已固定SDK镜像digest（当前m2-file-write使用sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97），COPY冻结patch到固定绝对路径。新镜像产生新digest；父镜像/源码文件/patch字节/构建上下文SHA列清单。sdk-minimal profile保持。

DshRelease.patch_sha256s可表达patch字节hash，但现helper.patches_sha256是**有序路径列表**JSON摘要。两者必须分别核验，不能把文件hash与路径hash混用。冻结operator release→容器内绝对patch路径映射，setup复读patch字节hash；不从请求任意路径选择patch。现空patch任务保留原行为。

### B：宿主桥接trace送入独立verifier

最短seam是T2专用ArtifactHandler的`upload_artifacts`：Harbor0.16.1 `trial/trial.py:_run_separate_verifier`已在独立verifier环境创建后、执行tests前调用它，且SingleStepTrial先完成agent并停止agent容器。T2 handler只从自身trial.paths.agent_dir/dsh读取固定桥接文件，校验私有普通文件/大小/hash/session及status，再上传到独立verifier固定`/audit-input/`。

T2 task不收学生指定路径artifacts；新增窄T2隔离factory/handler策略，保留原answer专用handler不变。不需要复制整个Harbor `_run_separate_verifier`、不创建第二sandbox、不恢复agent宿主mount。早期桥接身份检查从现executor抽取最小可复用函数，不能提前要求尚未生成的Harbor reward。

上传trace/run/status只供判定，路径固定；完整raw artifact以宿主桥接副本为准。source是宿主桥接产物，不能在Harbor artifact manifest伪装为学生提交的answer。上传与读取失败均基础设施错误；不写reward0。trace读取当前DshHarborAgent的sandbox.read_file会全量缓冲，现artifact上限是事后准入，不是抗恶意进程硬内存限制。

### C：同标准评分与训练侧复验

Verifier image固定Python基础镜像，最小COPY oracle.py/verifier.py及其实际import依赖：evolution_verifier.py/verifier.py父模块等；不安装训练框架。固定test入口读取`/audit-input/session.jsonl`、可信hash与公开fixture，调用verify_trace。fixture、oracle、verifier不可由agent写，verifier network_mode:none。

`eligible=true,passed=false`写Harbor reward0；passed=true写1；eligible=false或hash/身份/结构异常使verifier非零退出并保留错误，不能生成可训练0奖励。既有Harbor reward/result/worker cleanup证明继续使用。Harbor receipt仍由HarborDshTask生成新鲜请求绑定记录。

训练侧`verify_downloaded_evidence`增加一个明确T2策略：从operator冻结fixture（路径+字节摘要，绑定TaskRef）复核返回dsh_trace，要求重算eligible与Harbor reward一致。其输入不得来自模型prompt或worker自行声明的fixture。原有注册policy、token/mask/logprob、group/session、receipt及optimizer/reload门不放松。

## 预计最小文件清单

- 新Harbor T2固定task目录（上列文件），冻结patch/release清单。
- 新T2专用verifier容器入口及独立trace上传handler（具体路径实施时定）；最小变更isolated_trial factory以显式选择固定任务策略。
- 修改executor释放固定的T2 patch映射及桥接identity helper，维持原文件任务兼容。
- 修改HarborDshTask证据验证以支持operator冻结T2 fixture与业务重算；相应Task配置/准备入口传入冻结合同。
- 对应CPU及真实Docker反例测试；不修改VERL或Gateway采样实现。

## 验收顺序与信任边界

1. CPU：旧文件task回归；错patch路径/字节、错误TaskRef、大小超额、symlink、session错位拒绝；T2公开所有calls覆盖与普通0分保留。
2. Docker无模型：固定脚本通过唯一DSH循环产生trace，新独立verifier得1；no-op/漏调用/漏cleanup得0；重复ID、篡改hash、错session为拒绝；证实verifier无agent可写宿主mount，无残留容器。
3. 固定学生模型公开dev一次：新Gateway真实tokens、T2 trace与Harbor reward全链路复验，尚不要求训练。
4. 有意义差异后才做少量GRPO和独立reload；沿用已有offline batch join、optimizer计数/有限梯度、LoRA数值delta，不以artifact存在代替训练。

限制：公开dev不是hidden；脚本策略不是学生on-policy；学生代码在agent容器有权限改自身runtime/trace，宿主拿到hash一致副本不构成抗恶意行为证明。独立verifier保护评分代码，但不会自动使容器内trace来源可信到可对抗恶意root。更强证据需外部观测与不可篡改采集，此批明确不宣称。终局RSI/记忆/Terminal-Bench效果另验。

## G1 脚本策略 Docker 验收入口

新增 `deployment/checks/harbor_t2_scripted_smoke.py` 与对应 CPU tests。入口接收冻结 task 目录、公开 fixture、新私有 output；四个 mode 各建独立 session，复用 ScriptedPolicy 与唯一 DshHarborAgent，不新增 Agent 循环。HTTP SSE 仅接受固定 session 路由、固定模型和测试 key；响应使用请求模型。positive 得 1，wrongoutput 真实工具返回空数组得 0，noop 得 0，tamper 在 VERIFICATION_START 改 trace 字节且保留原 hash，要求明确身份/hash 拒绝且无 reward。每 Trial 默认 600 秒，查询真实 Docker container/network/volume 清理状态；失败也保存报告及源码 hash，不自动重连。CPU 验路由、响应、策略差异、结果分类、输出保护；真实 Docker 由主线程独立运行，不将 CPU fake Trial 视作容器证明。
