# 当前 M1 GPU 手动操作说明

## 范围与状态

这份说明用于**现有已部署GPU**复跑本轮DSH邮箱脱敏课程，复用已有脚本，不是全新主机的一键安装器。Harbor M2和最终干净环境复建尚未验收。

代码固定：`2df91d7de31b9ecacefeaad1c54dbea80028eead`；源码目录`/workspace/rebuild/uni-agent-g1-v2`；Python环境`/workspace/venvs/uni-agent-rebuild-cf2d3f5`。最新文档commit可以更靠后，不能因此在运行中更换GPU源码。

权威配置：`/root/runs/dsh-redact-m1-v2-r4/launch-manifest.json`。版本、课程、模型、LoRA16、两步训练、4train/2public holdout、所有预算都从此继承。仓库留存副本为`redact-m1-v2-r4-audit-bundle.json`中的`launch-manifest.json`字段。

## 手动启动同配置新实验

先SSH到GPU，确认`nvidia-smi`没有其他训练或reload占用。下面命令在前台运行，应放在可靠终端会话中；中断后先检查作业状态，不重复启动。运行名必须全新。

```bash
cd /workspace/rebuild/uni-agent-g1-v2
export PYTHONPATH="$PWD:$PWD/verl"
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python - <<'PYRUN'
import json, os, subprocess
from pathlib import Path
from deployment.services.harbor_training_supervisor import supervise
repo = Path.cwd()
source = Path('/root/runs/dsh-redact-m1-v2-r4/launch-manifest.json')
launch = json.loads(source.read_text())
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == launch['source_commit']
assert not subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
name = 'dsh-redact-m1-manual-01'  # 每次修改为全新名称
root = Path('/root/runs') / name
ckpt = Path('/workspace/uni-agent-g1/checkpoint') / name
assert not root.exists() and not ckpt.exists()
ckpt.parent.mkdir(parents=True, exist_ok=True)
probe = ckpt.parent / ('.write-probe-' + name)
try:
    with probe.open('xb') as f:
        f.write(b'0' * 1048576); f.flush(); os.fsync(f.fileno())
finally:
    if probe.exists(): probe.unlink()
root.mkdir(mode=0o700)
env = launch['environment'].copy()
for key in ['AGENT_LOG_DIR', 'ROLLOUT_DATA_DIR', 'VALIDATION_DATA_DIR', 'DSH_TRACE_ROOT', 'DSH_RESULT_ROOT', 'ALLOW_REUSE', 'PRINT_COMMAND']:
    env.pop(key, None)
env.update(RUN_ROOT=str(root), CKPTS_DIR=str(ckpt), EXP_NAME=name)
record = {**launch, 'environment': env}
(root / 'launch-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
result = supervise(record['command'], repo, {**os.environ, **env}, root, lambda: None, wall_seconds=2700)
raise SystemExit(0 if result['exit_code'] == 0 else 1)
PYRUN
```

1 MiB探针只验证当前可写，不保证全部容量足够；两份完整checkpoint约17 GiB，预留至少25 GiB配额。共享文件系统df不代表用户配额。

## 查看、审计与独立恢复

- `examples/dsh/ops/status_qwen3_4b_online_rl.sh <RUN_ROOT>`：状态；另看本次监督器的`supervisor-result.json`和`train.log`。
- `examples/dsh/ops/audit_qwen3_4b_online_rl.py <RUN_ROOT> --output <新报告路径>`：训练与验证轨迹审计。
- `deployment/checks/checkpoint_delta.py <step1模型pt> <step2模型pt> --output <新报告路径>`：LoRA变化、base冻结与有限数值。
- `examples/dsh/ops/reload_qwen3_4b_checkpoint.sh <global_step_2绝对路径> --foreground`：必须继承原launch manifest环境、重新设置全部输出根，不能裸用默认1条train；保留4条train/batch2供状态恢复。复用`redact-m1-runbook.md`的supervise模板，将run与checkpoint替换为本次目录，设置1800秒上限。
- reload后审计加`--partition val`。检查新session、两条fresh receipt、无训练指标、无新model checkpoint及GPU释放。
- 停止只针对该run拥有的进程；不要全局pkill Ray或停止整个Pod。后台监管作业按manifest内wall-clock上限结束。

验收清单：`../../tasks/harbor-modal-integration/acceptance-tracker.md`。exit0和保存文件不足以证明学习；当前r4已通过真实LoRA变化/optimizer/消费审计，reload两题均1，最终reload轨迹审计2/2通过，GPU释放。

## 显存与性能

已验证配置：GPU_MEMORY_UTILIZATION=0.30，CONCURRENCY=1，GATEWAY_COUNT=1，ROLLOUT_MAX_NUM_SEQS=1。0.30是推理引擎预算，不是整卡显存占用目标；训练actor、优化器及临时张量另占内存。

先保持此配置完成G1。性能实验单独命名并固定同任务/预算，对比每分钟有效任务数、tokens/s、耗时、峰值显存及失败率；优先小幅增加任务并发，再评估显存预算。不得同时改多个参数或以显存占满作为成功标准。Modal和全异步仍后置。
