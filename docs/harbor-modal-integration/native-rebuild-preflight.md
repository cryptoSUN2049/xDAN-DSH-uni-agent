# N0 原生训练独立复建：只读前置调查

调查时间：2026-09-09 00:18—00:22（新加坡）；远端UTC为2026-09-08 16:18以后。仅执行SSH只读检查，没有安装、修改远端文件或启动GPU计算。此报告不是N0通过证据。

## 现场结论

- SSH：`root@216.243.220.178:14465`，已有 `~/.ssh/id_ed25519`。GPU计算进程查询为空。
- `/workspace/rebuild/uni-agent-g1-v2` HEAD为 `be8237ed9b8d22d06bc28195441aa7a28a23a8a0`。不能将本地最新HEAD或正在准备的修复当成远端已部署。
- Python 3.12.3；`uv 0.9.0`，可执行路径 `/usr/bin/uv`。venv记录的基础Python home是 `/usr/local/bin`。
- `/workspace/cache/uv` 约19G，包含 `archive-v0`、`wheels-v5`、`simple-v18`、git/sdist/editable构建缓存。发现torch、vllm、numpy、setuptools的索引路径。**这是缓存，不是独立 wheelhouse，也未证明所有新checkout离线构建依赖齐全。**
- `/root/.cache/uv` 仅12K，不是大包缓存。`/workspace/wheels`、`/workspace/releases`、`/workspace/uv-cache` 均不存在；不要写错cache路径后意外全量重下。
- 找到两份新版DSH发布wheel，实际SHA与固定发布记录相符，见后文。

## 旧/新 venv 的实际来源

| 项目 | `/workspace/venvs/uni-agent-fefb080` | `/workspace/venvs/uni-agent-rebuild-cf2d3f5` |
|---|---|---|
| 目录大小 | 约19G | 约19G |
| torch | 2.11.0+cu130 | 2.11.0+cu130 |
| vLLM | 0.24.0 | 0.24.0 |
| Transformers / Ray | 5.5.3 / 2.55.1 | 5.5.3 / 2.55.1 |
| NumPy | 2.4.6 | **2.3.5** |
| mistral-common | 1.11.3 | 1.11.3 |
| DSH SDK/runtime | 0.1.2a1 | **0.1.3a2** |
| uni-agent editable URL | `/workspace/src/uni-agent` | **`/workspace/rebuild/uni-agent-cf2d3f5`** |
| VERL editable URL | `/workspace/src/uni-agent/verl` | **`/workspace/rebuild/uni-agent-cf2d3f5/verl`** |

较新venv的 `uv pip check` 实际输出：257 packages，全部依赖兼容。注意它的 editable 并不指向当前 `uni-agent-g1-v2` checkout；原生r4通过 `PYTHONPATH` 和cwd显式指向新代码。这是旧环境的真实行为，不应复制到N0后宣称干净环境。

上游 `verl/uv.lock` 固定 **numpy 2.4.6**，而现已验证环境使用 **2.3.5**，是为适配mistral-common的既有记录修正。`deployment/bootstrap/install-verl.sh` 只做原锁sync和本项目no-deps editable安装，不自动补NumPy overlay或DSH wheel。单独执行它不能等同于恢复已通过r4的完整组合。

## 容量：已知事实与缺口

| 路径 | 只读观察 |
|---|---|
| `/` 容器盘 | 总32,212,254,720B，实际statvfs可用 **31,351,812,096B（约29.2GiB）** |
| `/workspace` | MFS `fuse` 网络挂载；statvfs为集群总量752,624,724,213,760B，可用140,726,621,962,240B，**不是账户剩余配额** |
| `/workspace/cache/uv` | 约19G |
| 两个训练venv | 分别约19G |
| `/workspace/models` | 约7.6G |
| `/workspace/uni-agent-g1/checkpoint` | 约17G |
| `/workspace/runs` | 约109G |

用户已将网络卷调整至500GB；本次只读审计没有quota/mfsgetquota工具，无法独立获取确切配额余额。目录du可能重复统计链接，不能把列表直接相加宣称总占用。也未执行写入探针，因为本任务限定只读。

N0建议新venv放 `/workspace/venvs/<new-name>`，显式copy cache安装约再需19G，两个checkpoint约17GiB；预留至少45—50GiB新增空间。容器盘仅用于小型私有配置/日志，不应悄悄替代云盘checkpoint。启动前由主线程做专属文件写入+fsync探针并核配额；不删除旧模型来掩盖空间未知。

## 最小复建准备命令（本轮未执行）

以下是已授权N0实施阶段的操作模板。主线程先确定并推送完整集成commit，替换占位符。不要在旧checkout中git pull，不克隆旧venv、不启用system-site-packages。

```bash
# 在已可用的仓库目录调用现有入口；目标必须全新。
bash deployment/bootstrap/checkout.sh <40位已推送集成commit> /workspace/rebuild/uni-agent-native-n0-r1
cd /workspace/rebuild/uni-agent-native-n0-r1
export DSH_TRAIN_VENV=/workspace/venvs/uni-agent-native-n0-r1
export DSH_UV_CACHE=/workspace/cache/uv
export UV_LINK_MODE=copy
export UV_PYTHON=/usr/bin/python3.12
export UV_OFFLINE=true
bash deployment/bootstrap/install-verl.sh
```

`checkout.sh` 从GitHub clone并初始化配对子模块。`install-verl.sh` 核VERL `fefb080262e1c015a0ea05f958822a6a512dc795`、tracked clean，再执行 `uv sync --frozen --extra fsdp --extra vllm`。UV缓存重用明确记作 **warm-cache新安装**，不能宣称从空缓存下载复建。若offline缺缓存，保存具体缺项和退出日志；只下载固定原锁/hash所需资产，不直接取消版本锁或复制旧site-packages。

新venv存在后，补已验证的NumPy版本和原DSH发布物：

```bash
UV_CACHE_DIR=/workspace/cache/uv uv pip install \
  --python /workspace/venvs/uni-agent-native-n0-r1/bin/python --no-deps numpy==2.3.5
UV_CACHE_DIR=/workspace/cache/uv uv pip install \
  --python /workspace/venvs/uni-agent-native-n0-r1/bin/python --no-deps \
  /workspace/artifacts/dsh-g1-v2-b236969/deepseek_harness_sdk-0.1.3a2-py3-none-any.whl \
  /workspace/artifacts/dsh-g1-v2-b236969/deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl
uv pip check --python /workspace/venvs/uni-agent-native-n0-r1/bin/python
```

前面导出的 `UV_OFFLINE=true` 仍生效；任何缺缓存应显式诊断。NumPy 2.3.5现在只有版本/现环境兼容记录，尚需固定实际选用wheel的URL/SHA及安装日志，才能形成闭合的字节锁。

两份本地DSH wheel本次已重新hash：

- SDK：`6c6a1a8f26b9030326447a8ed41c3ae6261a6b78e7fe61d72c7bf3ae21f03d6e`。
- Runtime：`59cc8ec59946afa572bfd0b9e6268d7380a4d00d1157d7dce6d2b2df86cf51ad`。

独立主机无这些文件时，从固定私有DSH Release `dsh-sdk-0.1.3a2-b236969-linux-x64`下载并核SHA。无需为N0重新build runtime；重建源码发布物是不同的验收工作。

安装后需要以下门：

1. 从checkout外、清除PYTHONPATH，检查 `uni_agent.__file__`、`verl.__file__` 和importlib.metadata direct_url均指向新checkout；检查SDK/runtime落在新venv。不能仅靠显式PYTHONPATH覆盖旧editable来源。
2. 比对torch/vLLM/Transformers/Ray/NumPy与DSH版本、runtime二进制SHA；输出完整已安装清单和包直接来源。
3. `uv pip check` 必须通过；额外包不能由“旧环境里有”推断新环境也有。
4. 新环境执行 `deployment/checks/gpu_smoke.py` 的实际CUDA前向/反向；它是待实施检查，不是此次只读调查结果。
5. 用新SDK做有界启动/退出和原生任务CPU回归，然后才启动两步训练。

## r4 路径迁移：不能只改 PYTHON_BIN

原生已通过输入是 `/root/runs/dsh-redact-m1-v2-r4/launch-manifest.json`，代码2df91d7。其环境应作为数值预算基线，但下列路径必须显式迁移：

| 字段 | N0处理 |
|---|---|
| cwd、source_commit | 新固定checkout与新完整commit |
| PYTHON_BIN、DSH_VENV、PATH | 新venv；runner_python=python须解析到相同venv |
| PYTHONPATH | 新checkout和新checkout/verl，不能残留旧路径 |
| MODEL_PATH | 可复用既有固定snapshot，但记录共享模型缓存及全部文件/配置身份 |
| DATA_ROOT/TRAIN_FILE/TEST_FILE/TASK_CONFIG | 使用从新checkout生成的独立数据目录 |
| RUN_ROOT/EXP_NAME、agent/rollout/validation/trace/result roots | 全新run；不继承旧输出 |
| CKPTS_DIR | `/workspace/uni-agent-g1/checkpoint/native-n0-r1` |
| DSH_SHA / runtime SHA / verifier bundle | 保持当前固定0.1.3a2及原v2评分，不暗升级 |

**原r4 prompt内直接包含 `/workspace/rebuild/uni-agent-g1-v2/.../redact-train-01.json`。**仅复制原Parquet会让新代码仍访问旧fixture，不能证明独立checkout可运行。最短办法是用既有三级准备器从新checkout重生相同场景，并记录唯一预期变化为prompt绝对fixture前缀及文件/manifest哈希：

1. 新checkout执行 `examples/dsh/ops/prepare_qwen3_4b_data.sh`，设置新 `DATA_ROOT`、`DSH_VENV`、`PYTHON_BIN`、`ENVIRONMENT_DIGEST=sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`，产生原16/8及manifest。
2. 新Python `-m examples.dsh.prepare_redact_curriculum --repository-root <新checkout> --source-dir <新16/8目录> --source-manifest-sha256 <实际hash> --runtime-executable <新venv实际runtime二进制> --output-dir <新4/2-v1目录>`。
3. 新Python `-m examples.dsh.prepare_redact_curriculum_v2` 使用同组参数名，source指上一步4/2-v1、output指新4/2-v2目录。
4. 比较原r4与新数据：scenario IDs、fixture bytes、所有业务metadata/reward规则相同；prompt只允许预期根路径映射。新task-config仍为v2 verifier，不能误用仓库默认v1 verifier YAML。

相对patch字符串 `examples/dsh/evolution.patch.yml` 与patch文件字节保持不变；patch-stack digest是有序路径字符串列表的hash，不是单个文件hash。不要为新checkout随意把相对patch改成绝对patch造成身份漂移。

训练保持两步、4train/2公开同类holdout、batch2/n4、8192/1024、LoRA16、单Gateway/单并发、2700秒。使用原生 `examples/dsh/ops/launch_qwen3_4b_online_rl.sh --foreground` 及有界supervise，不需Harbor controller。通过后新进程独立reload，再核完整审计/参数证据；这些均尚未执行。

## 仍需交付的N0证据

- 新checkout GitHub来源/commit/VERL子模块SHA、bootstrap日志、全新venv创建事实；旧路径在无PYTHONPATH下不被import。
- 原uv.lock与显式NumPy/DSH overlay的完整安装字节来源，warm-cache命中/缺项实录。`g1-v2-installed-packages.json`只记录版本，不是wheel哈希锁。
- 本次调查发现 `g1-deployment-lock.json`仍有旧Harbor任务及过时pending字段；新N0应有独立准确部署manifest，不能照抄其中状态当事实。
- 网络卷真实容量或配额缺口、写入探针；新环境/data/两步checkpoint的实际空间增长。
- 新环境CUDA/DSH预检、同任务训练更新、消费审计、独立reload与评估，以及脱敏归档/可获取路径。

上述结果只读调查已完成。N0“独立干净环境”若使用同一Pod、已有模型与uv缓存，应准确称为 **同主机新checkout/新venv的缓存辅助复建**；这与从空机器/空缓存完整恢复是不同验收层级。

## 实跑纠正
N0首次bootstrap在创建venv前退出：旧pyvenv.cfg的home=/usr/local/bin不能推导当前系统解释器路径。远端实际command -v python3=/usr/bin/python3，readlink旧venv/bin/python=/usr/bin/python3.12，版本3.12.3。模板已修正；失败日志install.log保留，新尝试install-attempt2.log。
