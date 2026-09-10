# GPU关闭后的快速恢复入口

2026-09-10。最新关机节点优先阅读 [GPU关机检查点](gpu-shutdown-checkpoint-20260910.md)。下文旧短课程是历史资料；当前主线为核心记忆课程有效学习，异步暂停。

## 不要重复已完成的实验

- ws-short-train-r1：8步中2步非零梯度，真实参数变化，901/902独立reload通过。
- ws-short-train-r2：工程重复与两题reload通过；32终态B全满分，8步零梯度、参数未更新。不能作为已提升的模型。
- core-v1现有520train/160公开dev；core-train-r4已完成16步/16独立任务，全部任务梯度0。四族reload及预算修复已验，详细以最新关机检查点为准，不能宣称能力提升。
- 32链事实诊断已完成：23条A已保存但B未读记忆，是下一课程主要目标。方案expert-memory-context-training-plan.md与core-memory-expanded-course-design.md。

## 恢复所需资产

| 资产 | 原持久盘路径 |
|---|---|
| 首次有效更新checkpoint | /workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_8 |
| 重复实验checkpoint（零更新） | /workspace/uni-agent-g1/checkpoint/ws-short-train-r2/global_step_8 |
| r1原始证据归档 | /workspace/reports/ws-short-r1-engineering-evidence-20260909.tar.gz |
| r2原始证据归档 | /workspace/reports/ws-short-r2-engineering-evidence-20260909.tar.gz |
| 模型 | /workspace/models/Qwen3-4B-1cfa9a7 |
| 既有Python环境 | /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python |
| DSH固定wheels | /workspace/artifacts/dsh-g1-v2-b236969/ |
| r2执行源码 | /workspace/rebuild/uni-agent-rsi-compare-f419bbb（f419bbb3d72fd49abc0b37cea94fde699d1c03ac） |

r1 archive SHA256=d7764c1422ce5a9f89df862a927059224ca5ede201fd2756a40468ef505d8823。
r2 archive SHA256=15e23af2bb646d3b7c3efc456131b4d9c21a6ccfc50eeba7671cb6dc5dd46cee。
checkpoint不在证据tar中，单独保留。归档排除training.env等环境文件；新run用固定准备器重新生成。私有/root/runs可能随Pod丢失，恢复旧审计需从归档检查成员后恢复原路径，不能直接假定它仍在。

## 重新接入顺序

1. 获取新SSH地址/端口，确认挂载同一network volume到/workspace。若挂载错误先纠正，不重新下载或覆盖资产。
2. `nvidia-smi`确认GPU与其他作业；`df -h /workspace`检查挂载；确认上表模型/CK/wheel/archive存在。集群df容量不代表个人配额。
3. 检查既有venv是否可运行。新容器的Python/动态库可能不同，目录存在不代表环境可用：执行下面无训练探针。
4. 从GitHub分支worktree-harbor-modal-integration读取handoff后选择固定完整SHA；新checkout，不在历史运行checkout里pull。恢复历史r2用f419，下一课程用届时已通过测试并推送的实施SHA。
5. 设置显式PYTHONPATH，核VERL overlay和DSH0.1.3a2；通过后复用venv。失败才按native-work-state-end-to-end-runbook.md重建新命名环境，不覆盖旧环境。
6. 新run-id、新prepare目录，checkpoint保持/workspace/uni-agent-g1/checkpoint/<run>。先canary与GPU smoke，再启动基线/训练。恢复优先从明确checkpoint开始，不试图恢复消失的Ray进程。

```bash
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
"$PYTHON_BIN" -c 'import torch; from importlib.metadata import version; print(torch.__version__, torch.cuda.is_available()); print(version("deepseek-harness-sdk"), version("deepseek-harness-runtime-bin"))'
cd /workspace/rebuild/uni-agent-rsi-compare-f419bbb
export PYTHONPATH="$PWD:$PWD/verl"
"$PYTHON_BIN" -m deployment.checks.verl_source_overlay --repo "$PWD/verl"
```

上述是环境检查，不启动训练，不证明所有依赖已验收。私有GitHub凭据不存入文档；新Pod若无认证需先配置机器访问。原SSH 216.243.220.178:14465仅历史地址，不假定下次有效。

## 冷启动读文档顺序

先tasks/harbor-modal-integration/handoff.md→本文→expert-memory-context-training-plan.md→core-memory-fact-flow-audit.md→core-memory-expanded-course-design.md。确认实现状态再执行；异步和误发聊天面板不属于当前启动任务。
