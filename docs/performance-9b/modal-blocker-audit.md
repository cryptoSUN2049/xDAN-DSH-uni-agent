# Modal 卡点归因复核

2026-09-15。结论：现有证据不足以确定 Modal 是训练未启动的根因，撤回此前确定性归因。

| 直接证据 | 能证明什么 | 不能证明什么 |
|---|---|---|
| modal-provider-smoke-r2.json：两个命令 return_code=0，passed=true，cleanup_confirmed=true | 该次真实 Modal 创建、执行、清理成功 | DSH Trial、Gateway、verifier reward、训练成功 |
| environment_backend.py validate_gateway_origin | 本项目 Modal 路径限制 HTTPS DNS hostname | Modal SDK 必须要求自有专用域名 |
| harbor_modal_ingress.py ModalIngressConfig | 本实现选择 named Tunnel UUID/凭据 | Cloudflare 是唯一可用路由 |
| harbor_run_controller.py registration 路径先 model.start，再 ingress.start，再 worker_factory | 当前实现有入口启动前置步骤 | 实际运行已经失败于该步骤 |
| 本轮 SSH banner exchange timeout，exit255 | 未成功取得当前远端状态 | GPU 空闲原因、训练进程有无或 Modal 网络失败 |

本地检索到 Modal 单元/集成测试及 provider smoke 日志；未取得完整训练失败于 ingress 的运行日志。测试名称含 Modal 或历史 red 测试不能当作生产运行故障。其他项目的 launch 文件不能当作本链路已备妥输入。

下一步验收顺序：
1. 恢复 SSH 后查本项目进程、源码版本、实际启动命令和最近日志。
2. 检查并准备本链路 task/image/RunSpec/数据，执行真实模型 preflight。
3. 从实际 sandbox 发起受控 Gateway 请求，保留 DNS/TLS/HTTP 与 session 路由结果，再归因网络问题。
4. 跑完整 Trial 与 verifier，然后连接 rollout/update；只有日志明确显示失败阶段，才能报告该阶段为卡点。

专用域名不是需要用户先补齐才能继续检查的已证实外部阻塞。单卡可用于较小范围训练验证；separate_async 分卡及独立 Teacher 的角色 GPU 要求另行验收。

## SSH 恢复后的实际观测（2026-09-15 12:52 UTC）

- 单张 RTX PRO 6000，GPU utilization=0%，memory.used=50241 MiB。下一次 compute-app 查询显示 PID39035 `VLLM::Worker` 占50232 MiB。这是瞬时采样，不是持续利用率统计。
- 可见推理主进程 PID34897 为 `/workspace/.venvs/metarsi-apus-py311/bin/python ... parallel_infer_verl.py`；Ray PID35590 同属该环境。没有在本次进程筛选中发现本分支 main_ppo、Controller 或 FSDP probe 进程。尚不能仅凭名称确认每个 GPU 子进程的父子归属。
- 本分支 `/workspace/verl-uni-agent-harbor-opd-rl/runs` 的全部十个 `.log` 均为环境安装、组件回归或 fsdp-lora 探针；未见正式 Harbor RL 训练日志。
- 在本分支远端目录 maxdepth=6 检索 launch.json、parquet、training-preflight.json、registration-intent.json、receipt.json，无匹配。不能排除其他路径或更深层有文件，但已检查的运行目录没有可直接使用的启动输入。
- resume-r4 日志末尾明确 `passed=true`、`scope=single_gpu_native_export_component`，只完成两步组件更新。
- 本地历史 Controller preflight JSON 明确 `actual_gateway_used=false`、`mock_ssh_returncode=0`，不能作为真实 Gateway 连通证据。
- 当前跟踪的 `deployment/versions/harbor-execution-image.json` 为 `registry_published=false`。这证明该清单未记录发布完成，不等于所有其他镜像都未发布。

结论：当前证据定位到本分支正式训练启动准备尚未交付/运行的缺口；没有证据显示正式训练已经启动后卡在 Modal。服务器存在其他项目的推理作业，不停止、不复用其 Ray 或模型服务。下一步先准备本分支真实 launch/task/data 和部署版本，再验收 Gateway/Trial；双卡并行验收另行安排。
