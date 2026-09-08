# 原生诊断 v1 与 DSH runtime 实测

日期：2026-09-08。现有 RTX PRO 6000；未创建新付费资源。

## 原生诊断：运行完成，有效更新未通过

代码 ca790bf，配对 VERL fefb080；模型与数据身份见 native-smoke-v1 manifest。
远端日志 `/workspace/reports/native-train-v1.log`，退出码文件为 0。
两个 optimizer step 均完成采样、评分、checkpoint 保存和验证：

| step | 组内真实奖励 | advantage / gradient norm | 留出准确率（2题） |
| --- | --- | --- | --- |
| 0 | 基线 | 不适用 | 0.5 |
| 1 | 4次全部0 | 0 / 0 | 0.0 |
| 2 | 4次全部1 | 0 / 0 | 0.5 |

CPU 实测比较 step1 与 step2 的504个同名 LoRA 张量，变化数为0。
证据 `/workspace/reports/native-train-v1-tensor-audit.json`。
因此不得宣称参数有效更新或能力提升；两题验证波动不能归因于训练。
没有独立 reload 验收，后续仍须完成。不得人为制造奖励差异。

退出阶段日志有 DataLoader worker killed 异常；主进程退出0，但不能据此忽略该异常。
当前 cgroup memory.events 的 oom/oom_kill 均0，尚不足以认定具体原因。
后续需核验 DataLoader 退出管理；原生支线有界，不无限增加步数。

## DSH：固定源码、正式 wheel、安装后运行通过

源码7840bced35ee07ebefbdce0106b56dbc00bdc3ef，Node24.20.0，pnpm11.7.0。
官方 Linux runtime 构建退出0；官方 build-python-release.py 成功生成两个0.1.2a1 wheels。
产物目录 `/workspace/artifacts/dsh-7840`；摘要见 deployment/versions/dsh-runtime-candidate.json。

复用已构建二进制后的实际命令：

```bash
cd /workspace/src/dsh-runtime
python3 scripts/build-python-release.py --package sdk --output-dir /workspace/artifacts/dsh-7840
python3 scripts/build-python-release.py --package runtime --platform linux-x64 --runtime-exe dist-exe/deepseek-harness-sdk-runtime-linux-x64 --output-dir /workspace/artifacts/dsh-7840
uv venv /workspace/venvs/dsh-sdk-7840
uv pip install --python /workspace/venvs/dsh-sdk-7840/bin/python /workspace/artifacts/dsh-7840/*.whl
cd /workspace/reports
timeout 180 /workspace/venvs/dsh-sdk-7840/bin/python /workspace/src/dsh-runtime/scripts/smoke-python-runtime.py --scenario sdk-minimal --installed-wheel
timeout 180 /workspace/venvs/dsh-sdk-7840/bin/python /workspace/src/dsh-runtime/scripts/smoke-python-runtime.py --scenario sdk-restart --installed-wheel
```

两项均输出 passed、退出0，使用官方 keyless 模拟端点，不调用付费模型。
独立SDK环境实际依赖：pydantic2.13.5、pydantic-core2.46.5、annotated-types0.8.0、typing-extensions4.16.0、typing-inspection0.4.4。
该安装验证不改变训练隔离环境，也不代表 DSH 已接入本次 GPU RL。

下一步：将已验证 wheel 接入训练环境，继续 M1 真实 DSH 任务及 fresh receipt 合同；M2 和可复建总交付仍未完成。
