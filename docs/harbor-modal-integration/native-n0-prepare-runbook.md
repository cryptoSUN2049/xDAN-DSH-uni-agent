# N0：课程准备与有界原生训练操作

本批交付 `examples/dsh/ops/prepare_native_rebuild.py`。它只执行CPU课程准备、严格比较和运行计划落盘，**不会启动训练/reload，也尚未自动执行整条验收流水线**。新环境安装、CUDA/DSH检查及模型身份验证先于本说明中的训练步骤。

## 准备器输入

在新GPU checkout `/workspace/rebuild/uni-agent-native-n0-r1`，由刚安装好的新venv Python运行。先从真实r4 launch-manifest计算SHA作为独立参数，不手工改写基线；新checkout commit必须是已推送并部署的完整40位SHA。

```bash
cd /workspace/rebuild/uni-agent-native-n0-r1
export PYTHONPATH="$PWD:$PWD/verl"
/workspace/venvs/uni-agent-native-n0-r1/bin/python \
  -m examples.dsh.ops.prepare_native_rebuild \
  --repository-root /workspace/rebuild/uni-agent-native-n0-r1 \
  --expected-revision <新checkout完整40位SHA> \
  --venv /workspace/venvs/uni-agent-native-n0-r1 \
  --runtime-executable /workspace/venvs/uni-agent-native-n0-r1/lib/python3.12/site-packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64 \
  --baseline-manifest /root/runs/dsh-redact-m1-v2-r4/launch-manifest.json \
  --baseline-manifest-sha256 sha256:<原r4实际文件SHA> \
  --output-dir /root/runs/native-n0-r1-prepare \
  --run-parent /root/runs \
  --checkpoint-parent /workspace/uni-agent-g1/checkpoint \
  --run-name native-n0-r1
```

命令中的runtime路径必须先通过新venv实际安装位置核实。输入外部SHA不是可以照抄的占位符；缺文件、SHA错、runtime/bundle不匹配、输出重复或业务差异均立即失败。

输出目录必须全新，与train/reload/checkpoint目录不能重叠或互为父子。prepare失败后保留该次目录诊断，不复用它再次尝试；新尝试用新名称。不能删除旧目录来绕过独占检查。

## 输出和严格等价

- `course-16-8/`：现有完整生成器和manifest CLI的输出。
- `course-4-2-v1/`：现有不可变选择器输出。
- `course-4-2-v2/`：现有v2版本器输出，固定原runtime与评分bundle。
- `train-launch-manifest.json`、`reload-launch-manifest.json`：各自完整环境、argv、新路径、代码身份与2700/1800秒上限。
- `plan.json`：准备状态、旧新输入来源、后续步骤与业务等价报告。

旧Parquet先验证manifest/hash，再从已验证bytes解析，避免后续重读另一版本。六条完整row逐条比较；只替换prompt中该条fixture的旧checkout绝对路径前缀，**没有跳过任何metadata字段**。fixture manifest也全量相等。报告明确打印 `rows_compared`、`changed_prompt_messages`、`absolute_path_replacements`、每条旧新path及次数；当前固定课程预期六条row、六个prompt message、十二处绝对路径替换。

新数据仍是同四条训练和两条公开同类holdout，不是新增数据或隐藏评估。底层旧manifest写入器保留历史source标签，权威新checkout SHA来自外层plan/launch-manifest；不要把那个旧标签当实际来源。

模型snapshot路径复用原r4，记录为共享模型缓存；准备器不会再次复制模型或宣称空缓存复建。安装来源、模型文件哈希和实际CUDA能力由N0安装/预检证据覆盖。

## 训练：使用已有 supervisor 函数

训练前必须：安装/DSH/CUDA预检通过，已与共享GPU的其他会话协调取得本轮使用时段、已核实本次GPU无其他作业，云盘实际可写且新增配额够保存两份完整checkpoint。训练用新运行目录与云盘checkpoint；不覆盖r4或既有模型。

以下Python片段在新checkout前台执行，可保存运行输出，但不能当作后台进程已经托管。`launch_path` 指train manifest；reload时只在前置审计全部通过后改为reload manifest。CLI没有虚构的 `--native` 选项；原生链路直接复用现有有界 `supervise` 函数，`health=lambda:None` 因为此处不使用Harbor controller。

```python
import json, os, subprocess
from pathlib import Path
from deployment.services.harbor_training_supervisor import supervise

launch_path = Path('/root/runs/native-n0-r1-prepare/train-launch-manifest.json')
launch = json.loads(launch_path.read_bytes())
repo = Path(launch['cwd'])
assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == launch['source_commit']
assert not subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
root = Path(launch['environment']['RUN_ROOT'])
root.mkdir(mode=0o700, exist_ok=False)
assert root.stat().st_mode & 0o777 == 0o700
result = supervise(launch['command'], repo, {**os.environ, **launch['environment']}, root,
                   lambda: None, wall_seconds=launch['wall_clock_seconds'])
raise SystemExit(0 if result['exit_code'] == 0 else 1)
```

`run_root.mkdir`是独占新run声明；再次运行相同名字会失败。监督器只控制自己的进程组；断开终端或发现超时先核日志/进程，不重复启动。训练期间不要更新checkout、venv、task config或数据。

## 必须按顺序验收，失败即停止

`plan.json.steps`中已列出现有audit/delta/reload argv。执行数组应使用 `subprocess.run(argv, cwd=repo, env=..., check=True)`，不经过shell拼接；输出报告路径为独立新文件。

1. train退出状态与checkpoint完整性。
2. `examples/dsh/ops/audit_qwen3_4b_online_rl.py <train-run> --output <train-audit.json>`核实际fresh轨迹/奖励与TransferQueue/trainer消费。
3. `deployment/checks/checkpoint_delta.py <step1 actor模型文件> <step2 actor模型文件> --output <checkpoint-delta.json>`核LoRA实际变化、base冻结及数值有限。计划中的文件名对应现有单卡checkpoint布局；文件不存在就停止，不猜别的checkpoint代替。
4. `deployment/checks/optimizer_delta.py <step1优化器文件> <step2优化器文件> --output <optimizer-delta.json>` 核实际step进展、AdamW moment有限及非零，保留已观察到的空state；再与训练日志交叉核对。只接受本项目产生的可信checkpoint，以CPU和weights_only=True读取，不支持任意下载pickle或通用优化器格式。
5. 前述全通过、训练GPU退出后，用 `reload-launch-manifest.json` 和同一supervise方式启动独立进程。它调用现有reload shell wrapper，保留4条train/batch2以加载数据加载器状态，设置VAL_ONLY=True并绑定本次global_step_2。
6. `audit_qwen3_4b_online_rl.py <reload-run> --partition val --output <reload-audit.json>`，确认新session/新评分，实际恢复本次权重、无额外训练/新model checkpoint和GPU释放。

不能因有文件或exit0继续跳过某个失败审计。当前脚本未自动编排以上执行与gate；后续若增加执行模式，应先把这些规则实现并测试，再声称“一条命令完成全链路”。

共享GPU说明：新venv只隔离依赖，不隔离GPU资源。nvidia-smi瞬间为空或0%不能证明已取得独占使用权；必须先协调其他会话，再执行CUDA探针、训练或reload。

2026-09-09最新优先级：用户澄清没有其他会话占用，00:45计算PID空。运行前仍核占用并仅管理自身进程，不额外引入人工协调前置。该N0新环境流程后置；四能力任务使用已验收环境优先推进。
