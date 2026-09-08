# SSH 15秒×6 保活复测：单次600秒窗口无故障

独立 owned SSH连接，无ControlMaster复用；ServerAliveInterval=15、ServerAliveCountMax=6。远端仅每10秒输出UTC，共60次；本机记录收取时间，并每分钟新SSH date。未操作GPU、未改源码或原连接。与 `/root/runs/dsh-redact-m1-v2-r1` 启动时间重叠，训练负载状态由主进程证据确认，本探针不采集GPU指标。

结果：

- 2026-09-08 13:21:39.259 UTC → 13:31:42.871 UTC（新加坡21:21:39→21:31:42）。
- 总elapsed603.629秒（包括SSH初始化与最后短连接收尾）。
- 长连接SSH exit0，60/60条输出；收取间隔9.910–10.110秒。
- 11次独立短连接均exit0、stderr空；长连接stderr0字节。
- 原始证据 `/private/tmp/harbor-ssh-load-probe-15x6-20260908-212139/{report.json,stream.jsonl,short-probes.json,ssh.stderr.log}`。

比较：旧10×2窗口于592.401秒exit255、57/60条，曾实际复现server not responding。新15×6本次窗口没有长间隔，因此不能证明它容忍了同等网络中断，也不能证明调参解决根因。两个窗口时间不同、网络负载没有受控，不能作参数改善的因果实验。可确认：当前这一次600秒连接完整通过，未重连、未掩盖失败、没有运行模型或训练。
