# G1 checkpoint 持久目录

项目名称固定为 `uni-agent-g1`。启动已有训练入口时设置：

```bash
export CKPTS_DIR=/workspace/uni-agent-g1/checkpoint/dsh-redact-m1-v2-r3
```

现有 `examples/dsh/train_qwen3_4b_online_rl.sh` 将此变量传给 `trainer.default_local_dir`。每次新实验用不同目录，VERL在其中生成 `global_step_1/actor`、`global_step_2/actor` 等。独立reload使用同一完整global_step目录。不得将指向/root的软链接冒充持久存储。

2026-09-08实测：云盘1 MiB write/fsync返回errno122。v2-r1首次torch.save失败；v2-r2本地checkpoint方案仍因Hydra向云盘写配置而在55秒退出。两个失败run均不算有效checkpoint。

恢复容量后才创建/使用新实验目录：预留至少25 GiB用户可用配额（两份完整checkpoint约17 GiB，另留运行空间），检查目录写入及挂载来源。全局df空闲不能证明用户配额足够。源代码继续GitHub精确commit部署；私有轨迹仍存/root/runs并独立归档。此文件只定义部署目录，不声称已恢复容量或迁移完成。

更新：用户已扩容至500 GB，新目标目录写入落盘通过；r3已启动，未清理历史产物。前述errno122为扩容前记录。
