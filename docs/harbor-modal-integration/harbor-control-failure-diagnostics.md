# Harbor 控制链路失败诊断增量

目标：把 SSH 退出与 HTTP 健康检查失败的两端时间线连接起来。只改诊断，不改 keepalive/HTTP timeout/重试/重连/终止策略。

文件：`deployment/services/harbor_run_controller.py`、`harbor_training_supervisor.py` 及两份对应 tests。

合同：controller-failure.json 新增 `failure_observed_at_unix` 与 `ssh_exit_codes:{control,model}`（进程未启动/仍运行时 null），读取真实 owned SSH process.returncode；时间是 monitor 观察时间，不冒充 OS 精确退出时刻。既有 reason/run/controller/spec 保留，GET status 不变。supervisor 健康失败新增私有 `health-failure.json`，包含 `phase:preflight|runtime`、`observed_at_unix`、`exception_type`，HTTPError 可附整数状态码、URLError 可附 exception reason 类型；不记录异常 message/repr、URL、headers、body、token、argv 或环境变量。runtime result 附同诊断对象，preflight 保持抛出原异常并禁止启动子进程。

测试先行：模拟 SSH returncode=255 与冻结 clock，检查失败文件真实字段且原 status 合同不变；真实短生命周期 supervisor 子进程验证健康异常仍终止；异常 message/HTTP URL/body 放哨兵 secret，检查序列化文件不存在这些字符串。成功路径无健康失败文件。CPU 后原 controller/supervisor 回归、Ruff check/format。无 GPU/网络故障注入、不提交。
