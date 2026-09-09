# 原生训练工程：人工 SSH 复跑操作手册

更新：2026-09-09。目的：在现有 GPU 上，按与本轮相同的固定组件与任务合同，重新跑一轮训练，再独立加载 checkpoint、执行评估。**工程正确闭环不要求本轮提分**；真实消费、有效更新与评估产出不可省略。

验收逐项勾选见 [native-engineering-acceptance.md](native-engineering-acceptance.md)。本手册复用现有已安装环境，不是全新主机安装验收；四能力整体也尚未全部训练通过。

## 1. 当前路径与证据边界

```text
12题 context 文件证据课程（12 train / 4公开 dev）
  → Uni-Agent 调度 DSH SDK/runtime（DSH唯一工具执行循环）
  → Gateway 保存真实 token / mask / logprob
  → 独立 verifier、回执、完整组准入
  → TQ / VERL sync GRPO 更新 LoRA
  → /workspace 保存完整 checkpoint
  → 独立新进程加载 checkpoint
  → 新 DSH 会话执行4题评估 → 新轨迹、回执及消费审计
```

这是在线 RL，没有 SFT、教师 API、Harbor、Modal。context 任务是文件证据诊断，不能直接称已验证模型上下文窗口切换。记忆 A/B 两族已真实评估通过，但记忆训练接线仍待 GPU；RSI 也不能按本 context 结果宣称完成。

已完成母实验 `context-v2-curriculum-r1`：12有效batch、48消费、11唯一题、6步非零梯度；step6→12全部504 LoRA变化、399 base冻结。D3合法执行错误被评分合同拒绝，D2补采；不能写成12题全部覆盖。dev严格成功0/4，不影响“有评估产出”，但不构成能力提升。详见 [课程报告](context-v2-curriculum-r1-result.md)。

最新独立reload `context-v2-curriculum-r1-reload-step12` 已470.012秒exit0：实际从step12加载model/optimizer/RNG/lr_scheduler，4/4新val组消费审计true，无新增训练消费或checkpoint文件（输出目录为空）；评估均值0.39796875、strict0/4。完整报告与归档由后续交接链接追踪。

## 2. 为什么目录冲突

实际调用顺序是 `reload_qwen3_4b_checkpoint.sh → launch_qwen3_4b_online_rl.sh → train_qwen3_4b_online_rl.sh`。

1. 外层 launch 先 `mkdir RUN_ROOT`，写 command.txt、run-manifest.json。
2. 内层 train 才识别 `PRINT_COMMAND=1`，打印命令并退出0。
3. 外层把这个退出0记成completed；此时没有模型执行证据。
4. 独立 supervisor 的 `assert not run.exists()` 发现目录已存在，正式运行被拦下。

不是 CUDA 安装错误，也不是用户文件冲突。根因是“打印模式的副作用”与“新运行目录检查”相撞。首次PID178761因此未加载模型；两份打印证据保留在 `/root/runs/context-v2-curriculum-r1-reload-step12-print-command-evidence`；重试PID178933已进入真实checkpoint加载。

操作原则：不要使用正式RUN_ROOT打印命令；只读查看JSON命令清单即可。必须做打印预检时，所有输出路径使用独立scratch身份。不要用ALLOW_REUSE绕过检查，不删除旧run、不把打印manifest当训练证据。当前GPU源码未为此升级；本手册启动路径直接绕开该副作用。

## 3. 登录与只读预检

在 Mac 终端：

```bash
ssh root@216.243.220.178 -p 14465 -i ~/.ssh/id_ed25519
```

随后所有命令在 GPU 主机执行。先只读查看，不要抢占正在运行的本轮reload：

```bash
nvidia-smi
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
cd /workspace/rebuild/uni-agent-native-n0-r1
git rev-parse HEAD
git -C verl rev-parse HEAD
git status --short
```

必须是：

| 组件 | 本轮实际固定值 |
|---|---|
| GPU集成源码 | d3084f2a771804f011c4e641ecf0986c7166bc86 |
| Uni-Agent上游基线 | 89733ec81a69c3cc93ac90479de7ea7f01e51c1f |
| 配对VERL | fefb080262e1c015a0ea05f958822a6a512dc795 |
| DSH源码 | b2369692ea530007075ebcd18d39fdba0bbd3982 |
| SDK / runtime安装版本 | 0.1.3a2 / 0.1.3a2 |
| Python环境 | /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python |
| 模型 | /workspace/models/Qwen3-4B-1cfa9a7 |
| 模型revision声明 | 1cfa9a7208912126459214e8b04321603b3df60c |

文档所在分支 `worktree-harbor-modal-integration` 的 HEAD 更靠后，**不要为了读取新版文档而 git pull 覆盖正在运行的GPU源码**。此次为既有云盘环境结果复跑，不声称从GitHub独立验证全部模型权重来源。另开主机部署参阅deployment目录及版本锁，不能省略安装验收。

## 4. 用同一模板启动训练，再启动独立reload

建议在可保持连接的终端中前台执行下面代码，监督器有墙钟限制；若使用tmux，先确认主机已安装。断线后先核实原进程，不直接重跑。本模板启动真实GPU任务；仅在GPU空闲时执行。

首次 `MODE='train'`、`NAME` 使用全新名称。训练完成且审计更新通过后，再运行相同模板：改成 `MODE='reload'`，换一个全新NAME，并将CHECKPOINT指向刚训练的global_step_12。不要同时跑两份。

```bash
cd /workspace/rebuild/uni-agent-native-n0-r1
env -u PYTHONHOME -u PYTHONPATH -u RAY_ADDRESS -u PYTORCH_CUDA_ALLOC_CONF \
 CUDA_VISIBLE_DEVICES='' /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python - <<'PYRUN'
import hashlib, json, os, pathlib, subprocess, sys

MODE = 'train'  # 第二次改为 'reload'
NAME = 'context-manual-train-01'  # 每次换新；reload也必须不同名
CHECKPOINT = '/workspace/uni-agent-g1/checkpoint/context-manual-train-01/global_step_12'
repo = pathlib.Path('/workspace/rebuild/uni-agent-native-n0-r1')
python = '/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python'
assert MODE in ('train', 'reload')
assert NAME and NAME[0].isalnum() and len(NAME) <= 60 and all(c.isascii() and (c.isalnum() or c in '-_') for c in NAME)
assert subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip() == 'd3084f2a771804f011c4e641ecf0986c7166bc86'
assert subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo/'verl', text=True).strip() == 'fefb080262e1c015a0ea05f958822a6a512dc795'
assert not subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'], text=True).strip(), 'GPU正在使用，先核实归属'
# 复用实际课程审计清单；只读，不执行其旧run命令。
reference = json.loads(pathlib.Path('/root/runs/context-v2-curriculum-r1-plan/preparation-audit.json').read_text())
sha = lambda p: 'sha256:' + hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
for path, expected in reference['source_hashes'].items():
    assert sha(path) == expected, path
assert sha(reference['runtime']['path']) == reference['runtime']['sha256']
assert sha(pathlib.Path('/workspace/models/Qwen3-4B-1cfa9a7/config.json')) == reference['model_config_sha256']
run = pathlib.Path('/root/runs') / NAME
data = pathlib.Path('/root/runs') / (NAME + '-data')
ckpt = pathlib.Path('/workspace/uni-agent-g1/checkpoint') / NAME
ray = pathlib.Path('/tmp') / ('dsh-' + hashlib.sha256(NAME.encode()).hexdigest()[:12])
for p in (run, data, ckpt, ray):
    assert not p.exists() and not p.is_symlink(), f'需要新路径: {p}'
if MODE == 'reload':
    assert pathlib.Path(CHECKPOINT, 'actor').is_dir()
sys.path[:0] = [str(repo), str(repo/'verl')]
from examples.dsh.capabilities.prepare_context_training_v2 import prepare
from deployment.services.harbor_training_supervisor import supervise
manifest = prepare(repository_root=repo, output_dir=data, run_id=NAME,
    runtime_executable=reference['runtime']['path'],
    environment_digest=reference['runtime']['sha256'], runner_python=python, run_root=run)
assert manifest['counts'] == {'train': 12, 'validation': 4}
env = dict(reference['environment'])
env.update(manifest['environment'])  # 新任务配置和所有阶段输出根
for key in ('PRINT_COMMAND','ALLOW_REUSE','RAY_ADDRESS','PYTHONHOME','PYTORCH_CUDA_ALLOC_CONF'):
    env.pop(key, None)
env.update(PATH=str(pathlib.Path(python).parent)+':/usr/local/bin:/usr/bin:/bin', HOME='/root',
    PYTHONPATH=str(repo)+':'+str(repo/'verl'), PYTHON_BIN=python,
    DSH_VENV=str(pathlib.Path(python).parent.parent), CUDA_VISIBLE_DEVICES='0',
    MODEL_PATH='/workspace/models/Qwen3-4B-1cfa9a7', MODEL_LICENSE_APPROVED='1',
    RUN_ROOT=str(run), CKPTS_DIR=str(ckpt), EXP_NAME=NAME, RAY_TMPDIR=str(ray),
    OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', TRAINER_MODE='sync',
    TRAIN_BATCH_SIZE='1', PPO_MINI_BATCH_SIZE='1',
    ROLLOUT_N='4' if MODE=='train' else '1', VAL_ROLLOUT_N='1',
    TRAIN_MAX_SAMPLES='12' if MODE=='train' else '1', VAL_MAX_SAMPLES='4',
    TOTAL_TRAINING_STEPS='12' if MODE=='train' else '1',
    SAVE_FREQ='6', TEST_FREQ='6' if MODE=='train' else '1',
    VAL_ONLY='False' if MODE=='train' else 'True',
    RESUME_MODE='disable' if MODE=='train' else 'resume_path',
    RESUME_FROM_PATH='' if MODE=='train' else CHECKPOINT)
probe = subprocess.run([python,'-c',
    'from examples.dsh.capabilities.context_verifier_v2 import bundle_digest;print(bundle_digest())'],
    cwd=data, env={**env, 'CUDA_VISIBLE_DEVICES':''}, capture_output=True, text=True, check=True)
assert probe.stdout.strip() == manifest['verifier_bundle']['sha256']
if MODE == 'train':
    command = ['bash', str(repo/'examples/dsh/ops/launch_qwen3_4b_online_rl.sh'), '--foreground']
else:
    command = ['bash', str(repo/'examples/dsh/ops/reload_qwen3_4b_checkpoint.sh'), CHECKPOINT, '--foreground']
command += ['trainer.total_epochs=1', 'trainer.test_freq='+env['TEST_FREQ'],
            'trainer.default_local_dir='+str(ckpt)]
run.mkdir(mode=0o700); ray.mkdir(mode=0o700)
supervision = run/'supervision'; supervision.mkdir(mode=0o700)
(run/'human-launch-plan.json').write_text(json.dumps(dict(mode=MODE, environment=env,
    command=command, reference=reference['integration_head']), indent=2)+'\n')
os.environ.clear(); os.environ.update(env)
result = supervise(command, repo, env, supervision, lambda: None,
    wall_seconds=7200 if MODE=='train' else 3600, interval=5, grace=30)
print(json.dumps(result))
raise SystemExit(0 if result['exit_code']==0 else 1)
PYRUN
```

这是根据已运行模板整理的人工入口；底层prepare/ops/supervisor已真实使用。本文代码块做语法/接口核对，**尚未以这个全新手工run名字再跑一遍**，不把文档检查当新增GPU验收。它依赖上述现存reference JSON；若云盘缺失该清单，先恢复归档/重新准备，不盲用默认值。prepare默认VAL_ONLY=True/两步，模板已显式覆盖，不能只source training.env就认为执行了12步。

## 5. 第二个终端：像工程师一样观测

把RUN替换为上一步NAME对应目录：

```bash
RUN=/root/runs/context-manual-train-01
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
tail -n 35 "$RUN/supervision/train.log"
cat "$RUN/run-manifest.json"
# 结束后才存在：
cat "$RUN/supervision/supervisor-result.json"
```

| 阶段 | 应观察到 | 尚不能得出的结论 |
|---|---|---|
| 版本/输入预检 | 清单hash一致；新目录；导入正确checkout | PID不代表启动成功 |
| Ray/VERL启动 | 日志持续新增；worker创建；GPU可能暂为0 | 0%单点不证明卡死 |
| 权重/引擎初始化 | 显存增长；加载日志；ready to fit | 显存占用不代表正在更新 |
| DSH采样 | 新session/工具轨迹/回执 | 有token不等于已消费 |
| 更新 | GRPO组、adv/梯度、actor指标与checkpoint | 所有同分组可能零梯度 |
| reload | Loaded model/optimizer/RNG/lr_scheduler指向正确step | 配置显示resume路径不等于加载完成 |
| 独立评估 | 4新val组、fresh回执、实际消费、新指标 | 不要求比基线更高，但必须如实报告 |

日志暂静默先核CPU/磁盘读取、worker、最后时间戳和当前阶段；不要根据固定一分钟阈值重启，也不要全局ray stop/pkill。supervisor只负责自己的进程组；结束后另查GPU是否释放。

## 6. 训练后的审计命令

```bash
cd /workspace/rebuild/uni-agent-native-n0-r1
export PYTHONPATH="$PWD:$PWD/verl"
RUN=/root/runs/context-manual-train-01
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  examples/dsh/ops/audit_qwen3_4b_online_rl.py "$RUN" --output "$RUN/manual-audit.json"
```

退出0：全组符合该审计器严格标准。退出1：报告存在不合格组，逐项检查，不能改eligible或忽略退出码；若组被安全拒绝且未消费，分别记录“采样失败隔离正确”和“严格全组审计未通过”。退出2：输入/manifest不可读，先修复审计输入。母实验原报告false保留，不能因为后续refill成功而改成true。

张量差异检查（单卡rank0完整checkpoint）：

```bash
CK=/workspace/uni-agent-g1/checkpoint/context-manual-train-01
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python deployment/checks/checkpoint_delta.py \
 "$CK/global_step_6/actor/model_world_size_1_rank_0.pt" \
 "$CK/global_step_12/actor/model_world_size_1_rank_0.pt" \
 --output "$RUN/manual-checkpoint-delta.json"
```

输出文件必须新建；至少LoRA有变化、base不变、数值有限。还需结合非零adv/梯度及optimizer状态；单独weight变化可能含动量/weight decay，不能独立证明新任务学习信号。完整JSONL指标在checkout的 `dsh-context-v2/<EXP_NAME>.jsonl`。本轮step6→12结果见课程报告。继续使用现有单卡AdamW状态审计：

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python deployment/checks/optimizer_delta.py \
 "$CK/global_step_6/actor/optim_world_size_1_rank_0.pt" \
 "$CK/global_step_12/actor/optim_world_size_1_rank_0.pt" \
 --output "$RUN/manual-optimizer-delta.json"
```

要求passed=true、step推进、moment有限且变化；该工具只支持本项目实际单卡AdamW格式，不是任意optimizer格式的通用审计器。

## 7. 独立reload完成后的验收

用第4节同模板重新prepare，MODE=reload、全新NAME、CHECKPOINT指向自己的训练产物。结束后：

```bash
RUN=/root/runs/context-manual-reload-01
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
 examples/dsh/ops/audit_qwen3_4b_online_rl.py "$RUN" --partition val --output "$RUN/manual-reload-audit.json"
```

必须保存：正确step的实际加载日志、4个新评估会话、fresh verifier receipts、token/回读消费审计、reward与严格成功率。reload不应有新的训练update或新model checkpoint。随机采样允许得分波动；“结果可重新执行”不同于“逐token完全一致”。本阶段不以提分作为工程成功条件。

## 8. 存储与交接

- checkpoint：`/workspace/uni-agent-g1/checkpoint/<NAME>/`，不得落容器根盘。
- 当前私有运行证据：`/root/runs/<NAME>`，容器丢失可能丢失；完成后归档到`/workspace/reports/`并记录sha256。
- 数据包也包含绝对路径与run身份，不通过简单复制旧receipt复用；新run重新prepare。
- Network volume配额由RunPod控制面核对；共享文件系统df可能显示整个集群容量，不代表个人剩余额度。
- 不把API key/PAT/private key打包进归档或Git。代码和报告每个完成环节commit/push前通过Ruff双门；大checkpoint不提交Git。
- 当前状态与后续阶段：[handoff](../../tasks/harbor-modal-integration/handoff.md)、[active goal](../../tasks/harbor-modal-integration/active-engineering-goal.md)。
