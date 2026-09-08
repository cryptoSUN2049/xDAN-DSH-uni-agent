# Harbor M2：现有 GPU 手动训练与验收说明

## 用途、边界与当前状态

本说明串起已存在的脚本，用于现有 Mac Docker + Runpod GPU 环境的可审计复跑。它不是全新主机的一键安装器。

当前运行名 `harbor-evolution-m2-v2-r1`，执行代码固定为 `be8237ed9b8d22d06bc28195441aa7a28a23a8a0`。本文件编写时，主线程报告 Mac controller PID 69461、GPU supervisor PID 85930 已启动，学生仍在初始化；这些 PID 是历史定位信息，使用前必须重新核对身份，不能直接用于停止命令。**M2 学生训练、参数更新、独立 reload 尚未验收。**后续状态以 [验收表](../../tasks/harbor-modal-integration/acceptance-tracker.md) 为准。

实际任务是单个公开 `redact-train-01`：查看 fixture、检查工具、注册给定代码、调用邮箱脱敏工具并完成清理。数据是同一任务的 **4 行训练、1 行同题评估**，不是四个独立任务或隐藏留出集。四行用于 batch=2 的两个训练批次；基础脚本设置 `total_epochs=1`，默认只生成两行会不足两批。训练前后满分不能证明泛化提升。

链路：VERL 同步 GRPO → Uni-Agent Gateway 实际 tokens/logprobs → DSH SDK/runtime 执行唯一 Agent Loop → Harbor Docker 隔离任务/独立 verifier → Task 与消费审计重算 → VERL 更新。这里是 `trainer.v1.trainer_mode=sync`；Docker 位于 Mac，GPU 无需运行 Docker。未使用 Modal 或 fully async 训练。

## 固定部署身份与目录

| 内容 | 本轮值 |
|---|---|
| GitHub | `cryptoSUN2049/xDAN-DSH-uni-agent`，分支 `worktree-harbor-modal-integration` |
| 执行 commit | `be8237ed9b8d22d06bc28195441aa7a28a23a8a0` |
| GPU checkout | `/workspace/rebuild/uni-agent-g1-v2` |
| GPU Python | `/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python` |
| Base 模型 | `/workspace/models/Qwen3-4B-1cfa9a7`，revision `1cfa9a7208912126459214e8b04321603b3df60c` |
| DSH | `0.1.3a2`，源码 `b2369692ea530007075ebcd18d39fdba0bbd3982` |
| Runtime SHA | `sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb` |
| Verifier bundle | `sha256:60f49dcb519576bbe09839371ec3220775aa42aaf5e780a7f5d843c71552ea82` |
| TaskRef | `evolution-redact-train-01 / v2 / sha256:3cf73f11ef23772c61c243f830e04e095914573740c52be2176c75c68716c3ef` |
| Agent image | `sha256:25b67c52befc3c0ac35e614f3669c3122f2e916f0254f2c5ed95448bffa3897e` |
| Verifier image | `sha256:e3aaf6d7bdfbd0e4d380d78659ff57a5d2e253e61a6ca80339cd1ecd56615696` |
| Mac plan | `/private/tmp/harbor-evolution-m2-v2-r1/deployment-plan.json` |
| Mac frozen task | `/private/tmp/harbor-evolution-v2-docker-r1/harbor-evolution-v2-package-r1/task` |
| GPU frozen package | `/root/runs/harbor-evolution-v2-package-r1` |
| GPU private inputs | `/root/runs/harbor-evolution-m2-v2-r1-input` |
| GPU private run | `/root/runs/harbor-evolution-m2-v2-r1` |
| Checkpoints | `/workspace/uni-agent-g1/checkpoint/harbor-evolution-m2-v2-r1/global_step_<N>/` |

依赖锁见 `deployment/versions/g1-deployment-lock.json`。记录实际 import/version/源码和 artifact SHA，不能以分支名或浮动 latest 代替。文档提交可能晚于执行 commit；不要在运行中的 checkout 上更新源码。

## 1. 计划与新运行准备

同配置重跑必须使用全新 run 名、私有目录、controller/worker ID、tunnel alias、凭证和 deadline。以下命令展示已部署 r1 的准确参数；**不要原样再次启动 r1**。准备器禁止覆盖已存在输出。

`deployment-plan.json` 是本轮已生成的操作清单，含 argv、传输清单、代码与 TaskRef 身份。仓库没有独立 `plan` CLI：由操作人生成 JSON，然后通过 `deployment.services.harbor_run_controller.RunSpec.model_validate_json()` 校验。计划文件中的 `status/pending` 是准备时快照，不能替代运行回执。

RunSpec 需要：两小时未来 deadline（CLI 允许未来不超过四小时）、完整 TaskRef/DSH release、已核实 Gateway 节点 IP，以及 Mac 私有绝对路径。`policy_template` 不填 `gateway_port`，由真实 Framework SessionHandle 注册时提供。

本轮 Mac 控制/worker/model 端口为 48340/48341/48342，GPU 反向控制/worker 端口为 48350/48351；创建前分别检查是否空闲。SSH 是 `root@216.243.220.178:14465`、本机 `~/.ssh/id_ed25519`、真实 known_hosts 文件。Pod 更换后重新核 endpoint 与 Gateway IP，不能沿用旧 IP 作为事实。

凭证新生成、文件0600，目录0700。GPU YAML 内含 worker token，放 `/root/runs`；网络云盘不保证 Unix chmod 语义。不要输出 token、不要把凭证提交 Git，也不要复用旧失效运行的 registration。

## 2. 固定源码与 task package

GPU 从 GitHub 拉取已发布提交；不要 scp 源码。仅在无运行占用的 checkout 中执行，例如：

```bash
git fetch origin worktree-harbor-modal-integration
git checkout --detach be8237ed9b8d22d06bc28195441aa7a28a23a8a0
git rev-parse HEAD
```

这是现有 checkout 的操作示例，新机器还需要 clone、依赖与模型准备。确认 pinned VERL/Uni-Agent/DSH 发布物，而不是重新安装最新包。认证使用 SSH deploy key 或外部凭证，不把 token 放进 remote URL/日志。

Task package 可通过现有 `examples.harbor.prepare_evolution_task` 生成，参数为 `--root`、`--source-dir`、`--source-manifest-sha256`、`--output`、`--agent-image-digest`、`--verifier-image-digest`、`--admission-version v2`。输入必须是固定原生 `dsh.redact-curriculum.v2` 的4/2数据。准备器校验原 prompt 的 checkout 路径，生产数据应在生成该 prompt 的 checkout 路径打包；只把 fixture 路径显式映射到 `/app/fixture.json`。

本轮已有上述 GPU/Mac package，不需重复生成。修改任何 task 文件会改变目录 SHA；运行前核两端完整 TaskRef，以及 `docker image inspect` 的实际镜像 ID。新的 agent/verifier 镜像需先构建/加载并通过 Docker smoke，再用于学生。

从 GPU package `manifest.json` 提取 `evolution_v2_binding`，保留 GPU 的 fixture/metadata 绝对路径并校验 TaskRef。不要把 Mac binding 路径直接部署到 GPU。

本轮只传五份配置/凭证：run-spec.json、registration-token、worker-token、evolution-v2-binding.json、training-manifest.json。以 `deployment-plan.json.transfer_map` 为准；传输内容不是可执行源码。传后校验权限与配置 SHA，禁止打印凭证。

## 3. GPU CPU 数据与配置准备

在固定 GPU checkout：

```bash
export PYTHONPATH="$PWD:$PWD/verl"
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m examples.harbor.prepare_m2_training \
  --run-spec-path /root/runs/harbor-evolution-m2-v2-r1-input/run-spec.json \
  --task-dir /root/runs/harbor-evolution-v2-package-r1/task \
  --output-dir /root/runs/harbor-evolution-m2-v2-r1 \
  --task-config-path /root/runs/harbor-evolution-m2-v2-r1/task.yaml \
  --registration-token-file /root/runs/harbor-evolution-m2-v2-r1-input/registration-token \
  --worker-token-file /root/runs/harbor-evolution-m2-v2-r1-input/worker-token \
  --evolution-v2-binding /root/runs/harbor-evolution-m2-v2-r1-input/evolution-v2-binding.json \
  --train-count 4 --heldout-count 1
```

输出 `train.parquet`、`heldout.parquet`、`task.yaml`、`launch.json`。同题 eval 只证明工程回归。`launch.json` 绑定 registration 和独立 audit 的 operator 参数；不要从学生 receipt 猜测评分版本或任务身份。

训练 manifest 的 `environment` 固定以下关键配置；现有文件是完整实例：

- 新 base + LoRA16/alpha16，无 `lora_adapter` 字段；`RESUME_MODE=disable`，`RESUME_FROM_PATH` 为空。
- `TOTAL_TRAINING_STEPS=2`、`TRAIN_BATCH_SIZE=2`、`PPO_MINI_BATCH_SIZE=1`、`ROLLOUT_N=4`、`VAL_ROLLOUT_N=1`、`DATA_SHUFFLE=False`。
- `MAX_PROMPT_LENGTH=8192`、`MAX_RESPONSE_LENGTH=1024`、`PPO_MAX_TOKEN_LEN_PER_GPU=9216`。RunSpec `max_tokens=512` 是 DSH 单 turn 预算，不能与 Gateway 累计响应预算混同。
- `SAVE_FREQ=1`、`TEST_FREQ=1`、`SAVE_LORA_ONLY=False`；`VAL_ONLY=False`。基础脚本固定训练前评估。
- `GPU_MEMORY_UTILIZATION=0.30`、actor/optimizer offload=True、layered summon=False、eager/free cache=True、rollout CPU offload=0、max_num_seqs=1。Gateway 与任务并发均为1。
- `CKPTS_DIR` 指向上表 `/workspace/uni-agent-g1/checkpoint/...`；日志、轨迹、含凭证配置指向 `/root/runs/...`。
- 外层 `wall_clock_seconds=2700`；controller deadline 两小时，不能提前于训练期限。

训练前对 checkpoint 父目录做独占1MiB写入+fsync探针后删除自己的探针文件，并确认可用配额至少约25GiB。探针成功只说明可写，网络盘 `df` 可能显示共享集群总量；它不代表本用户配额。不能为了训练删除未归档的历史模型。

## 4. Mac controller 与 GPU 命令预览

Mac 在相同固定源码 worktree，保持终端/监管进程可用：

```bash
PYTHONPATH=.:verl /private/tmp/harbor-h0-20260908/bin/python \
  -m deployment.services.harbor_run_controller \
  --run-spec /private/tmp/harbor-evolution-m2-v2-r1/run-spec.json
```

新 `controller` 根目录必须不存在。启动后 `unregistered` 是合法健康状态；真实 Gateway SessionHandle 出现后才注册端口并进入 `ready`。记录 controller PID、日志与 RunSpec SHA。

GPU 上在**继承训练 manifest 的 environment**后运行：

```bash
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m examples.harbor.train_m2_online_rl \
  --launch /root/runs/harbor-evolution-m2-v2-r1/launch.json --print-command
```

例如可用 Python `subprocess.run(argv, env={**os.environ, **manifest['environment']}, check=True)` 设置环境，避免手工遗漏配置。不要把 JSON 当 shell 脚本 source。预览会调用基础训练脚本的 print 分支，不启动 Ray/GPU。

预览必须看到 Harbor registration/postprocessor、`evolution_v2_binding`、n4/batch2/2steps，不能残留原生 DSH-only audit。当前路径键已可由真实 Hydra parser 保真解析。基础 print 分支仍省略部分实际参数（如 `trainer.default_local_dir`）；checkpoint 路径要另核 manifest 和实际训练日志，不能把预览当作全部最终参数。

## 5. GPU 启动、观察与停止

```bash
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m deployment.services.harbor_training_supervisor \
  --launch /root/runs/harbor-evolution-m2-v2-r1/launch.json \
  --manifest /root/runs/harbor-evolution-m2-v2-r1-input/training-manifest.json
```

保持工作目录为固定 checkout，`PYTHONPATH=.:verl`。这个入口自动加载训练 manifest，并对真实 controller 做预检/运行中健康检查，不能改成原生 M1 的 `health=lambda:None`。可靠前台终端可直接运行；后台由操作人以 detached owned process group 托管，记录启动 PID与日志，不重复拉起同一 run。

检查本次 `train.log`、`supervisor-result.json`、`exit-code`、controller registration/health/SSH日志、GPU进程与显存。单次GPU0%不能说明卡死；需要比较日志时间、模型加载、Gateway注册、任务进度。反过来显存占用也不能证明成功推理。

正常结束或2700秒上限由 supervisor 处理所属训练进程组。人工提前停止时，在拥有该作业的前台终端 Ctrl-C；后台则先核实 PID、启动时间、命令和 run 目录，再仅向该 run 的 supervisor 发送 SIGINT，等待其 finally 清理所属 child group。不要用全局 `pkill Ray`、`ray stop` 或关闭整个 Pod。先停训练并确认结束，再对本次 Mac controller 使用前台 Ctrl-C或身份核实后的SIGINT，让 asyncio finally 回收 worker/tunnel。

检查 `supervisor-result.json`、`controller-stop.json` 及本次容器/隧道是否消失。`controller-stop.json.cleanup_errors=[]` 也不自动证明所有容器清理；代码写出的 `docker_cleanup_proven=False` 需配合独立 Docker 检查。无法正常停止时不要盲目复跑，应记录残留进程身份再做定向处理。

## 6. 消费审计、参数证据与独立 reload

训练后在固定 checkout 执行：

```bash
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m examples.harbor.audit_m2_training \
  --launch-path /root/runs/harbor-evolution-m2-v2-r1/launch.json \
  --agent-log-dir /root/runs/harbor-evolution-m2-v2-r1/agent-logs \
  --rollout-data-dir /root/runs/harbor-evolution-m2-v2-r1/rollouts \
  --validation-data-dir /root/runs/harbor-evolution-m2-v2-r1/validation \
  --train-n 4 --validation-n 1
```

保存 JSON 输出作为证据，检查退出状态。审计重算 task/receipt/轨迹、真实 tokens/logprobs 和 trainer/TransferQueue 消费；部分奖励0.25与合法完成失败0分必须保留，恶意或不完整证据拒绝。组内奖励全相同时可能无学习信号。

通过 `deployment/checks/checkpoint_delta.py <step1-model.pt> <step2-model.pt> --output <report.json>` 检查实际张量有限、LoRA变化、base冻结；另核 optimizer step/moments 与训练指标。checkpoint 文件存在或退出0不足以证明真实更新。

独立 reload 必须新建 run/controller/spec/凭证/输出目录，保留原 TaskRef、镜像、verifier、模型、预算和源码。继续使用 Harbor prepare、supervisor 和 `train_m2_online_rl`，设置 `VAL_ONLY=True`、`RESUME_MODE=resume_path`、`RESUME_FROM_PATH=<原global_step_2绝对目录>`；不能裸调用原生 DSH reload wrapper 丢失 Harbor registration/audit。

保留4行train、batch2以兼容 checkpoint 数据加载器状态；这不表示 reload 会训练。新run checkpoint输出目录与原checkpoint分离。外层可设1800秒；证明实际加载目标权重、运行新eval session/receipt，无actor更新与新model checkpoint。调用上述 Harbor audit 时改成 `--val-only --validation-n 1`，省略 `--train-n` 与 `--rollout-data-dir`，其他路径换成 reload run。

## 独立环境可复建仍需完成

- 本轮真实学生 M2 的更新、消费、checkpoint及独立reload证据尚未齐备，不能提前勾选G1完成。
- 新Mac/Pod从空环境恢复的安装验收：固定 Python依赖、VERL/Uni-Agent、DSH Linux SDK/runtime发布物、模型snapshot与tokenizer哈希；现有venv路径不是安装交付。
- 当前两个 Docker 镜像的长期可下载发布物/registry位置、校验清单，以及从原始固定输入重新构建TaskRef的实测证据。本机已有image ID不代表另一台机器可拉取。
- 原生4/2数据及源manifest的可获取归档、可重建prompt根路径说明；`/root/runs`和Mac `/private/tmp`不是长期持久交付。
- 将脱敏的run配置/版本/验收报告与checkpoint发布或归档；凭证独立重建，不复制旧认证身份。
- 在独立新环境依说明复跑、确认checkpoint目录容量与网络配置、核容器/隧道退出。最后才称可复建全链路。

性能优化、Modal扩容、fully async以及更大场景课程均为后续工作；当前优先完成相同预算下可审计工程验收。
