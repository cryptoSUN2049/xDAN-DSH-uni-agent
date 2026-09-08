# Harbor 控制传输短暂抖动：有界容忍

依据 ssh-load-probe-20260908.md：长连接592秒后实际keepalive timeout，随后短连接恢复。原因仍未区分，不能认定GPU负载导致。此增量只缓解短暂传输不可用，**不是根因修复**，不重连SSH、不复用已失败run、不恢复失效controller。

文件：deployment/services/harbor_tunnel.py、harbor_training_supervisor.py；对应CPU tests。现SSH ServerAliveInterval=10/CountMax=2改固定15/6，约90秒而非精确OS退出承诺。

预检仍首次健康检查失败即禁止启动训练。运行期仅明确TimeoutError、连接拒绝/重置/中断、ENETUNREACH/EHOSTUNREACH、临时DNS EAI_AGAIN（含URLError.reason真实异常类型）容忍。HTTPError任何状态、TLS证书/权限失败、未知异常、身份不符、malformed JSON、healthy=false均立即终止；不靠错误message字符串分类。

首个transport异常时记录monotonic时间，连续失败最多90秒；健康成功在窗内完成后重置。每次检查前后都核总wall-clock与失败窗，不把时间窗口延长为“每次错误再等90秒”。sleep取interval/剩余总预算/剩余失败窗最小值。已有HTTP读取timeout=5保持；同步检查不能被外部强制打断，实际终止最多还含一次有界HTTP检查及既有清理grace，不宣称纳秒硬实时。全部健康诊断不包含URL/token/message。恢复抖动计数进入supervisor-result，最终失败仍只有一个私有health-failure.json。进程组清理与exitcode规则不变。

测试先红：fake clock+owned fake process检查短抖动恢复、成功重置、90秒连续失败、较短总wall-clock优先、HTTP auth/identity/malformed立即失败、分类白名单；原真实子进程成功/失败清理与SSH取消回收回归。无GPU、无云部署、无网络故障注入。
