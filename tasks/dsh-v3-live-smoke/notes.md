# 实现与验证笔记

日期：2026-09-07。用户已批准 CPU 实现及手工 worktree 创建。

## 已确认的实现行为

- M0 `a197ead`：保留固定 VERL，修复测试 fixture；Ruff 0.12.2/0.15.8
  import 分类通过。主分支 Draft PR #1 的五项 workflows 成功。
- 任务行禁止覆盖 operator workdir；每行 metadata 加 cwd 不会生效。
  因此在已有 `task_runner` resolve 之后增加 operator-owned workspace 参数，
  不改变 Task / verifier / Framework 核心的准入合同。
- 已实际检查 prepare → Parquet → metadata 预登记 → 16 文件复制 → verifier
  `--help` 的 CPU 衔接。没有模型调用，不能把 `--help` 当任务成功。
- TQ `session_id` 是整数 rollout index；真正 Gateway ID 在 dump header 中。
  多 chain 共享同一 episode 的最终 reward/receipt，TQ 最终读回选择最大 chain index。
- bundle writer 的排序发生在路径标准化之前；absolute/relative scenario 参数会
  影响 verifier 文件清单排序。prepare 用既有 author 重建并验证两种现有合法形式。

## Review 发现及回归

独立审查发现三项，均在新 auditor 范围修复：

1. 旧 NPZ loader 转为 Python list 会丢 dtype，NaN/负数/二维 token ID 可能被放过。
   增加每条 chain 的一维、整数、非负检查；先看到 3 个失败用例再修复。
2. 截断 ZIP 会抛 `BadZipFile`；现包装为失败报告，不中断整个审计。
3. `load_live_scenarios` 不会利用 repository_root 解析相对 scenario path。
   现显式绑定已校验仓库路径；异 cwd 的同名不可信 registry 用例覆盖此问题。

另有回归覆盖：unfinished dump、历史 episode workspace 持久变化、receipt
时间/issuer、缺失 TQ readback、完整但 reward=0 的策略失败。生成 hash 不等于
来源真实性；这批 fixture 始终是 synthetic CPU 测试。

## 测试环境的实际限制

临时环境：`/private/tmp/uni-agent-cpu-20260907`，Python 3.12.12。额外安装
aiohttp、datasets、SWE-bench 4.1.0 及依赖只为本机完整回归；未改项目依赖或 GPU pin。

coverage 7.16.0 对 dotted source module 用 `find_spec()`，在
`sys_modules_saved` 内导入 `uni_agent.framework.task_runner` 会连带加载
torch/numpy，退出后清掉 `sys.modules`，C 扩展却仍在进程里。第二次 import
产生 `cannot load module more than once` / `already has a docstring`。
最小复现已验证。使用目录 source：

```sh
--cov=examples/dsh/ops --cov=examples/inference --cov=uni_agent/framework
```

再从 JSON coverage 报告提取四个修改模块；不要因为上述 instrumentation
问题升级冻结的 torch 或 VERL。该问题不等于测试已通过。

PyPI distribution 名 `TransferQueue` 与 `transfer-queue` 不等价。probe 查询
`metadata.version('TransferQueue')`，manifest 字段仍是 `transfer-queue`；已用
执行真实 probe 代码、stub 掉 GPU 模块的 CPU 测试复现并验证。

## GPU 与全局阶段

本轮没有创建 RunPod 资源或执行模型/训练。旧 DSH commit 缺失、Linux
source/runtime 冻结及独立 Pod 停机仍待完成。进程组 TERM/KILL 不等于
Pod 停费，也不保证回收主动脱离进程组的进程。模型 Pod 不接收 RunPod/GitHub key。

完整运行报告与最终测试数字在 handoff / progress 中记录；本笔记保留根因，
不维护第二份不断漂移的累计测试计数。
