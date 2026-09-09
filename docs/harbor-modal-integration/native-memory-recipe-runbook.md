# 原生 resident memory：先 val，再 n4 工程诊断

此入口复用固定 DSH 单卡脚本、VERL v1 sync、NativeMemoryFramework。A/B 使用同一常驻 Gateway backend，但独立 session；DSH 是唯一执行 Loop。固定 constraints / updates 两族曾在独立推理中成功，这不证明新 resident 接线或训练成功。

每次一个 family、一条 train 和一条 val 调度记录。二者身份不同但语义相同，属于 `fixed-diagnostic-not-heldout`；不能当泛化留出集。默认 val-only，框架配置仍保留 train n4 / val n1。切到 train 才执行一次 n4 更新尝试。全部 B 同分意味着零 GRPO 信号，应报告消费工程情况，不能制造失败/伪造奖励来宣称学习。

## 人工执行

先由主线程提交/push此批，再在空闲 GPU 上按精确新集成 SHA 检出。VERL 和 DSH pin 保持部署锁；不要留在旧 d3084f2，因为旧提交没有 NativeMemoryFramework。

```bash
cd /workspace/rebuild/uni-agent-native-n0-r1
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
export CUDA_VISIBLE_DEVICES=''
RUNTIME="$($PYTHON_BIN -c 'from deepseek_harness_runtime import bundled_runtime_path;print(bundled_runtime_path())')"
$PYTHON_BIN -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir /root/runs/memory-resident-val-r1-data \
 --run-root /root/runs/memory-resident-val-r1 --run-id memory-resident-val-r1 \
 --runtime-executable "$RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family constraints --mode val
$PYTHON_BIN -m examples.dsh.capabilities.prepare_memory_training check \
 /root/runs/memory-resident-val-r1-data/manifest.json
```

`prepare` / `check` 不启动 GPU；检查实际 checkout/VERL、源与输入 hash、DSH SDK/runtime 0.1.3a2、runtime 字节摘要、模型 config/tokenizer config 摘要和跨 cwd 导入。模型 revision 必须等部署锁，但 revision 字符串并非外网来源证明；当前只测量清单列出的模型文件。

完成审阅后真实启动（前台监督，另一个 SSH 窗口观察）：

```bash
$PYTHON_BIN -m examples.dsh.capabilities.prepare_memory_training launch \
 /root/runs/memory-resident-val-r1-data/manifest.json
```

启动器清单环境显式设 CUDA=0，拒已有 GPU compute process，创建独占短 Ray 目录及 700 的 `run/chains`；监督墙钟 val 3600 秒、train 7200 秒，仅停止自己进程组。断开 SSH 的处理应由操作者使用 tmux 等持久终端，不把后台 PID 当成功证据。

val 完成后，重新 prepare 全新 `memory-resident-train-r1[-data]` 名称、`--mode train`，其余参数保持不变；仍先 `check` 再 `launch`。`--family updates` 也要全新名称。不能复用目录或复制旧回执；本批没有新增 reload recipe。

## 证据位置和判据

- `manifest.json`：准备身份、环境、实际 ops argv、source/input/runtime/model 摘要、明确未运行状态。
- `<run>/supervision/train.log` 与 `supervisor-result.json`：真实启动与退出。
- `<run>/chains/<chain>/writer|reader/`：私有 task config、fixture、真实 trace / receipt、冻结记忆。B 不继承 A 对话。
- `<run>/agent-logs/`：stage-only NPZ+metadata，阶段原始 reward/token 不改变。
- `<run>/chains/groups/*/crosswalk.json`：链回执、唯一 TQ key、A 后 B、调度 step 与实际权重版本。仅 producer 对应关系，不能单独证明消费。
- `<run>/chains/groups/*/submission.json`：TQ 写返回；仍非 trainer 消费证明。使用独立 memory 消费审计，不拿旧 DSH v2 audit 假称已通过。
- checkpoint 在 `/workspace/uni-agent-g1/checkpoint/<run-id>`；train 只有一条题/一次更新尝试，可能零优势、零梯度。

先验收 fresh A/B、私有 freeze、新 B 事实正确、真实 logprobs/token/version、组准入和实际消费；参数更新仍需非零学习信号、checkpoint/optimizer 和后续独立 reload 证据。CPU Hydra/from_config 和首 A 目录冒烟不能替代 GPU 验收。
