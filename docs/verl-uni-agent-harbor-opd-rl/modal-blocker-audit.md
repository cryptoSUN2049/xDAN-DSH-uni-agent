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
