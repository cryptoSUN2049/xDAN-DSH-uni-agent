# TL;DR
- 当前 worktree/分支：`verl-uni-agent-harbor-opd-rl`；用户已授权实施、GPU验证和按节点 commit/push。
- Uni-Agent `91618ea` / VERL `a9f2985` 已配对升级；Teacher→TQ→原生loss接线完成。
- `283e3a5` 原生loss 8项CPU验证；`cec4a07` Modal后端191项CPU验证。均非GPU训练证据。
- 当前推进：LoRA合并同步配置已修复（3140271，18项测试），完成单卡依赖安装；随后实际GPU验证。
- 平台 goal 为 active。双卡由用户需要时启动；完整训练闭环尚未验收。

# 本轮交付物
代码与设计主要文件（行数为此节点快照；详见各提交diff）：
- `uni_agent/framework/entry.py`（221 行）
- `uni_agent/framework/framework.py`（1729 行）
- `uni_agent/framework/memory_chain.py`（588 行）
- `uni_agent/tasks/harbor_dsh/environment_backend.py`（81 行）
- `uni_agent/tasks/harbor_dsh/modal_environment.py`（157 行）
- `uni_agent/tasks/harbor_dsh/executor.py`（472 行）
- `uni_agent/tasks/harbor_dsh/isolated_trial.py`（388 行）
- `uni_agent/tasks/harbor_dsh/worker.py`（226 行）
- `tests/uni_agent/framework/test_teacher_loss_on_cpu.py`（156 行）
- `docs/verl-uni-agent-harbor-opd-rl/modal-backend-design.md`（113 行）
- `docs/verl-uni-agent-harbor-opd-rl/modal-controller-notes.md`（61 行）
- Teacher timeout/scoring/rollout/version、Modal helper/scope/executor/Trial/Worker测试：对应上述源码的tests目录。
- `docs/verl-uni-agent-harbor-opd-rl/async-lora-validation.md`（78行）：真实同步缺口及GPU验收步骤。
- `examples/harbor_opd_rl/{base,rl,opd,hybrid}.yaml` 与 `launch.py`：原生训练配置与入口。
- `docs/verl-uni-agent-harbor-opd-rl/{integration-design,training-recipes,teacher-bridge-review}.md`：架构、算法与CPU证据。
- `tasks/todo.md`、`tasks/lessons.md`、本目录 `memory.md`：计划、纠正与持久决策。

# 设计约束
Uni-Agent保留Agent/DSH/Gateway/任务准入/TQ；VERL负责优化与同步；Harbor负责verifier；Modal只做任务sandbox。不能切换Tinker trainer或引入另一套agent loop。
Teacher概率不是任务成功判定。Teacher整组失败不得提交部分trajectory。生成版本、行为logprobs和工具mask必须保留。失败清理确认不得制造reward。
所有修改留在当前worktree，不覆盖其他工作树或SkyRL环境。每次push先全库Ruff双门。

# 已踩坑/已发现的真实行为
- 原生Teacher返回全序列[S,K]且已left-shift；首response用prompt_len-1行，末dummy不能再shift。
- Teacher TQ用ragged_idx=1；缺列不得被shared_keys静默丢弃。
- 上游postprocessor增加task_result；resident工厂需转发Teacher但保留自身同步限制。
- Harbor锁0.16.1。Modal Trial可选路径已接通；Controller公网入口、registry release仍待实施。
- Harbor清空sandbox句柄不证明终止；独立scope保留资源ID并terminate/poll确认，成功需agent与verifier，失败只核实际创建资源。
- native separate_async训练和推理分卡；colocate_async会暂停推理更新。Teacher必须独立池：纯separate RL至少2GPU角色，separate+OPD至少3；不是显存容量保证。
- **发现异步LoRA同步缺口**：非naive checkpoint path未传adapter metadata，未merge时可能只导出base；recipe已显式merge=true（3140271），18项测试通过。不能声称当前为高性能增量adapter同步。
- ReplayBuffer staleness按提交step过滤，实际token min/max只是独立证据，不能混称。
- 远端FUSE不支持chown，rsync用-rltz；安装慢同时存在下载/解压瓶颈，不凭进程存在判断进展。
- CPU用torch2.14；UA测试lane vLLM0.23与VERL uv.lock vLLM0.24不同，不混称统一锁。

# 下一里程碑任务清单
- [x] LoRA merged同步最小修复、18项CPU配置回归、独立commit 3140271。
- [ ] 全库Ruff双门，push当前分支；核远端HEAD。
- [ ] GPU环境安装结束后固定TQ与源码，实际CUDA/vLLM测试。
- [ ] Controller拥有公网HTTPS Gateway映射；冻结可拉取registry镜像/任务/policy。
- [ ] 通知用户需要双卡后验证separate_async LoRA：真实rollout→update→新权重rollout。
- [ ] OPD/hybrid多卡验证、独立reload、optimizer恢复和吞吐/陈旧度指标。

# 分支/部署状态
分支已有升级、Teacher、recipe、版本准入及上述2个新提交。用户刚授权push，本节点准备推送；未创建PR。实际远端HEAD须用git核验。
远端 `root@157.157.221.177:12524`，SSH key `~/.ssh/id_ed25519`，独立known_hosts `/private/tmp/uni-agent-opd-known-hosts`。
实际GPU单张RTX PRO6000 Blackwell96GB。独立根 `/workspace/verl-uni-agent-harbor-opd-rl`；源码 `src/uni-agent`，新提交尚需增量同步。
当前环境 `/tmp/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023`；安装日志 `/workspace/verl-uni-agent-harbor-opd-rl/runs/environment-install-localssd.log`，本轮仍在解压/下载，无训练启动。
CPU最近证据：Framework/Gateway547通过；原生loss8通过；Modal191通过。日志分别 `/private/tmp/uni-agent-opd-latest-cpu-regression.log`、`/private/tmp/uni-agent-native-opd-hybrid-loss-confirmed.log`、`/private/tmp/uni-agent-modal-integrated-tests-r3.log`。
CPU命令解释器 `/private/tmp/uni-agent-opd-upgrade-cpu/bin/python`；PYTHONPATH工作树+verl，Harbor测试另加已核验缓存 `/Users/gumpm5/.cache/uv/archive-v0/GhbgF7AXg2sb3NAv`。

# 冷启动 checklist
- [ ] 先读本handoff、memory.md、integration-design.md，再核git status/log/submodule。
- [ ] 查agent状态、GPU安装日志和退出码；不能重复安装、不能停止别的项目进程。
- [ ] 查本分支远端HEAD与未提交改动，不以文档代替实际状态。
- [ ] 看tasks/todo.md当前节；用户已经实施授权，勿重复询问。
- [ ] 真实GPU前核依赖版本、源码manifest、显存；CPU/Tinker旧证据不得追认为新闭环。
