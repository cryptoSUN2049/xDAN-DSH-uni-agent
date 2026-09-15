# 项目决策记忆：Uni-Agent原生Harbor RL＋OPD

更新时间：2026-09-15。

## 用户已明确的目标与授权

用户要求围绕Uni-Agent当前架构和recipes推进，复用其他worktree能力；明确要求独立分支及worktree，并已授权启动实现。不得在下一session重复询问是否允许创建worktree、成对升级或实施已讨论的接线。

目标分支/worktree：verl-uni-agent-harbor-opd-rl。
基线：harbor-modal-integration / 9075dfa。
目标上游：Uni-Agent 91618ea065e3f02a004442ca08521521b0ce0698。
配对VERL：a9f2985159536a607211dcac730d3f5d55028950。
旧VERL：fefb080262e1c015a0ea05f958822a6a512dc795。
VERL增量62提交、264文件；不默认升级到VERL独立main。

## 不可偏离的架构

Uni-Agent owns Agent/Task/Gateway/trajectory admission/TQ；VERL owns optimizer与训练；Harbor owns任务/verifier；Modal用于隔离任务环境。DSH保留现有Agent执行链。Tinker Cookbook只作为算法/评分/验证参考，不改用其trainer作为主框架，也不默认添加VeRL-Tinker服务层。

Student候选Qwen3.5-9B，Teacher候选Qwen3.8-27B。用户假设自有8×A100，但40GB/80GB、网络和实际访问尚未确认；不据此声称服务器可用或已启动GPU。

## 真实能力与缺口

最新上游entry.py仍拒绝teacher_client；限制始于2026-06-18 ee61374 / PR58，不是已知OPD回归。VERL有Teacher manager，Uni-Agent需要补传递、原始token评分、mask/位置/版本与TQ消费合同。不得只删除raise。

Tinker云P0已有9B/27B更新和独立推理reload，9个本地证据工件SHA一致；RL advantage全0，实际更新为OPD。不能将它认作Uni-Agent/VERL、正式TB、optimizer恢复或能力提升验收。

## 已启动的升级预检

已执行git merge-tree只读合并预检，未修改产品代码/建立未解决merge状态。发现7个冲突文件：
- docs/source/concepts/gateway-and-trajectories.md
- tests/uni_agent/framework/test_generate_sequences_on_cpu.py
- tests/uni_agent/rl_insight/test_adapter.py
- uni_agent/framework/entry.py
- uni_agent/framework/framework.py
- uni_agent/gateway/session/codec.py
- uni_agent/gateway/session/session.py

先保留本地严格组准入、memory/context、预算、session证据和清理行为，结合上游Continuous Token/router/postprocessor新合同解决冲突，再测试。不能使用整文件ours/theirs机械覆盖。

## 阶段顺序

1. 上游成对升级与现有CPU回归；核对官方recipes与本地启动路径。
2. Teacher client→Framework评分→TQ→VERL蒸馏loss接线及合同测试。
3. Harbor远程DSH执行器Modal适配（现有Docker专用逻辑不能靠配置自动迁移）。
4. 真实完整group、RL/OPD/hybrid非零信号、更新/采样权重同步/推理reload/optimizer恢复。
5. 同预算独立评测；正式TB测试题不参与调参。

代码实施已授权；具体远端访问与资源预算仍需实际信息，不推断存在。当前没有远端启动、合并、push或新GPU测试。继续前先读handoff与integration-design，再核Git实际状态。
