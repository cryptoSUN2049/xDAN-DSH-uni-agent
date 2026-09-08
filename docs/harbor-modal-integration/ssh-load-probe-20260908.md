# 负载期 SSH 600 秒探针：实际复现超时

独立 owned SSH，原参数 ServerAliveInterval=10 / ServerAliveCountMax=2，无复用ControlMaster；远端每10秒输出UTC，预期60条，另每分钟独立SSH date。不操作GPU，不改旧run。与M1初始化负载时间重叠由主线程提供，探针本身不观测GPU利用率。

- 开始：2026-09-08 12:39:50.230 UTC；结束12:49:42.637 UTC。
- 实际592.401秒、SSH exit255，仅57/60条，stderr：`Timeout, server 216.243.220.178 not responding.`。
- 最后收包12:49:12.843 UTC，至退出约29.793秒；因此不能把10×2描述为实测精确20秒。
- 前10次每分钟新SSH均exit0。断后另一次新连接12:50:34.950→12:50:37.854 UTC，exit0。
- 未在故障瞬间同时发新连接，不能声称“故障同时短连接正常”；只能排除断后持续不可达。未区分路径抖动、Mac调度/休眠、服务端连接级停顿，不自动归因GPU负载。

原始证据：`/private/tmp/harbor-ssh-load-probe-20260908-203950/{report.json,stream.jsonl,ssh.stderr.log,short-probes.json,post-disconnect-short.json}`。结论：同类keepalive超时已复现，前9分钟正常不是全程通过。尚未调整参数或重连旧run。
