# uv 环境管理手册（verl-uni-agent-harbor-opd-rl）

更新：2026-09-16。继承自 `xDAN-DSH-MetaRSI/docs/main/uv-runbook.md` 与 `uv-training-design.md`，按本项目路径落地。原则不变：**持久卷是唯一长期资产根，uv 管 Python 用户态依赖，单一 freeze 快照是唯一版本来源，激活必须用 CUDA 运算和 import 证明。**

## 为什么要这套办法

2026-09-16 核实：此前通过 GPU 组件验证的 venv 建在 pod 本地 `/tmp/verl-uni-agent-harbor-opd-rl/envs/`，pod 重建后整个环境消失，`/workspace` 下同名目录只剩 6.8M 空壳。留下的只有 `runs/environment-freeze-vllm023.txt`（245 包）和 11G uv cache。任何放在 `/tmp`、`/root`、overlay 根分区的东西都会随 pod 丢失。

## 资产与职责

| 资产 | 位置 | 说明 |
|---|---|---|
| 项目根 | `/workspace/verl-uni-agent-harbor-opd-rl/` | RunPod Network Volume 挂载点下的独立根 |
| 源码 | `$ROOT/src/uni-agent`（含 `verl/`） | rsync 副本，无 `.git`；版本以 `runs/source-manifest-<sha>.json` 为准 |
| venv | `$ROOT/envs/<lane>/` | 每个 lane 一个目录；失效时新建 `<lane>-<n>`，不覆盖 |
| uv cache | `$ROOT/cache/uv/` | `UV_CACHE_DIR`，重建时复用 wheel |
| 锁 | 仓库 `deployment/versions/uv-lanes/<lane>.freeze.txt` | `uv pip freeze` 单一快照，含 `-e` 源码行 |
| 模型 | `/workspace/models/<name>-<rev7>/` | 固定 revision |
| 证据 | `$ROOT/runs/` | 日志、freeze、manifest、探针 JSON、checkpoint |
| 启动脚本 | 仓库 `deployment/bootstrap/uv-lane-bootstrap.sh` | 幂等重建 + 激活证明 |

宿主机与 RunPod 镜像提供 NVIDIA driver 与 CUDA 基础层（当前 driver 595.91.07，RTX PRO 6000 Blackwell 96GB）。不在 pod 内重装 driver。GPU wheel 自带 CUDA 用户态库。

## 当前 lane

| Lane | Python | 关键版本 | 用途 |
|---|---|---|---|
| `ua-verl-py312-vllm023` | 3.12.3（`/usr/bin/python3.12`） | Torch 2.11.0 / vLLM 0.23.0 / Transformers 5.8.0 / Ray 2.54.1 / peft 0.18.1 / TransferQueue 434f8c4 / **harbor 0.16.1 + modal 1.5.5（2026-09-16 加入；resolver 同时降了 openai 3.14→2.54、protobuf 7.36→6.33、websockets 17.1→15.0.1、importlib-metadata 9.0→8.9，`uv pip check` 兼容，GPU smoke 复验见 gpu-smoke-ws1-post-harbor.json）** | Uni-Agent 测试 lane，单卡组件验证已通过（r2/r3/r4）；上游 Harbor 路线用此 lane |

同一台机器上另有 MetaRSI 的 `/workspace/.venvs/metarsi-*-py311`（Torch 2.10 / vLLM 0.18.1 / Transformers 4.57.6）和 VERL 自身 uv.lock（vLLM 0.24 / Transformers 5.9）。三条 lane 不混称统一锁；正式训练前须为训练 lane 单独验锁。

## 每次启动的顺序

1. 核 SSH 端口（pod 重建后会变），`findmnt -T /workspace` 确认挂的是持久卷。
2. `nvidia-smi` 与 `ps` 查是否有本项目或其他项目进程在跑；不停别人的进程，不重复启动。
3. 核 `runs/source-manifest-*.json` 最新 sha 是否等于本地 HEAD，不等先 rsync。
4. 检查 `envs/<lane>/lib/python*/site-packages` 是否真有包；空壳不算环境。
5. 激活并做激活证明；通过后才能跑探针或训练。
6. 每次运行保存 run ID、命令、退出码、源码 sha、锁 sha256、freeze、GPU/driver、日志。

### 同步源码

```bash
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
rsync -rltz --delete \
  --exclude .git --exclude '__pycache__' --exclude .Codex --exclude '*.egg-info' \
  -e "ssh -p 30284 -i ~/.ssh/id_ed25519" \
  ./ root@157.157.221.177:$ROOT/src/uni-agent/
# 远端写 manifest
ssh -p 30284 -i ~/.ssh/id_ed25519 root@157.157.221.177 \
  "printf '{\"sha\":\"%s\",\"utc\":\"%s\"}\n' $(git rev-parse HEAD) $(date -u +%Y%m%dT%H%M%SZ) > $ROOT/runs/source-manifest-$(git rev-parse --short HEAD).json"
```

FUSE 卷不支持 chown，只能 `-rltz`，不能 `-a`。

### 重建 lane（venv 丢失或新 pod）

```bash
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
LANE=ua-verl-py312-vllm023 UV_VENV=$ROOT/envs/ua-verl-py312-vllm023-ws1 \
  bash $ROOT/src/uni-agent/deployment/bootstrap/uv-lane-bootstrap.sh
```

脚本做的事：拒绝 `/workspace` 之外的 venv/cache 路径；拒绝覆盖已有非空 venv；`uv venv` + `uv pip sync <lock>`；`uv pip check`；跑 CUDA 运算与 7 个关键 import；写 freeze 并与锁 diff；写 manifest JSON。所有输出在 `runs/uv-lane-<lane>-<utc>.{log,freeze.txt,manifest.json}`。

### 激活已有 lane

```bash
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
export UV_CACHE_DIR=$ROOT/cache/uv
source $ROOT/envs/ua-verl-py312-vllm023-ws1/bin/activate
python -c 'import sys; print(sys.executable, sys.prefix)'
python -c 'import torch; a=torch.arange(32, device="cuda", dtype=torch.float32); assert (a*a).sum().item()==10416; print(torch.__version__, torch.cuda.get_device_name())'
python -c 'import vllm, ray, transformers, peft, transfer_queue, verl, uni_agent; print("imports passed")'
```

### Modal 凭据

`~/.modal.toml` 从本机 scp 到远端 `/root/.modal.toml`（chmod 600）。放 `/root` 是有意的：pod 重建后会丢，需要重拷，但不落在共享网络盘、不进仓库。lane 内 `modal profile current` 应显示 `shootime007`。

## 修改依赖的规则

- 只允许两种途径改版本：改 `requirements-test.txt` 后在 lane 内 `uv pip install`，然后 `uv pip freeze` 覆盖仓库锁；或直接对锁做审阅过的编辑再 `uv pip sync`。两种都要在同一提交里更新本手册的 lane 表。
- `uv pip` 显式版本可能被项目 `tool.uv.override-dependencies` 覆盖；锁外 overlay 必须 `--no-config` 隔离并实际 `uv pip check` + import 验证，不能只信命令参数。
- 禁止合并历史分段锁（GPU/TQ/VERL 各一份）做恢复；MetaRSI 曾因此让 resolver 回退到无法导入的 datasets 2.2.1。
- `uv pip check` 有冲突时逐条处理，不能忽略全部输出。

## 禁止事项

- venv、cache、模型、证据放 `/tmp` 或 overlay 根分区。
- 覆盖已有 venv；覆盖失败现场的 runs 目录。
- 修改或停止 `/workspace/.venvs/metarsi-*`、`/workspace/skyrl`、`/workspace/metarsi-apus` 及其进程。
- 把"uv 可用 / import 通过 / 进程启动"当作训练验收。
