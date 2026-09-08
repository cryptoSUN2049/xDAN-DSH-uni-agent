# 最新 DSH Session v2：真实 SDK 情景验证

2026-09-08；本次范围是本机 built CLI 与最新 Python SDK 的真实运行集成，模型响应来自官方脚本的 loopback mock。没有付费模型请求、GPU 训练、DSH 仓库修改或快照更新。

## 结果

| 官方情景 | 进程退出码 | 日志末行 | 实际覆盖 |
| --- | --- | --- | --- |
| `sdk-minimal` | 0 | `smoke-python-runtime: sdk-minimal passed` | SDK 驱动真实 runtime；shell 两次调用保持计数状态；真实编辑器写文件；最终响应、持久 session 版本与模型可见快照匹配 |
| `sdk-restart` | 0 | `smoke-python-runtime: sdk-restart passed` | 两次独立 SDK/runtime 生命周期、两个独立 session；精确两次 mock 请求；最终响应、事件类型、通知类型、模型请求和两个 Session v2 持久记录快照匹配 |

测试前后 DSH HEAD 均为 `b2369692ea530007075ebcd18d39fdba0bbd3982`，测试后 `git status --short` 为空。测试采用现有构建产物 `apps/cli/lib/bin.js`，并没有重新构建或验证产物逐文件与 HEAD 的可复现对应关系。构建证据见同目录 `dsh-latest-architecture-impact-audit.md`。

## 可复查命令与入口

DSH 根目录：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp`。

临时可执行文件 `/private/tmp/dsh-v2-built-cli-wrapper`，权限 0700：

```sh
#!/bin/sh
exec /Users/gumpm5/.nvm/versions/node/v22.22.0/bin/node /Users/gumpm5/Documents/Code/xDAN-DSH-Exp/apps/cli/lib/bin.js "$@"
```

从 DSH 根目录运行：

```sh
PYTHONPATH=/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/python/sdk/src /private/tmp/harbor-h0-20260908/bin/python scripts/smoke-python-runtime.py --scenario sdk-minimal --exe /private/tmp/dsh-v2-built-cli-wrapper > /private/tmp/dsh-v2-sdk-minimal.log 2>&1
PYTHONPATH=/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/python/sdk/src /private/tmp/harbor-h0-20260908/bin/python scripts/smoke-python-runtime.py --scenario sdk-restart --exe /private/tmp/dsh-v2-built-cli-wrapper > /private/tmp/dsh-v2-sdk-restart.log 2>&1
```

脚本支持 `--exe` 自定义入口；未传 `--installed-wheel`，因此此结果不冒充发行 wheel 验证。未传 `--update-snapshots`，脚本只读取并比较现有期望快照。脚本使用固定假 key `sk-keyless-smoke` 与本机 mock 服务。各 SDK 请求自带 60 秒超时；两项均正常完成，未触发超时或人工终止。

## 断言依据

源码均相对于上述 DSH 根目录：

- `scripts/smoke-python-runtime.py:1048`：minimal 执行并断言文件内容、最终响应及 `COUNT=1` / `COUNT=2`，比较 `scripts/snapshots/python-sdk-single-exe/minimal/model-visible.json`。
- `scripts/smoke-python-runtime.py:1331`：restart 的两个 `DeepSeekHarness` 上下文共享 home，但使用不同 session id；每个上下文结束时 runtime 关闭。
- `scripts/smoke-python-runtime.py:1706`、`:1730`：持久日志版本、cwd、内容与唯一 session id 检查。
- `scripts/smoke-python-runtime.py:1901`：生成规范化 result、requests 与两份 session 快照。期望文件为 `restart/result.json`、`restart/requests.json`、`restart/session.1.v2.jsonl`、`restart/session.2.v2.jsonl`，均位于 `scripts/snapshots/python-sdk-single-exe/`。
- `scripts/smoke-python-runtime.py:2255`：默认精确比对规范化快照。动态路径、时间等字段经过官方脚本规范化，因此不是原始运行日志的逐字节重复性证明。

日志仅为本地临时证据，任务临时 home 在脚本完成后按官方实现清理；上述退出码与输出已归档于本报告。

## 对升级门的意义与剩余边界

本次将证据从 initialize/shutdown 提升到了真实工具执行、SDK 事件返回和 Session v2 持久化快照。此前 source CLI 的 FiberState 启动失败不适用于这次已通过的 built CLI 路径；不据此声称 source CLI 问题已修复。

`sdk-restart` 验证两个独立 session 跨 runtime 生命周期共存，**没有测试同一 session 的恢复续跑**。也未测试旧 Session v0 导入、ContextPilot 自定义事件、`sourceEventSeqs` 血缘、Harbor receipt/audit 与训练 token 对齐。

尚需单独通过：最新 Linux runtime wheel 的构建安装与同类 smoke；本项目 DshAgent/Harbor bridge 对新版事件的完整证据采集和严格 receipt 审计；固定样本 reward/token 对齐；随后才是更新运行 pin 后的 GPU rollout、训练更新和 checkpoint reload。当前生产训练 pin `7840bced35ee07ebefbdce0106b56dbc00bdc3ef` 未修改。这两个 mock 情景不能证明模型能力提升或 RL 链路已经适配新版 runtime。
