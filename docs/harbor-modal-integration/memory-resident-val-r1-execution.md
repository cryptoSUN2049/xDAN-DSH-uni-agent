# 第一个 resident memory GPU 验证

状态：真实GPU运行失败。模型引擎已加载，但NativeMemory构造误拒上游默认reward worker句柄，A/B尚未执行；主线程只停止已核实归属的child185194进程组，supervisor exit=-15/540.012秒，GPU已释放。原始run/日志保留；后续修复需新版本和新运行。

- integration：`4168b628f3a2ff4c301dcffb60f016f8ecb770f2`；配对 VERL `fefb080262e1c015a0ea05f958822a6a512dc795`。
- 独立源码：`/workspace/rebuild/uni-agent-memory-resident-r1`，detached worktree；旧 context checkout 不改。
- Python：`/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python`，复用已有GPU验收环境，不重装。
- DSH：固定 0.1.3a2，Linux runtime SHA `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- 模型：`/workspace/models/Qwen3-4B-1cfa9a7`；revision声明 `1cfa9a7208912126459214e8b04321603b3df60c`。
- 任务：constraints固定诊断族，A读取源并写memory，严格核验后冻结，B在新DSH/Gateway会话读取冻结事实并回答。同一驻留模型服务，不用两次inference CLI拼接。
- data：`/root/runs/memory-resident-val-r1-data`；run：`/root/runs/memory-resident-val-r1`；stage root：`run/chains`。
- 首轮模式：VERL v1 sync，VAL_ONLY=True，val n1，train n4只作为框架合同，不执行训练更新；并发1，LoRA16，8192+8192，推理预算.30，wall3600秒。

## 这次要证明什么

1. 真实启动固定模型服务，A/B共享后端且独立session。
2. A原始回执、文件字节/冻结摘要、B原始回执逐项对应。
3. Gateway每次生成都有真实权重版本，val step0应等weight0；不从调度字段补写缺失版本。
4. 原A/B reward和token不改写，TQ key跨stage连续且唯一，最终B处于sibling最后。
5. 专用消费审计与实际trainer val JSONL对应；仅submission.json不算消费。

本轮不要求参数更新，不将其标记为memory RL已全部通过。随后以独立train run验证n4完整组；若B奖励全同分，明确没有新增GRPO学习信号，不人为改变分数制造梯度。

## 执行与观察入口

准备/check/launch命令见 [recipe操作手册](native-memory-recipe-runbook.md)。运行后看 `run/supervision/train.log` 与 `supervisor-result.json`，先核日志再看GPU，不凭PID判断启动。最终审计：

```bash
cd /workspace/rebuild/uni-agent-memory-resident-r1
PYTHONPATH="$PWD:$PWD/verl" CUDA_VISIBLE_DEVICES='' \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
 -m examples.dsh.capabilities.audit_memory_training \
 /root/runs/memory-resident-val-r1 \
 --memory-root /root/runs/memory-resident-val-r1/chains \
 --run-id memory-resident-val-r1 \
 --output /root/runs/memory-resident-val-r1/memory-consumption-audit.json
```

CPU接线已281项组合回归、主线程38项重验；消费审计27项新增用例通过；recipe真实shell/Hydra/from_config与首A目录6项通过。它们不替代上述GPU事实。
