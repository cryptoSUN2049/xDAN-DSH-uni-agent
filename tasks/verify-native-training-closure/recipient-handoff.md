# 给 verl-uni-agent-harbor-opd-rl 会话的执行交接

## TL;DR

- 用户最新指示：本会话提交PR并写交接，由产品会话合并和执行；本会话不合并、不操作其GPU作业。
- PR：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/3
- 目标分支：verl-uni-agent-harbor-opd-rl；修复b02deb8；组合验证提交3e7ce3b（后续仅交接文档更新）。
- GitHub四项检查已通过：check-metadata、docs、pre-commit、secrets-scan。合并前按最新HEAD重新核对。
- 123项修复回归，启动入口99%覆盖；与a7f8344组合320项通过。GPU完整闭环未验收。

## 交付内容

启动入口 examples/harbor_opd_rl/launch.py 复用配对VERL的tokenizer/processor/create_rl_dataset进行真实过滤预检。有效行数少于一个batch或验证集为空时在Ray启动前拒绝；根据绝对目标步数推导epoch，避免小数据提前退出而没有最终checkpoint。

新增参数：--total-training-steps、--save-freq、--resume-from-path、--preflight-only。print-config只做配置组合；preflight-only读取tokenizer/数据但不训练。实际运行写training-preflight.json。

恢复目标是绝对step；恢复源要求global_step_N/actor和data.pt，目标step必须更大。model/optimizer/extra及受支持TQ恢复交原生VERL，未将入口存在当作真实恢复验证。

证据和指南：docs/verify-native-training-closure/{checkpoint-fix.md,cpu-validation.json,training-recipes.md,verification.md}。
测试：tests/uni_agent/examples/{test_harbor_launch_preflight.py,test_harbor_training_preflight.py}。

## 不可改变的约束

保留DSH唯一Agent loop、Uni-Agent轨迹准入和原生VERL训练，不改配对子模块。工具输出mask和真实Harbor reward保持原合同。不得伪造奖励方差或用CPU测试替代GPU更新/效果。

## 产品会话执行清单

- [ ] 先读本文件及本产品worktree最新handoff/notes，核Git状态、HEAD、已有GPU作业PID和结果。
- [ ] 核PR目标、最新diff与checks；合并PR #3，不再另建训练主线。
- [ ] 本地安全快进到合并结果；保留当前fsdp_lora_merged_export.py未提交修复及fsdp-lora-export-r1.json、notes.md。若这些状态已变化，以最新状态为准。
- [ ] 有新增产品修改时复跑相关组合测试与Ruff双门；无代码变化不重复全部验证。
- [ ] 在固定服务器模型/数据上运行--preflight-only，检查有效rows、epoch、总步数和恢复来源。
- [ ] 继续现有单卡LoRA导出组件实验，先查r2真实进程和结果，不因SSH观测超时重启。
- [ ] 双卡separate_async RL：完整组真实采样、非零优势/梯度、参数变化、新权重采样、最终checkpoint、独立reload。
- [ ] 显式optimizer恢复与OPD/hybrid角色资源验证；最后同预算独立效果对照。
- [ ] 各节点commit/push、handoff/tasks/goal同步；总目标不因PR合并而标complete。

## 远端现场边界

本会话普通SSH多次在banner阶段超时，不证明服务/作业已终止。产品会话notes记录专属ControlPath `/private/tmp/uni-agent-opd-validation-ssh.sock`、900秒有界r2和运行证据；由产品会话核实最新状态。不要启动重复GPU实验或动其他项目环境。

## 验证命令

CPU解释器 /private/tmp/uni-agent-opd-upgrade-cpu/bin/python；PYTHONPATH=.:verl。Harbor依赖按产品handoff的固定缓存，覆盖插件在/private/tmp/uni-agent-closure-test-tools。完整范围见本分支handoff和cpu-validation.json。

原生fit控制流测试提取实际配对实现，仅stub模型/日志/队列；真实本地tokenizer过滤无外部模型请求。两者证明入口合同，不证明训练质量。

## 收敛和分支状态

PR保持OPEN供产品会话执行。临时verify-native-training-closure保留供审阅，不再开发/部署；合并后可按Git状态正常清理，勿force删除脏工作区。当前唯一产品主线为verl-uni-agent-harbor-opd-rl。
