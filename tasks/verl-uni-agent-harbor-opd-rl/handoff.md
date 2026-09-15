# TL;DR

## 训练入口修复合入说明

来自verify-native-training-closure的b02deb8：原生过滤预检、完整batch前置校验、根据目标步推导epoch、最终checkpoint保存及显式恢复参数。与a7f8344组合的320项CPU交叉回归通过；单独入口回归123项，覆盖率99%。GPU更新/reload/optimizer恢复仍未验收。

产品主线保持verl-uni-agent-harbor-opd-rl，临时验证分支通过PR交付后不再独立推进。详情见docs/verify-native-training-closure/checkpoint-fix.md及training-recipes.md。原有notes.md与其他会话未提交文件保留。
- 当前 worktree/分支：`verl-uni-agent-harbor-opd-rl`；用户已授权实施、GPU验证和按节点 commit/push。
- Uni-Agent `91618ea` / VERL `a9f2985` 已配对升级；Teacher→TQ→原生loss接线完成。
- `283e3a5` 原生loss 8项CPU验证；`cec4a07` Modal后端191项CPU验证。均非GPU训练证据。
- 当前推进：单卡依赖安装/GPU算子和vLLM回归已通过；真实LoRA merged导出组件已通过（r2）。
- b0b3967接通Controller公网入口与任务准备，217项CPU通过；真实Modal环境双sandbox清理通过。
- 平台 goal 为 active。已向用户请求双卡SSH和专用Gateway域名；完整训练闭环尚未验收。

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
- Harbor锁0.16.1。Modal Trial/Controller公网入口/任务准备代码已接通；专用域名配置、DSH registry发布与真实任务仍待完成。
- Harbor清空sandbox句柄不证明终止；独立scope保留资源ID并terminate/poll确认，成功需agent与verifier，失败只核实际创建资源。
- native separate_async训练和推理分卡；colocate_async会暂停推理更新。Teacher必须独立池：纯separate RL至少2GPU角色，separate+OPD至少3；不是显存容量保证。
- **发现异步LoRA同步缺口**：非naive checkpoint path未传adapter metadata，未merge时可能只导出base；recipe已显式merge=true（3140271），18项测试通过。不能声称当前为高性能增量adapter同步。
- ReplayBuffer staleness按提交step过滤，实际token min/max只是独立证据，不能混称。
- 远端FUSE不支持chown，rsync用-rltz；安装慢同时存在下载/解压瓶颈，不凭进程存在判断进展。
- CPU用torch2.14；UA测试lane vLLM0.23与VERL uv.lock vLLM0.24不同，不混称统一锁。

# 下一里程碑任务清单
- [x] LoRA merged同步最小修复、18项CPU配置回归、独立commit 3140271。
- [x] 全库Ruff双门通过（479文件），里程碑push至origin；89ebca9已推送。
- [x] GPU环境安装/TQ固定、CUDA BF16反向/NCCL、vLLM14项和Framework/Gateway569项通过。
- [x] 单GPU真实LoRA update→merged导出→trainer恢复组件验证（r2通过，r1失败保留）。
- [x] Controller公网HTTPS映射代码及Modal任务/训练准备冻结合同，217项CPU回归。
- [x] 真实Modal两个环境命令与独立终止确认；只是组件，不是DSH任务。
- [ ] 配置用户专用域名/Tunnel；冻结并验证可拉取DSH registry镜像/task/policy。
- [ ] 通知用户需要双卡后验证separate_async LoRA：真实rollout→update→新权重rollout。
- [ ] OPD/hybrid多卡验证、独立reload、optimizer恢复和吞吐/陈旧度指标。

# 分支/部署状态
分支已有升级、Teacher、recipe、版本准入及上述2个新提交。已推送至origin同名分支并设置tracking（里程碑HEAD 89ebca9）；未创建PR。后续文档提交用git核验实际HEAD。
远端 `root@157.157.221.177:12524`，SSH key `~/.ssh/id_ed25519`，独立known_hosts `/private/tmp/uni-agent-opd-known-hosts`。
实际GPU单张RTX PRO6000 Blackwell96GB。独立根 `/workspace/verl-uni-agent-harbor-opd-rl`；源码 `src/uni-agent`，新提交尚需增量同步。
当前环境 `/tmp/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023`；安装日志 `/workspace/verl-uni-agent-harbor-opd-rl/runs/environment-install-localssd.log`，已安装完成：Torch2.11.0/vLLM0.23.0/Transformers5.8.0/Ray2.54.1/TQ434f8c4，pip check245包兼容；没有训练闭环结果。
CPU最近证据：Framework/Gateway547通过；原生loss8通过；Modal191通过；入口/准备/执行器组合217通过。GPU组件与回归摘要见docs同目录gpu-preflight.json。日志分别 `/private/tmp/uni-agent-opd-latest-cpu-regression.log`、`/private/tmp/uni-agent-native-opd-hybrid-loss-confirmed.log`、`/private/tmp/uni-agent-modal-integrated-tests-r3.log`。
CPU命令解释器 `/private/tmp/uni-agent-opd-upgrade-cpu/bin/python`；PYTHONPATH工作树+verl，Harbor测试另加已核验缓存 `/Users/gumpm5/.cache/uv/archive-v0/GhbgF7AXg2sb3NAv`。

# 冷启动 checklist
- [ ] 先读本handoff、memory.md、integration-design.md，再核git status/log/submodule。
- [ ] 查agent状态、GPU安装日志和退出码；不能重复安装、不能停止别的项目进程。
- [ ] 查本分支远端HEAD与未提交改动，不以文档代替实际状态。
- [ ] 看tasks/todo.md当前节；用户已经实施授权，勿重复询问。
- [ ] 真实GPU前核依赖版本、源码manifest、显存；CPU/Tinker旧证据不得追认为新闭环。

## 2026-09-15 GPU/Modal新节点
- 新交付：deployment/services/harbor_modal_ingress.py、Controller/worker改动、prepare_t2_task/prepare_m2_training扩展；b0b3967。
- 两个新验证脚本：deployment/checks/harbor_modal_cleanup_smoke.py（真实provider已过）与fsdp_lora_merged_export.py（r2实际GPU通过）。
- docs同目录新增gpu-preflight.json、modal-provider-smoke-r2.json、modal-ingress-design.md、incremental-lora-sync-design.md。
- 原始GPU regression566pass/3error是远端rsync无.git造成历史fixture失败；只补git历史再跑3pass，未改测试或源码；历史失败日志保留。
- SSH偶发banner timeout；恢复后必须查原进程，不重复启动或把观测失败认作进程终止。
- 本机Modal配置已验证有shootime007工作区；Docker Desktop daemon未运行。未复用其他项目Cloudflare Tunnel。

## 最新导出节点
- a7f8344已push且远端SHA复核一致；包含b0b3967入口实现及真实GPU/Modal组件证据。
- fsdp-lora-export-r2.json：144 adapter参数更新、base_changed=0、399导出tensor，选定层base+delta精确相等、trainer完整恢复；真实进程exit0。
- r1额外启用use_orig_params=True导致FSDP前向断言；脚本改回recipe默认False后r2通过。原失败JSON保留。
- r2完成后核GPU进程释放；尚无双卡发布/独立reload结果。用户的双卡SSH/专用域名回复仍待提供。

## PR #3 已接收
- 核f43948b四项GitHub检查SUCCESS、MERGEABLE/CLEAN；已合并为2b3eff3，当前产品worktree安全fast-forward。
- 本地checkpoint save/resume探针未提交增量完整保留。verify-native-training-closure不再实施，由本会话统一执行。
- 新入口有效dataset预检/绝对step/最终checkpoint规则已纳入；这不代表GPU恢复通过。
- 单卡save-r3组件已启动，900秒界限；输出runs/fsdp-lora-save-r3.{json,log}及独立checkpoint目录，完成前不得重复启动。

## PR接管后的恢复验收
- PR #3已MERGED（2b3eff3），产品分支定向49项测试通过；485文件Ruff双门通过。
- save-r3保存10个native checkpoint文件并逐一hash；resume-r4新进程加载前验证fileshash，加载后全部trainer参数和optimizer哈希精确匹配。
- resume-r4继续2步非零梯度更新，144 adapter变、base不变，merged导出/恢复再次通过。RNG/scheduler加载有日志，但未逐项断言；trainer/TQ/rollout恢复未验收。
- 两进程已终止，GPU compute-app列表为空。实际checkpoint保留在远端runs/fsdp-lora-save-r3-checkpoint。
- 新/改文件：deployment/checks/fsdp_lora_merged_export.py；docs同目录fsdp-lora-save-r3.json、fsdp-lora-resume-r4.json、async-lora-validation.md；tasks/lessons、todo及本handoff。
- 不再重复原生入口实现。下一步用户双卡/域名资源就绪后，先真实preflight，再separate_async训练、权重发布、TQ恢复和独立serving验证。
