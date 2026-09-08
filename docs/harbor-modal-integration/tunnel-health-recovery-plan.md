# G1 隧道恢复与失败处理增量

目标：保持固定 run 身份，在控制隧道退出时停止其所属训练；不自动重连正在运行的 rollout。

流程：GPU supervisor → 认证 GET controller run status → 固定 run_id/controller_id/spec digest + 状态；未注册但控制隧道健康允许初始化，ready要求model tunnel与worker就绪。连续有界健康失败终止自己启动的训练进程组，记录失败证据。Mac controller意外失联以非零状态退出并持久记录原因。

文件：deployment/services/harbor_run_controller.py 与现有controller测试；部署监督脚本（独立文件，待探针验证后落实）；本目录结果JSON及交接。

API：GET /v1/runs/{run_id}/status，沿用独立 registration bearer，不返回凭据；返回run_id/controller_id/run_spec_sha256/state/healthy。错误身份404，未授权401，断隧道healthy=false。不会绑定Gateway或修改任务。

验收：认证/身份/未注册/已注册/断线状态测试；控制器退出原因测试；本地双向HTTP探针；远程启动前健康检查。训练最终仍需token/reward/optimizer/reload独立验收。保活10秒/2次保持不变，未证实根因不靠调大数值掩盖。
