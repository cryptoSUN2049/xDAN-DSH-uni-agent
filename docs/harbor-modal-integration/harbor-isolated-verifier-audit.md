# Harbor 0.16.1 独立 verifier 接入审计

日期：2026-09-08。只读审查本机固定 `/private/tmp/harbor-h0-20260908/lib/python3.12/site-packages/harbor`、现有 `DshHarborAgent` 与 H0 文件任务；本报告未改 Harbor 包、未运行模型或容器。下面是下一批可实施方案，不是已运行结果。

## 结论

Harbor 0.16.1 已实现独立 verifier 环境。最短严格路线是：**本仓一个限定单步骤任务的 `SingleStepTrial` 子类，移除 agent 阶段全部 host mounts，保留 Harbor 的独立 verifier 生命周期与评分逻辑；任务只显式传输 `/app/answer.txt`。** DSH bridge 在宿主采集日志，不依赖 agent 容器的 `/logs/agent` 挂载。

单加 TOML `environment_mode="separate"` 不足以满足“agent 不能修改 controller/评分目录”：上游 `_agent_env_mounts` 无条件挂载宿主 `verifier/`、`agent/` 和 convention artifacts，前两者没有只读标记。虽然 separate 阶段会停止 agent 并清空 verifier 目录，严格任务仍应去掉这些共享目录。

## 原生 API 与生命周期证据

下列路径相对固定 Harbor 安装目录，行号来自本次源码。

| 位置 | 已确认行为 |
| --- | --- |
| `models/task/config.py:471` | `[verifier].environment_mode` 支持 `shared/separate`；提供 `[verifier.environment]` 也隐含 separate |
| `models/task/verifier_mode.py:43` | dedicated env 优先取 verifier.environment；没有则复制 top-level environment |
| `trial/single_step.py:32` | agent run→同步日志→采集 artifacts→停止 agent env→独立 verifier；shared 顺序不同 |
| `trial/trial.py:523` | 上传收集的 artifacts 到新 verifier，再运行 VerifierFactory 生成的 verifier |
| `trial/trial.py:594` | dedicated env 由 Harbor 创建/start；finally 中 shield stop；使用独立 `__verifier__trial` session id |
| `trial/trial.py:635` | verifier 环境只增加宿主 verifier_dir mount；额外 runtime compose 清空，使用 tests/ 自有 compose |
| `trial/trial.py:648` | 单步骤 verifier 的构建上下文是任务 `tests/`，不是 `environment/` |
| `trial/trial.py:572`、`verifier/verifier.py:97` | separate 模式 `skip_tests_upload=True`，镜像必须已经拥有 `/tests/test.sh` |
| `trial/artifact_handler.py:189` | artifacts 上传回原 `source` 路径；destination 只影响宿主布局 |
| `trial/trial.py:337` | run 捕获普通异常后记录 result；返回结果不代表无异常 |
| `verifier/verifier.py:227` | 读取 reward.json 或 reward.txt 返回 VerifierResult；controller 仍须检查 exception、reward 数值与原始文件 |

## 本仓最小 Trial 子类

建议实现于 worker 所属模块，版本预检固定 Harbor 0.16.1。范围限本轮受控单步骤 DSH 文件任务；不作为通用 Harbor 替代实现。

```python
from harbor.models.task.task import Task
from harbor.models.trial.config import ServiceVolumeConfig, TrialConfig
from harbor.trial.single_step import SingleStepTrial


class IsolatedDshTrial(SingleStepTrial):
    @property
    def _agent_env_mounts(self) -> list[ServiceVolumeConfig]:
        return []


# task_dir/config 均来自 worker 已冻结的本地 allowlist。
task = Task(task_dir=task_dir)
trial = IsolatedDshTrial(config, _task=task)
result = await trial.run()
```

这使用上游固定版本的内部构造 seam，不修改 site-packages。`SingleStepTrial.__init__:20` 接受 `_task: Task | None` 并拒绝 multi-step task；`Trial.__init__:87` 要求已加载 `_task`。

**不能直接依赖继承的 `await IsolatedDshTrial.create(config)`。** `Trial.create:251–262` 硬编码返回 `MultiStepTrial` 或 `SingleStepTrial`，不会返回调用者子类。可在本仓另写限定 local/single-step 的工厂，或自定义 create；不需要复制 Trial.run 和 verifier 实现。

构造前由 worker 拒绝远程 task 引用、agent skills/MCP/extra_env、runtime mounts、extra compose，以及任务自带未经审计的 volumes/socket/privileged 配置。`_agent_env_mounts=[]` 只去掉 Harbor 注入的挂载，不能神奇删除 task-authored compose volumes。

## 为什么去掉 agent mounts 后 DSH 仍能工作

- `TrialPaths.mkdir:138` 在宿主创建 agent/verifier/artifacts 目录；不会要求它们同时挂入容器。
- [DshHarborAgent.setup](../../uni_agent/agents/dsh/harbor_agent.py) 在容器预检 SDK/runtime/helper，然后在宿主 `logs_dir/dsh` 创建证据目录。
- 同文件 run 通过 BorrowedHarborSandbox.read_file 取得 SDK `session.jsonl` / `result.json`，宿主写入 `agent/dsh`；不通过 `/logs/agent` 回传证据。
- Docker `start:832` 的静态 compose 不带卷，mount override 由收到的列表生成；`[]` 不增加挂载。`start:883` 只创建实际 writable mount targets，无 mount 时该步骤为空。
- `_download_agent_logs:450` 对 mounted provider 只做 prepare_logs_for_host；`_upload_agent_logs:477` 直接返回。Docker 的 `capabilities.mounted` 仍为 true，这两条通用同步路径不会替本子类下载容器 `/logs/agent`；本 DSH bridge 已在宿主写日志，所以不需要它们。
- 不覆盖 `_verifier_env_mounts`：独立 verifier 仍可把最终评分写回 host verifier/，该 mount 从未进入 agent 容器。

不要把这套日志假设推广到依赖容器 `/logs/agent` 的其他 InstalledAgent；其他 Agent 要单独补明确日志下载。

## 最小任务 TOML 与文件

在新自有任务目录复用 H0 instruction/solution/test 语义。agent 环境必须预装固定 DSH SDK/runtime 与同版本 `uni_agent.agents.dsh.runner`；现有 H0 ubuntu 镜像本身没有这些依赖。

```toml
schema_version = "1.3"
artifacts = ["/app/answer.txt"]

[agent]
timeout_sec = 180.0

[environment]
build_timeout_sec = 120.0
cpus = 1
memory_mb = 1024
storage_mb = 2048
workdir = "/app"
# 镜像/compose 使用已固定且完成平台预检的 DSH 发布物。

[verifier]
environment_mode = "separate"
timeout_sec = 30.0

[verifier.environment]
cpus = 1
memory_mb = 256
storage_mb = 1024
workdir = "/app"
```

必须显式提供 `[verifier.environment]`，避免继承 agent 的 DSH 预装镜像。`tests/Dockerfile` 用固定 Ubuntu digest，并 `COPY test.sh /tests/test.sh`；现有 H0 `test.sh` 已按固定字符串与 `/app/answer.txt` 比较，写 reward 1 或 0，可复用。Verifier 不执行 answer 文件。

`tests/docker-compose.yaml` 可沿用 H0 的 `services.main.network_mode: none`，独立评分无需联网；agent 环境使用已完成探针的模型隧道网络，不能继续照搬 H0 agent 的断网 compose。用 `environment.network_mode="no-network"` 会走 Harbor egress sidecar，与原生 compose `network_mode: none` 是两套机制，按已有验证选择并记录。

Harbor 自动追加 `/logs/artifacts` convention entry（`models/task/artifacts.py:62`），仅写 `artifacts=[answer]` 不代表关闭它。本子类没有 convention host mount，而 mounted provider 的采集快捷路径（`artifact_handler.py:291`）只看到宿主预建的空目录；本轮不要把它当有效输出来源。只验收 explicit `/app/answer.txt`，核对其他 convention 内容为空；后续若需要禁用 convention，必须显式测试，不靠配置名称推测。指定 `destination` 不改变 verifier 中的目标路径。

## TrialConfig 与 DSH Agent 接线

```python
config = TrialConfig.model_validate({
    "task": {"path": str(task_dir)},
    "trial_name": job_id,
    "trials_dir": str(private_trials_dir),
    "environment": {"type": "docker", "delete": True},
    "agent": {
        "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
        "model_name": student_model,
        "kwargs": {
            "gateway_base_url": mapped_session_gateway_url,
            "gateway_api_key": "EMPTY",
            "profile": "sdk-minimal",
            "runner_python": "/opt/dsh/bin/python",
            "workdir": "/app",
            "max_tokens_per_turn": 4096,
            "run_timeout": 180,
            "patches": frozen_container_patch_paths,
        },
    },
})
```

`AgentConfig.import_path` 在 `models/trial/config.py:61`；AgentFactory 在 `agents/factory.py:186` 将 model_name 与 kwargs 交给自定义类。上例路径、profile、patch 必须根据已预检镜像填写，不是本次确认已经存在的部署值。Gateway URL 保留原 session ID 路径；每个新 Trial 使用新的 Gateway session。`verifier.environment_mode` 属于 **task.toml 的 Task VerifierConfig**，不是 `TrialConfig.verifier`；后者只负责禁用、超时、env、日志/自定义 verifier 等运行选项。

## 下一批必须证明的事项

1. 无模型 oracle 正例与 nop/错误答案反例：独立 verifier 分别得到 1/0，结果无 exception，agent/verifier 两个环境均清理。返回对象或 CLI exit 0 不能代替这些检查。
2. 容器 mount inspection 证明 agent 无 host mounts、无 Docker socket、无任务源码/controller/评分目录；只有 verifier 获得自己的评分目录。宿主父证据目录保持私有。
3. 篡改测试：agent 伪造自己的 `/tests/test.sh`、`/logs/verifier/reward.txt`，答案错误时独立 verifier 仍为 0；host 测试与 controller 字节不变。
4. artifact 边界：正常文件、缺失、错误内容、目录伪装、symlink、超额字节分别处理。只把数据复制给 verifier，不执行候选脚本；缺失答案的正常零分与基础设施拷贝失败分开记录。
5. 完成上述 CPU 验收后再用同一子类接真实 DshHarborAgent/Gateway，收齐 DSH trace、agent result、Harbor TrialResult/verifier reward。controller 生成正式 receipt 与绑定 manifest；不把 Harbor JSON 重命名为 DSH receipt。

这条路线复用 Harbor 原生 lifecycle/verify，仅增加版本明确的小型挂载适配。当前只有源码可行性证据；实际 oracle、篡改验证和模型执行由下一实施批次完成。

## 实施与实测补充

本仓isolated_trial.py已实现正确工厂、配置限制与agent mounts=[]。首次真实Oracle暴露/logs/agent缺失导致shell重定向失败；适配器现先创建普通容器目录，不恢复host mount。

新run `/private/tmp/dsh-harbor-isolation-v2`：oracle=1、nop=0、伪造agent内/tests/test.sh与/logs/verifier/reward.txt后仍为0；三例exception均null、Docker inspect agent Mounts均空、宿主test.sh哈希不变。agent与verifier容器清理另行查询无残留。证据harbor-isolation-result.json；初次v1保留为失败。

运行入口deployment/checks/harbor_isolated_verifier_smoke.py，固定任务examples/harbor/m2-file-write，输入摘要deployment/versions/harbor-m2-task.json。本轮133项相关测试通过；不是模型rollout或训练证明。下载前artifact类型/大小与symlink边界仍需下一批实现；不据此给任意任务安全保证。
