# RSI 固定 VERL overlay 适配

目标：RSI worker / proposer 与已批准部署合同一致，只允许 fefb080 + preserve-finish-reason-v1 的精确源码；不改 VERL、reward 或 Registry 语义。

```mermaid
flowchart LR
  Lock[部署 lock + manifest + patch] --> Verify[现有 verify_verl_source]
  Verify --> Prepare[RSI prepare 来源清单]
  Prepare --> Live[worker / proposer preflight 与运行中复核]
  Live --> Audit[proposal 来源审计]
```

改动文件：prepare_worker_eval.py 增加共享身份探测和 overlay 校验器/manifest/patch 来源绑定；launch_worker_eval.py 的共享 _live_inputs 拒绝缺失或漂移身份；proposal_registration.py 和 launch_proposal.py 传递并复核同一身份。测试只用 CPU 临时 checkout。

API：preparation manifest 新增必填 verl_effective_source，与 verify_verl_source 返回对象完全相等；旧清单必须重新 prepare。require_clean_sources 保留主仓库提交要求；VERL 改用现有严格校验，不做自动 apply。

验证：先 RED 复现精确 overlay 被拒；精确 overlay 通过；未知 target、锁文件、untracked/staged 修改拒绝；worker 和 proposal 清单身份缺失/漂移拒绝；相关 RSI/overlay 回归与 Ruff 双门。此工作延续用户已授权版本合同，无 GPU、commit 或 push。

验证结果：修复前 5 项 RED（精确补丁遭拒、身份未绑定、3 类漂移漏检）；修复后既有 CPU 环境 `/private/tmp/uni-agent-cpu-20260907/bin/python`、`PYTHONPATH=.:verl` 下 RSI prepare/proposal/launcher、真实 overlay、Registry/worker 共 **207 passed**，仅既有 Ray deprecation warning。全仓 `ruff check .` 和 `ruff format --check .` 通过（361 files）。源码审查未发现 strict inference 入口另有 clean-VERL gate；实际 GPU 运行留给新清单执行，不以 CPU 测试替代。
