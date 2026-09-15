# 原生训练闭环独立验证交接

## 1. TL;DR
- worktree/branch：verify-native-training-closure，来源3eebf20。
- Teacher/轨迹/loss 51项、recipe/入口/监督器92项通过。
- 默认2行只运行1外层步，无checkpoint；1行触发除零。
- 来源工作区另一会话持续施工，本分支仅保存验证及修复设计。
- 用户已要求继续；下一节点在本隔离worktree修复训练入口合同，独立于Modal施工。

## 2. 本轮交付物
- docs/verify-native-training-closure/verification.md：62行，结果、复现、修复设计。
- tasks/todo.md：追加本轮验证清单。
- 本文件：35行，冷启动入口。
- tasks/verify-native-training-closure/goal.md：当前目标及M0—M3状态。
- tasks/lessons.md：记录用户要求的节点提交/推送与状态更新规则。

## 3. 设计约束
DSH唯一Agent loop，Uni-Agent负责轨迹/准入，VERL负责更新/checkpoint。不得覆盖另一会话未提交文件或修改其安装进程。CPU、有效学习和效果分别验收。

## 4. 已踩坑与真实行为
- 测试需要PYTHONPATH=.:verl；首次缺少子模块路径导致collection失败，修正调用后通过。
- 配置测试通过不能覆盖epoch耗尽后的最终保存。
- separate_async外层步与optimizer子步不同。
- VERL支持恢复，当前recipe入口尚未提供恢复参数。

## 5. 下一里程碑
- [ ] 确认唯一实施会话，修复数据—预算—最终保存合同。
- [ ] 验证过滤后数据不足、最终保存、恢复及有界运行参数。
- [ ] GPU有效更新、采样同步、独立reload、optimizer恢复。
- [ ] 同预算独立模型效果评估。

## 6. 分支/部署状态
独立验证worktree保留；M0文档按本提交交付并推送同名分支，后续以远端回读验证。未部署、PR或启动训练。远端依赖安装是报告中的时间快照，不代表实时状态。

## 7. 冷启动 checklist
1. 本文件→verification.md→原实施分支最新handoff。
2. 核Git状态和是否已有checkpoint修复，避免重复施工。
3. 检查实际环境及资源占用，再按有界实验验收，不重复安装/运行。
