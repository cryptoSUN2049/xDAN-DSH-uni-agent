# DSH finish-reason 固定runtime无GPU canary

2026-09-09。目的：验证固定0.1.3a2/b236 Linux runtime消费HTTP结束语义，不替代Gateway后端stop原因保真测试，不启动模型训练。

新增`deployment/checks/dsh_finish_reason_canary.py`与对应deployment测试。本机127.0.0.1临时HTTP服务仅响应受限请求，SSE分别返回stop普通文本、length普通文本、length且正文含完整可打印tool-call块（不提供结构化tool_calls）；SDK实际run→原事件→结束原因与文件副作用验收。每case全新session/home/工作目录，关闭shell插件，不增加Agent loop。

前置检查deployment lock中的b236源码/version、SDK安装version、实际runtime SHA256。用户必须指定新output与runtime；已有目录拒绝，报告/原trace权限0600。请求大小、数量、读socket与SDK初始化/请求/退出均有界，不访问外网，不读取模型凭据。

判据：stop→DSH completed且finished=true；length→max-tokens且finished=false。length完整打印tool块仍只是文本，要求无tool/call、无sentinel文件，不能将看似合法的工具JSON执行。新脚本不签发Task/RL准入回执。

wiring确认terminal abort经Gateway是HTTP409，JSON error.type=conflict_error，message为Backend generation was aborted; session cannot continue。可选abort409 case使用相同响应；要求观察实际409后SDK异常或明确非completed，禁止超时当作成功。SDK若仅抛异常没有返回事件，原样报告trace不可得，不伪造trace或宣称同等级事件验收。

TDD：先CPU反例（把length转completed、文本变tool调用、side effect、错runtime pin、复用目录、wire注入结构化tool字段），再实现；真实Linux执行由root在固定checkout发起。CPU测试假SDK与真实loopback wire分开，不能称runtime已经通过。

实现备注：复用既有`dsh_log_tool_smoke.py`已运行的SDK模型标识deepseek-v4-pro，但唯一endpoint为本机假服务，并不请求该模型。固定SDK的`client.py:620`订阅next使用无timeout队列；因此每case增加120秒SIGALRM墙钟上限，退出恢复原signal，已有外部alarm拒绝覆盖。SDK请求timeout不能冒充这个上限。abort可选项只认实际409加明确JsonRpcError或非completed运行终态；TimeoutError不算成功。

CPU验证：初始接口缺失RED后wire/结束原因/副作用/错pin/不可覆盖14项通过；补墙钟RED→GREEN后15项通过（包含4项真实loopback HTTP），尚未执行固定Linux runtime。命令：

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=.:verl python deployment/checks/dsh_finish_reason_canary.py \
  --runtime /absolute/path/to/pinned/dsh \
  --output /root/runs/dsh-finish-reason-canary-r1 \
  --include-abort
```

`--runtime`须填实际二进制文件，不是可变launcher；SHA与deployment lock相同。新输出目录必须不存在。默认不加`--include-abort`先验证三种stop/length案例；加入后四case逐一保留原事件或明确异常证据。主线程固定GitHub代码后再实际Linux验收，当前不宣称runtime通过。
