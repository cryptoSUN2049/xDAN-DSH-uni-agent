# 正常完成路径：真实 GPU 验收

固定5e6b326、DSH0.1.3a2、配对VERL fefb080+overlay、基础Qwen3-4B。core-budget-normal-r1，WS01-v1-s2001，val，无参数更新。

监督器exit0，570.016秒，健康检查失败0。A生成1037 token，B生成302 token；两者finished/eligible均true，累计预算8192，实际NPZ计数与快照一致，生成logprob有限，NPZ哈希匹配。两者materialization_reason=null，正常结束没有被错误标记为预算触顶。

正式after_run源码/runtime/输入校验通过；消费审计passed=true、consumption_verified=true、run_completed=true，1组2条唯一A/B，策略版本0，stage_evidence_verified=true，无未知/重复消费或score mismatch。原crosswalk自身consumption标志仍false，后置正式审计独立核验为true，未篡改原件。

A/B业务reward均0。这是预算正常路径与完整链消费通过，不是能力提升或新有效学习。与core-budget-val-r2的真实8192触顶结果共同补齐预算修复两侧GPU验证；不扩张为全部P1/P2/P3通过。

原件/workspace/reports/core-budget-normal-r1，正式报告哈希见同名JSON。关机归档与恢复见gpu-shutdown-checkpoint-20260910.md。
