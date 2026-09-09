# Resident memory validation r2：真实 A→B 消费验收通过

2026-09-09，固定代码 `c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0`，remote checkout `/workspace/rebuild/uni-agent-memory-resident-r2`，run `/root/runs/memory-resident-val-r2`，既有 `uni-agent-rebuild-cf2d3f5` venv。DSH runtime SHA `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。

## 已通过的真实节点

- r1 默认 reward handles 构造问题修复后，r2 完成框架初始化。一个 resident rollout backend 完成 writer A 和独立 reader B，无两次 CLI 重启 backend。
- 监督 child PID `191435`，exit **0**，**385.009 秒**；manifest 为 `completed`，审计时 GPU compute-apps 为空。
- writer `memory-A-50972079284548cda61c0dc17f99663e`：finished、fresh、eligible，reward **1**，**325** 个实际生成 token。
- reader `memory-B-dd118bdd2d1a422494ed6b61499476ba`：独立新会话，finished、fresh、eligible，reward **1**，**242** 个实际生成 token。
- A、B 各三个真实生成段；generation/versioned counts 均 **3/3**、完整性 true，实际 policy version 均 **0**。validation trainer step 也为 0，未用调度步数伪造缺失版本。
- 专用审计重新验证原 stage JSON/NPZ、token digest、真实 Session trace、verifier receipt、冻结 manifest/content/source 与 A/B 身份绑定。writer 完成并通过原门后才冻结供 B 使用。
- 单个 validation sibling 的连续 key `_0_0`（A）和 `_0_1`（B）分别进入 `validation/0.jsonl`，score 均为 1；**1 个完整消费组、2 条唯一消费**，零缺失、重复、未知或未准入消费。
- 原始 crosswalk 仍为 `prepared-not-consumed`，submission 仍为 `tq-write-returned-not-consumed`；消费结论来自终态后独立 `audit_memory_training`，exit **0**、`passed=true`。没有改写旧标记来冒充消费。

链身份 `memory-7808e6746fc04234b3508c97ccd25830`；frozen content SHA `11a6c5b7532896b9e2bab79eac49ac5446a7002b7fc96e3626f85b3569029e5a`，manifest SHA `0bf85455dfc72728a09f4faf97b45ec05e338b9f4dcdfc1812d76c4da6cecba4`。

## 验收边界

本次为 **validation-only 固定 constraints 诊断**。原生汇总成功会话数 1、输出数 2，不能把 A/B 当成两个独立任务成功样本。没有 actor gradient/advantage 训练指标，train rollouts 为空，没有新 checkpoint；本次不证明 optimizer 更新或学习效果。

它验证了“同一常驻后端 → 唯一 DSH 内部 loop 执行 A → 控制端验证/冻结 → 新 session B → 原始 token 与延迟终态 reward 身份绑定 → trainer 真实消费”的工程路径。train n4、多组有效梯度、独立 reload、跨数据泛化仍分别验收；单条已有诊断满分不是模型能力提升研究。

本次未观察到拒绝/失败/unfinished 输出。r1 的构造失败仍单独保留，未覆盖或追认。

## 可复核证据

- [完整结果 JSON](memory-resident-val-r2-result.json)：精确 source/VERL SHA、监督、消费审计、每阶段真实版本与 token 数、冻结身份、日志哈希。
- 远程原件：`/root/runs/memory-resident-val-r2/consumption-audit.json`、`result-summary.json`、`chains/groups/*/crosswalk.json`、原 stage/receipt/trace、`validation/0.jsonl`。

审计命令（CPU，运行结束后）：

```bash
cd /workspace/rebuild/uni-agent-memory-resident-r2
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=.:verl \
  /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m examples.dsh.capabilities.audit_memory_training \
  /root/runs/memory-resident-val-r2 \
  --memory-root /root/runs/memory-resident-val-r2/chains \
  --run-id memory-resident-val-r2 \
  --output /root/runs/memory-resident-val-r2/consumption-audit.json
```
