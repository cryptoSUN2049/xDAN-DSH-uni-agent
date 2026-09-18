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

Student候选Qwen3.5-9B，Teacher候选Qwen3.8-27B。8×A100是容量规划假设。2026-09-15用户另行授权实际GPU服务器进行完整代码集成测试，详见下方资源记录。

## 真实能力与缺口

最新上游entry.py仍拒绝teacher_client；限制始于2026-06-18 ee61374 / PR58，不是已知OPD回归。VERL有Teacher manager，Uni-Agent需要补传递、原始token评分、mask/位置/版本与TQ消费合同。不得只删除raise。

Tinker云P0已有9B/27B更新和独立推理reload，9个本地证据工件SHA一致；RL advantage全0，实际更新为OPD。不能将它认作Uni-Agent/VERL、正式TB、optimizer恢复或能力提升验收。

## 升级预检（历史，已完成）

固定上游合并已完成，提交 `0c61d01`；以下7个冲突均按两边合同解决并回归：
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

代码实施及下述GPU验证已授权；当前无push或训练成功证据。继续前先读handoff与integration-design，再核Git实际状态。

## 实际GPU验证授权与隔离

用户提供并授权 SSH `root@157.157.221.177 -p 12524 -i ~/.ssh/id_ed25519`，要求新建/复刻以当前worktree命名的独立uv环境，推进至代码集成测试验证通过。首次只读连接成功：单张RTX PRO 6000 Blackwell约96GB，driver595.91.07；不是8×A100。远端独立根 `/workspace/verl-uni-agent-harbor-opd-rl/`，下设src/envs/cache/runs。不能修改SkyRL/metarsi环境或停止其进程。参考SkyRL冷启动文档中的环境隔离、模型固定revision和完整更新/reload/resume验收；不照搬其trainer或依赖锁。实际可用显存以每次启动前检查为准。

## 用户补充：全异步与OPD

用户强调Student自主真实环境探索、Teacher在Student实际上下文逐token指导、Harbor verifier独立任务奖励。已纳入设计。固定VERL原生Teacher要求独立GPU池：colocate_async+OPD至少2卡，separate_async+OPD至少3卡角色；当前单卡可做组件与RL验证。已通过异步问题询问是否补卡，继续不依赖答复的测试。

依赖不能混称统一锁：UA requirements-test要求vLLM0.23/Ray2.54.1；新VERL uv.lock fsdp+vllm为vLLM0.24/torch2.11/Transformers5.9，TransferQueue精确commit434f8c476b4be24bc087e6e95070e64efcc739f9。当前GPU环境为UA测试lane，完整训练须单独验锁。

用户已答复资源安排：需要时可启动双卡服务器；现在先做代码/单卡验证，不重复问是否提供卡。双卡用于separate_async LoRA RL；独立Teacher组合还需第三角色GPU或另一次colocate OPD验收。优先目标是全异步高性能LoRA RL，OPD接线是其中一环。

## 2026-09-15 实施增量

Teacher桥接、超时、TQ/mask、recipes、真实生成版本准入已提交。`283e3a5`用固定VERL原生loss证明8项CPU梯度合同：RL与OPD独立、hybrid加权相加、工具token梯度为零。Framework/Gateway最近547项CPU回归通过；不代表GPU更新。

Modal已接入Worker/executor/isolated Trial可选后端和独立资源清理；Controller公网入口及registry frozen release仍未接通。当前回归用真实Harbor类构造和fake SDK，不是云端运行。单卡测试环境依赖仍在下载，不能声称GPU验证通过。

`3140271`修复NCCL异步LoRA同步：显式merge=true，18项recipe测试通过。当前为LoRA优化+完整merged权重同步，不是高性能增量adapter同步。用户新增明确授权按验证节点push并维护handoff/tasks/goal，平台goal已创建active；所有push必须Ruff双门。

2026-09-15后续节点：b0b3967接通Modal controller ingress和registry task preparation，217项CPU通过。独立GPU环境完成安装并实际BF16/NCCL/vLLM通过，Framework/Gateway566+3通过。真实Modal生命周期组件两sandbox已确认终止，证据docs同目录modal-provider-smoke-r2.json。没有真实DSH Modal任务/异步GPU训练闭环证据。已通过异步问题向用户请求双卡SSH和本项目专用Gateway域名，等待文本回复期间继续单卡验证。

真实4B LoRA导出r2已通过：144 adapter变、base不变、399tensor导出、选定层base+delta精确相等、trainer哈希精确恢复。r1验证脚本use_orig_params=True与recipe不一致，FSDP前向失败；脚本对齐False后通过，未改VERL产品实现。仍未验证双卡rollout publication/reload，不能宣称完整闭环。

用户明确PR #3交接由当前产品会话统一执行：已核f43948b四项checks并合并为2b3eff3，本地快进且49项定向测试通过。新save-r3/resume-r4真实单卡native checkpoint恢复通过：模型全参数与optimizer精确恢复后继续更新；不等于trainer/TQ或rollout恢复。对方verify-native-training-closure不再推进重复实现。

## 持续阻塞：2026-09-15

连续三轮核查仍缺双卡SSH与项目专用Gateway域名/Tunnel，现有服务器SSH均在banner阶段超时。最后一次exit255；未据此认定服务器/作业停止。没有启动重复作业。总目标未完成，平台goal转blocked，等待外部资源信息后恢复。

恢复入口：提供可连接双卡SSH、GPU型号/显存、专用Gateway域名与Tunnel配置位置；先读acceptance-status.md并核远端进程与源版本，再准备真实launch/data、preflight、双卡训练/发布/TQ恢复。已有4B单卡更新/导出/模型与optimizer恢复和Modal生命周期证据保留，不重做作为替代。

## 2026-09-16 路线决策：上游 Harbor 内置 agent 路线

用户拍板"直接走上游 Harbor 内置 agent 路线"：用上游 `uni_agent/tasks/harbor` adapter + Harbor CLI + `harbor_env: modal` + terminus-2，在 Terminal-Bench 2.1 上打通 Gateway rollout → verifier reward → VERL 更新。DSH-in-sandbox（自建 Controller / Cloudflare ingress / registry 镜像）暂停，训练通路证明后再把 agent 换回 DSH。

关键事实：
- terminus-2 和 Harbor CLI 跑在 GPU 宿主机进程里，只把 shell 命令送进 Modal 沙箱，LLM 调用从宿主机发往本机 Gateway（adapter 注入 `LLM_BASE_URL`/`HOSTED_VLLM_BASE_URL` 等），**不需要 tunnel、不需要发布镜像**。
- `--served-model-name hosted_vllm/<name>`：litellm 剥掉前缀后把 `<name>` 发到 Gateway；Gateway 不校验 model 字段。
- 上游文档 `docs/source/quickstart/harbor-integration.md` 的 Gateway rollout 标 "Not yet validated"，本分支在替上游验证。
- 用户要求 `agent.model.max_total_tokens` 用 32k（16k 跑不起来）；runner 固定 prompt 4096，所以 `--max-model-len` ≥ 36864。
- 环境：lane `envs/ua-verl-py312-vllm023-ws1` 加 harbor 0.16.1 + modal 1.5.5；Modal 凭据在 `/root/.modal.toml`（pod 重建后重拷）。
- 之前的 GPU venv 曾建在 pod 本地 `/tmp`，pod 重建后丢失；一切资产只放 `/workspace`。SSH 端口会随 pod 重建变化（现 30284）。
- 用户要求：及时按节点 commit/push，关键信息写入项目记忆（本文件）。

已证明：TB 2.1 oracle 2/2 resolved（Modal 沙箱 + verifier 通）；lane 激活证明与 GPU smoke 通过。

## 2026-09-16 12:10 首个学习信号

pass_ratio reward（verifier CTRF 部分得分）让 4B 在 easy 4 题上出现组内 reward 方差，GRPO 首次得到非零梯度：step1 grad_norm 0.0131 / step2 0.0156，reward 均值 0.21→0.41。此前 22 条二值 reward 全 0、梯度全 0。全流程由 `examples/harbor_opd_rl/run_tb21_pipeline.sh` 驱动，验收由 `stages/80_acceptance.sh`（wandb API + 本地指标 + checkpoint delta）给 PASS / MECHANICS_ONLY / FAIL。踩坑：小数据集下 `total_epochs=1` 只够 samples/batch 步，已按步数反推 epoch。

## 2026-09-16 16:47 路线 ① 机制闭环验收 PASS

`run_tb21_pipeline.sh` 一条命令跑完 env→data→oracle→rollout→train(3 步 colocate_async)→delta→resume(step 4)→summary→acceptance，verdict PASS（hard 3 项、soft 5 项全 true）。证据 `docs/verl-uni-agent-harbor-opd-rl/pipe-r1/`。wandb：train `ohz52n9r`、resume `6iwtnfu6`。
已知现象：grad_norm 只在组内有方差的 step 非零（step 1、3），step 2、4 组内同分 → 0；4B 在 easy 4 题上 16 条轨迹中 16 条撞 max_turns=50、5 条 completed。下一轮的杠杆：stage1 数据（多样性）、n=8、并发 16、held-out 打开、DAPO。

## 2026-09-17 00:45 2 卡 pod 与路线 ② 起步

用户开了 2 × RTX PRO 6000 的新 pod（端口 11965，共享同一 `/workspace` 卷；旧单卡 pod 12063 仍在跑 pipe-r2）。VERL 原生 Teacher 需要独立 Ray 资源池整数张 GPU，2 卡即满足：GPU0 actor+rollout，GPU1 Teacher。`TEACHER=1` 开关已进训练脚本（k1 on-policy 蒸馏 + task reward 的 hybrid）。pipe-r3 用 4B 自评 Teacher 先跑通接线；27B Teacher（`Qwen/Qwen3.8-27B`）与 9B Student（`Qwen/Qwen3.5-9B`）已在后台下载。

## 2026-09-17 01:55 路线 ② 接线证明

pipe-r3（2 卡，`TEACHER=1`，4B 自评）：Teacher vLLM 在 GPU1 常驻，step 1/2 完成 hybrid 更新，wandb 出现 `actor/distillation/*` 指标。自评 Teacher 下 distillation loss ≈ 0 是正确的零点校验（k1 = log p_student − log p_teacher）。27B Teacher 与 9B Student 已在 `/workspace/models/`，pipe-r4 只改 `TEACHER_MODEL_PATH`。

## 2026-09-17 07:46 pipe-r2（stage1 20 题纯 RL）验收 PASS
- 证据 `docs/verl-uni-agent-harbor-opd-rl/pipe-r2/`：acceptance.json（PASS，hard 3/3 soft 5/5）、report-tables.md、verdict.json、delta.json；wandb train `dzlqgapu`、resume `eg1ix7eo`。
- held-out（validation 5 题，n=1）：0.328 → 0.497（step 6）→ 0.458（step 7）；同一 checkpoint 两次评估差 0.06（0.497 vs 0.56），5 题的噪声就是这个量级，只作机制证据。
- 轨迹终止分布仍以 max_turns 为主（train 72/122、resume 22/42），parse_error 14/10；这两项是下一步的样本效率问题，不是链路问题。
- pipe-r3（4B 自评 Teacher，wandb `pg4xsj19`）重训中：step 1 约 906 s，distillation/loss ≈ -0.0001（自评应为 0），预计 09:30 UTC 前进入 delta/resume。
- 假 FAIL 修复提交 2466495、31bcea8，已同步两台 pod 的 `src/uni-agent/examples/harbor_opd_rl/stages/`。

## 2026-09-17 09:15 Modal 第三次触顶；pipe-r3 train 6 步完成，resume 待额度
- pipe-r3（TEACHER=1 4B 自评，wandb `pg4xsj19`）：train PASSED 08:30，6 步 grad_norm 0.0093/0.0219/0.0165/0.0172/0.0262/0.0297 全非零，score/mean 0.21→0.58→0.07→0.50→0.53→0.68，`distillation/loss` 量级 1e-4（自评应为 0）；delta 08:32 PASS（504/504、399/399）。held-out 训练前 0.597，resume 起点重评 0.41（5 题噪声）。
- resume（wandb `1t9jeruh`）step 7 checkpoint 已保存但指标未记录（09:10 额度触顶，进程 Traceback），目录移到 `resume-attempt3-quota-step7-nometrics`；已在 pod 11965 布置 `modal-quota-wait.sh && FROM_STAGE=resume` 脱离会话链，额度恢复后自动重做 resume→summary→acceptance。
- 4B TB 2.1 正式基线（`runs/eval-tb21-4b-base-n1-official`，n=1）：89 题，66 题有效得分，**0/66 通过**（rule-of-three 上界约 4.5%）；23 题因 ImageBuildError 6 / NotFoundError 4 / ConflictError 2 / ResourceExhausted 2 等未完成。这是第三次得到 0%，作为 4B 基线足够。证据 `docs/…/tb21-4b-baseline-n1/summary.json`。
- 待用户：在 Modal 工作区把 spend limit 调高（不只是加余额）。

## 2026-09-17 11:20 换 Modal 工作区，双卡与单卡同时训练
- **Modal**：用户提供新 profile `l98348740`（token 只写在本机与两台 pod 的 `~/.modal.toml`，不进仓库；旧 profile `shootime007` 保留、已不激活）。本机 `~/.zshenv` 另加了 `TINKER_API_KEY`。
- **双卡 pod 11965**：10:45 探针用新 profile 放行，pipe-r3 resume 自动开跑；因续跑链漏传样本上限（训练 4 题 / held-out 1 题）被我停掉，11:08 按冻结参数重跑（20 题 / 5 题，inherited 15 knobs）。之后 `runs/pipe-r4/chain.sh` 自动接 **pipe-r4：Qwen3.5-9B Student + Qwen3.8-27B Teacher**（`TEACHER_GPU_MEM=0.85`，模型拷到本地 NVMe，Terminal-Lego 20/5，6 步 + resume），脚本副本在 `docs/…/pipe-r4/chain.sh`。
- **单卡 pod 12063**：**pipe-r5：4B 纯 RL + DAPO=1**，Terminal-Lego 20/5，20 步（约 2 epoch），held-out 在第 0/10/20 步评估；独立数据目录 `data-r5`，与双卡互不覆盖。
- **SWE-rebench 暂不入训**：oracle 闸门发现 verifier 的 `pytest --ctrf` 在任务镜像里不可用、不写 reward（证据 `runs/pipe-r5/oracle-attempt1-swe-rebench-no-reward-file/`）；根因排查中，结论出来前两条线都只用 Terminal-Lego。
- **架构事实**：4B 与 9B/27B 词表不同（151936 vs 248320），27B Teacher 只能配 9B；Qwen3.5 训练需 fla（已装，ecbde4b）。
- **Modal 成本粗估**（每 trial 约 $0.033）：pipe-r3 收尾约 $1，pipe-r4 约 $5，pipe-r5 约 $12–16（DAPO 重采可能再加三到五成）。

## 2026-09-17 11:40 SWE-rebench 修复；Full 数据集现状
- SWE-rebench 25 题可用了：5fa9d6a 去掉等于 Dockerfile `FROM` 的 `docker_image`，oracle 复验 aiohttp-8538 / anta-969 / click-2788 全部 reward 1.0。已通知 Tinker 线（两个 xdan-dsh-uni-agent 会话）。stage1 现在可以 `STAGE1_SLICE=0` 混合 41 train / 9 val，从下一轮开始用。
- `gump2049/xDAN-Harbor-Stage1-Tasks-Full`（2026-09-17 11:11 UTC 发布，sha 209d36a）：Terminal-Lego 11051 train / 2765 val，SWE-rebench 1265 train / 316 val，状态"未审计"、`training_ready=false`。任务打包在 `<source>-full/<rev>/runtime-v1.tar.gz`，现有 `10_data.sh` 读不了，需要加解包。Tinker 线的审计进度：SWE 547/1581 已审计，471 通过、76 失败；Terminal-Lego 尚未审计。

## 2026-09-17 12:20 pipe-r3 验收 PASS；换回 GRPO、放开并发、切到 40/7 审计混合集
- **pipe-r3 PASS**（约 12:10 UTC）：4B 自评 Teacher，6 步 + resume 到 step 7，7/7 步 grad_norm 非零，与 wandb 逐步对账一致，adapter 变、base 不变。wandb train `pg4xsj19`、resume `zlimfmcf`。证据 `docs/…/pipe-r3/`。**路线 ② 接线闭环**。
- **pipe-r5 停止**（12:06）：V1 下 DAPO 逐批补采，步长约翻倍；DAPO 开关原本设置的参数被 V1 忽略（469b09b 已改为 `max_inflight_gen_batches`）。按用户意见换回 GRPO。
- **数据**：Tinker 线在源头删掉了 `docker_image`，并排除 3 道审计未通过的 SWE 题；已审计集 sha 1129d6e 共 47 道，训练 40、验证 7。数据阶段默认只收 `nop_oracle_audit.passed=true` 的题。
- **pipe-r6（单卡，12:08 起）**：4B GRPO，40/7，`TRAIN_BATCH_SIZE=4 CONCURRENCY=32`，20 步（2 epoch），第 0/10/20 步评 held-out。
- **pipe-r4（双卡，12:16 重起）**：9B + 27B Teacher，同一份 40/7，batch 4、并发 32，6 步 + resume。第一次按 Terminal-Lego 20/5 起跑，到 oracle 阶段时停掉，旧目录改名为 `*-attempt1*`。
- **与 Tinker 线的协调**（会话 `xdan-dsh-uni-agent-e1`）：共用 Modal l98348740 的 spend limit，对方同意我们用 48 并发，对方自己 16 并发，新工作区偶发 "App create rate limit exceeded"。Full 仓库归档已去掉 `docker_image`。SWE 全集审计进度 558/1581，通过率约 86%，预计明天下午完成。Terminal-Lego 前 104 道审计明早出结果，逐题状态写在 `audits/harbor-sources-audit-{swe,tl}-full/audit-status.jsonl`。

## 2026-09-17 13:45 未完成 trial 的计分语义
- 现状（f81ae2c 部署前）：Harbor trial 只要没完成就记 0 分。模型改坏代码时 0 分是对的；沙箱或 verifier 故障时 0 分是错的，会给轨迹一个很强的负 advantage。
- f81ae2c：`failure_kind` 分为 agent 和 infra。infra 默认抛异常，只剔除这一条会话；`HARBOR_INFRA_FAILURE=zero` 恢复旧行为。已在隔离目录里用 lane 解释器跑过测试，20/20 通过。**尚未部署**，等 pipe-r4 和 pipe-r6 结束后再部署。
- pipe-r4 13:19 完成初始化（9B 占 61 GB，27B 占 86 GB，没有 OOM）；pipe-r6 在 13:20 左右已跑完 27 条 trial，平均分 0.78。wandb：pipe-r6 train `r382x2fw`。

## 2026-09-17 14:00 pipe-r4 OOM 重起；Full 数据阶段就绪；时间预估修正
- pipe-r4：第一次训练 13:41 时 9B 推理引擎 OOM，13:47 以 `ROLLOUT/TEACHER_MAX_NUM_BATCHED_TOKENS=8192` 从训练阶段重起，env/data/oracle/rollout 四个阶段直接复用。
- pipe-r6：第 1 步在 13:37 保存，约 30 分钟一步（SWE 冷镜像）；held-out 训练前 0.559（wandb `r382x2fw`）。数据按目录名排序，每 5 步换一次来源，读曲线时只比较同一来源。
- 预计完成时间（北京时间）：pipe-r4 约 06:00–08:00，pipe-r6 约 07:00–09:00。
- Tinker 线：Terminal-Lego 前 104 道审计通过 102 道，SWE 已审 629 道、通过 502 道。评分器已按同一规则修复（351e691）；run_tests.py 要等全集审计完成后才改源头，在此之前我们保留兜底逻辑。
- 已提交但**未部署**：f81ae2c 与 e50b110 里 `uni_agent/tasks/harbor/reward.py` / `task.py` 的改动，等两条 run 结束后再同步。`10_data.sh` 和训练脚本已同步（默认行为不变）。

## 2026-09-17 14:05 单卡改作对照组：pipe-r6 停止，pipe-r7 = 9B 纯 RL
- 用户决定保留单卡 pod 作为对照组。pipe-r6（4B）和 pipe-r4 的模型、步数都不同，数据还按来源成块排列，当不了对照组，所以跑完第 1 步后停掉，停止原因已写进 `runs/pipe-r6/pipeline-summary.jsonl`。
- **pipe-r7**（单卡，14:02 起）：Qwen3.5-9B，与 pipe-r4 完全镜像，唯一区别是 `TEACHER=0`。数据同为 40/7 审计集，每步 4 题 × 8 条、并发 32，6 步 + resume，`ROLLOUT_MAX_NUM_BATCHED_TOKENS=8192`。参数用 diff 核对过，只差 DATA_DIR 和 Teacher 相关项。脚本在 `docs/…/pipe-r7/chain.sh`。
- 明早比较 pipe-r4 和 pipe-r7：训练集 reward、held-out 7 题、每步耗时（Teacher 的开销）、`actor/distillation/*`。结论只看方向，6 步证明不了效果。
- Modal：我们峰值 64 个并发，已向 Tinker 线更正，对方如遇持续限流，我们先降到 16。

## 2026-09-17 14:50 两条 9B 同步改用保守引擎设置后重起
- pipe-r4 第二次训练 14:41 OOM：9B 引擎从 45 GiB 涨到 91 GiB（见 lesson 35）。pipe-r7 还没 OOM，但为保持对照一致一起停掉。两边 14:48 从训练阶段重起：`ROLLOUT_ENABLE_PREFIX_CACHING=False ROLLOUT_MAX_NUM_BATCHED_TOKENS=4096 GPU_MEMORY_UTILIZATION=0.40`；pipe-r4 的 Teacher 仍是 8192 单批、0.85 显存比例。已从 train-command.txt 核对确实生效（408c81b）。
- 关掉 prefix caching 后，多轮对话每一轮都要重新预填充，生成变慢。预计完成时间推迟到北京时间 08:00–10:00。
- 旧的训练目录保留为 `train-attempt-2-vllm-growth-oom-8192`（r4）和 `train-attempt-1-stopped-for-parity`（r7）。

## 2026-09-17 16:00 纠正：OOM 出在 Teacher；pipe-r4 第 4 次训练
- 三次 OOM 都是 Qwen3.8-27B Teacher（GPU1，显存比例 0.85），prompt logprobs 缓冲放不下。14:50 那条"9B 学生引擎显存增长"的记录是误判（见 lesson 33、35 的更正）。
- pipe-r4 于 15:48 从训练阶段重起：`TEACHER_GPU_MEM=0.70 TEACHER_MAX_NUM_BATCHED_TOKENS=4096`。学生侧仍是 prefix caching 关、单批 4096、显存比例 0.40，与 pipe-r7 一致，已从 train-command.txt 核对。三次失败的训练目录已按 Teacher OOM 重命名。
- pipe-r7 不受影响，一直在正常训练。监听预警改为任何 vLLM 进程达到 85 GiB 就报，Teacher 也覆盖在内。
- 下一轮：学生侧恢复 prefix caching、8192、0.45（两边同步），Teacher 保持 0.70 / 4096。
- 16:00 按用户要求 Teacher 再保守一档：`TEACHER_MAX_NUM_BATCHED_TOKENS=2048 TEACHER_MAX_NUM_SEQS=4`，显存比例保持 0.70；pipe-r4 第 4 次训练在初始化阶段停掉，改为第 5 次重起。学生侧和 pipe-r7 保持一致，不动。

## 2026-09-17 16:10 设置 v2（用户决定）；单卡 pod 失联
- 用户确认 2 卡方案：GPU0 放 9B 学生，GPU1 放 27B Teacher，不加卡。设置 v2：Teacher 单批 4096（显存比例 0.70、最多 4 条序列不变）；学生侧恢复 prefix caching 开、单批 8192、显存比例 0.45；对照组同步修改（da036c7）。
- pipe-r4 第 5 次训练在初始化时停掉，16:09 按 v2 从训练阶段重起（第 6 次），生效参数已从 train-command.txt 核对。
- **单卡 pod（12063）约 15:52 起卡住**：pipe-r7 此后没有任何写入；约 16:01 起 SSH 握手一直被对端断开，但 TCP 端口仍然通，原因未知。pipe-r7 v2 的启动脚本已放到 `runs/pipe-r7/chain.sh.v2`，pod 恢复后要先停掉旧会话（sid 304956），再用它替换 chain.sh 并重起。如果 pod 被重建，端口会变，需要先跑 `gpu-pod-restore.sh <新端口>`。

## 2026-09-17 16:50 共享评估集 eval-set-v1 已冻结，数据阶段默认剔除
- Tinker 线的用户已确认保留名单：`gump2049/xDAN-Harbor-Stage1-Tasks-Full` 的 `eval-set-v1/reserved.json`，冻结于 2026-09-18 00:43（北京时间），数据集 sha 957c879。SWE 按仓库保留 37 个，Terminal-Lego 按题保留 308 道。判定规则：Terminal-Lego 的 task id 在名单里即算保留；SWE 的 task id 去掉末尾的 `-数字` 得到仓库名，仓库在名单里即算保留。
- `10_data.sh` 默认剔除保留集，关闭用 `STAGE1_EXCLUDE_RESERVED=0`。在 Full 上实测：剔除 170 道后，Terminal-Lego 剩 96 道、SWE 剩 467 道可选；按每个来源 50 训练 / 20 held-out 选题，与保留集重叠 0。
- 下一步 held-out：Tinker 线明天上午会从保留集中挑 50 道 SWE、50 道 Terminal-Lego，都是基座 9B 时对时错的题，发出 manifest。届时我们把 held-out 换成这份 manifest，两条线就在同一套题上比较 checkpoint。

## 2026-09-17 17:2x pipe-r4 第 1 步：真 Teacher 信号出现，但数据对 9B 太简单
- wandb `m848n94f`，第 1 步（9B Student + 27B Teacher，设置 v2，无 OOM）：
  - `actor/distillation/loss = 0.1224`、`abs_loss = 0.2135`（4B 自评 Teacher 时是 0.0001）→ **路线 ② 的真 Teacher 信号确认**。
  - `actor/grad_norm = 0.1035`，比 4B 几轮的 0.01 大一个量级。
  - `critic/score/mean = 0.9163`（max 1.0 / min 0.857），训练前 held-out 0.988 → **审计通过的 40 题混合集对 9B 已接近饱和，组内几乎没有方差**，GRPO 学不到东西。
  - `timing_s/step = 1733`（gen 969 / update_actor 517 / old_log_prob 209），回复平均 24691 token、62.9 轮。
  - Teacher 打分没有单独计时项，要用 pipe-r7 对照组的每步耗时差值来估算。
- **结论影响下一轮选题**：不能只按"审计通过 + index 顺序"取题，要挑对 9B 有难度的题（基座时对时错）。Tinker 线的 eval-set-v1 用的就是这个筛法，同样的规则应该用到训练题上。

## 2026-09-17 17:45 Tinker 线的长度偏置警告（对 OPD 线直接相关）
- 他们的 r4（9B Student + 27B Teacher，24 题 5 次更新）训练后在 4 道留出题上**退步**：15/16 → 11/16。原因是输出暴涨：同一道题训练前每次 3.6k–5.5k action token 且 4 次对 3 次，训练后 25k–109k token 且 4 次全错，大多跑满 32 轮。每轮平均约 3.4k token，未触及单轮上限，所以不是截断，更像 OPD 的奖励或损失里存在长度偏置。
- 我们的起点已经很长：pipe-r4 第 1 步 `response_length/mean = 24691`、`num_turns/mean = 62.9`（配置 `max_turns=50`，指标定义待核，怀疑统计的是消息条数）。监听已加逐步长度、轮数、得分、蒸馏 loss 的跟踪。
- 判据：若第 2 到 6 步长度持续上升而 `critic/score/mean` 不升，就按同一个长度偏置处理（对策：奖励里加长度惩罚、或降低蒸馏系数、或限制轮数）。
- 他们还将发布 `eval-set-v1/base-rates.jsonl`（保留集逐题基座通过率，Qwen3.5-9B，32 轮 / 32768 token / temperature 1.0），只能用于校准选题规则，不能用于训练。训练题的通过率筛选需要他们的用户批预算。
- Terminal-Lego 全集难度分布：easy 9223、medium 4440、hard 153，按 index 顺序取几乎全是 easy。
- 口径核对（与 Tinker 线对齐）：我们的 `num_turns` 是消息条数 + 1（工具返回算 user 消息），62.9 ≈ 31 次模型动作，未越过 `max_turns=50`；每次动作约 796 token。Tinker 线训练前每次动作 110–170 token、训练后 780–3400，单条轨迹 3.8k → 26k。**我们第 1 步的 24.7k 起点高，主要来自 terminus-2 的风格差异，所以只看相对变化（第 1 步作基线），不与他们的绝对值比较。** 他们 reward 是二值、`kl_penalty_coef=1.0`、group_size 4；我们是 pass_ratio、无单独 KL 项、group_size 8。

## 2026-09-17 20:07 pipe-r4 验收 PASS：路线 ② 真 Teacher 全流程闭环
- 9B Student + 27B Teacher，审计混合集 40 训练 / 7 held-out，每步 4 题 × 8 条、并发 32，6 步 + resume 到第 7 步，全程无 OOM。wandb `m848n94f`，证据 `docs/…/pipe-r4/`。
- 验收 PASS：hard 3/3、soft 5/5；7/7 步 grad_norm 非零（0.089–0.153）且与 wandb 逐步一致；delta 通过：adapter 496/716 变、base 760/760 不变。
- 蒸馏 loss 全程 0.10–0.13（4B 自评 Teacher 时为 0.0001）→ **真 Teacher 信号确认**。
- 轨迹长度 24691 → 20869 → 21034 → 25801 → 14649 → 14351，**没有出现 Tinker 线的长度暴涨**，反而收敛。
- **held-out（7 题）：训练前 0.988 → 训练后 0.914，下降**。这套 held-out 已饱和（训练前近满分）、只有 7 题、reward 是 pass_ratio，波动 ±0.07 属噪声范围，但方向与 Tinker 线 r4 的退步一致，需要在 100 题评估集上复核。
- 每步耗时 1079–1732 s；Teacher 打分没有单独计时项，仍需 pipe-r7 对照组的差值来估算。
- 单卡 pod 从 15:52 起失联，对照组 pipe-r7 未能启动；双卡 pod 20:0x–20:37 期间 SSH 也间歇性无响应，但训练未受影响。

## 2026-09-18 00:20 固化：一条命令起一轮训练；Modal 再次触顶
- **Modal 工作区 `ac-zkyegsbayv51TZenFRbIqQ`（profile l98348740）花费上限触顶**，两条线都无法创建沙箱。我们的探针与 Tinker 线的报错一致。需要用户在 Modal 设置里调高本账期上限（不是余额问题）。
- **并发约定（与 Tinker 线）**：恢复后我们固定 16；他们评估筛选期间 32、筛完降到 8，峰值 48（昨晚 64 打穿了上限）。
- **新入口 `examples/harbor_opd_rl/run_opd_round.sh`（a5bb9c8）**：替代一次性的 chain.sh。默认值即 pipe-r4 验证过的设置：9B 学生 + prefix caching + 单批 8192 + 显存比例 0.45；Teacher 0.70 / 4096 / 4 条序列；并发 16；数据取审计通过、剔除共享评估集、只要 medium/hard。`--smoke` 跑 1 步 4 道题。内置模型本地暂存、等 Modal 额度、等前一条 run 退出。
- **已部署**（此前因有 run 在跑而推迟）：`uni_agent/tasks/harbor/{reward,task}.py` 的基础设施故障剔除（f81ae2c、e50b110），已校验共享盘与本地一致。
- **已排队**：`runs/pipe-r8-smoke`，额度恢复后自动开跑（9B + 27B Teacher，1 步 4 题）。冒烟通过再起正式一轮。
- 教训：换模型或换关键配置前先跑 `--smoke`。pipe-r4 连续 5 次失败尝试浪费了约 500 条 trial，一次冒烟只要几十条。

## 2026-09-18 01:00 Modal 成本复盘与沙箱纪律
- 账单事实（`modal billing report --for yesterday --show-resources`）：2026-09-17 `__harbor__` 应用 CPU 267.88 + 内存 90.20 = 358.08 美元，GPU 为 0；Tinker 线三个应用合计 6.52 美元。工作区本账期已计费 439.25，触发 `billing cycle spend limit`，两条线同时停摆。
- 折算（**2026-09-18 更正**：下面原写的 2840 小时、14 倍按 Function 单价算，是错的）：按 Sandbox 单价，CPU 267.88 美元约合 1888 核时，内存 90.20 美元约合 3756 GiB 时，按 2 核 4 GB 都折合约 940 沙箱小时，与 SandboxList 实测 953 小时一致。当天约 700 条 trial、每条实际 10–20 分钟，应约 200 小时，计费约为实际的 **4.8 倍，约八成空转**。
- 根因：Harbor `harbor/environments/modal.py:881` 写死 `sandbox_timeout_secs=86400`、无空闲超时，CLI 被杀不销毁沙箱。当天我们强杀 7 次训练（5 次与 27B Teacher OOM 有关），每次 16–32 个沙箱留在后台计费。次因：统一 2 核 4 GB 覆盖（任务只要 1 核 1–2 GB）、沙箱等 GPU 生成时照常计费、两条线共用工作区 64 并发跑整夜。
- 已落地的纪律（提交 2957442、7cf1876、9a491ea、1cc29a7）：规格改回任务契约；trial 超时 1800；`modal-sandbox-cleanup.sh`（带 `--older-than` 保护）；`modal-sandbox-guard.sh` 已在 11965 常驻（15 分钟一次，清理存活超 60 分钟的沙箱，日志 `runs/modal-guard.log`）；`run_opd_round.sh` 开跑前自动清理；默认并发 16；`--smoke` 先行。
- 待用户：Modal 后台调高本账期上限（建议改按天）；重启单卡 pod。
- 新文档：`docs/…/modal-cost-postmortem.md`（复盘）、`docs/…/modal-alternatives-brief.md`（替代沙箱调研简报，供独立会话执行）、`tasks/handoff.md`（已重写）。
- 待验证：`deployment/bootstrap/modal-sandbox-probe.sh` 额度恢复后先跑，实测规格、正常结束是否自动销毁、被杀后是否泄漏、清理脚本能否收拾。

## 2026-09-18 00:55 沙箱生命周期实测结论（证据 `sandbox-lifecycle/probe-report.md`）
- **正常结束会释放**：trial 运行中 1 个沙箱，退出码 0，结束 20 秒后为 0。
- **客户端被杀会泄漏**：杀掉 Harbor CLI 后 30 秒、90 秒仍各有 1 个沙箱存活。这就是 2026-09-17 那 358 美元的来源，现已实证。
- **清理脚本可用**：`terminated 1, kept 0`，清理后为 0。修复版通过 SandboxList RPC 读 `created_at`（modal 1.5.5 的 `Sandbox.list()` 没有这个属性），年龄未知一律保留。
- **设计已改为创建时传参**（用户要求，也是正确做法）：`environment_kwargs` → `sandbox_timeout_secs=2700`、`sandbox_idle_timeout_secs=1200`、`app_name=verl-harbor`，Harbor 经 `--environment-kwarg` 透传，Modal 服务端强制执行。守卫降级为手动兜底，不再常驻。
- **更正**：复盘里"命令行没暴露 sandbox_timeout_secs"是错的（`cli/trials.py:411` → `factory.py:313`）。由会话 xdan-dsh-uni-agent-67 指出并修复清理脚本的误杀缺陷。
- 我引入过一个严重缺陷：清理脚本把"年龄未知"当成"该杀"，常驻守卫会终止所有运行中的沙箱。在误杀发生前停掉了守卫。教训：先查上游有没有声明式参数，再考虑外部轮询补救。

## 2026-09-18 02:45 本轮数据与训练计划已落盘
- 按约定写进 `tasks/todo.md` 的「阶段 H」：H1 数据计划、H2 训练计划、H3 判据、H4 明确不追求的。
- 数据侧改用官方合并索引 `audits/passing-tasks.jsonl`（baf66ee），题池 Terminal-Lego 81 / SWE 422（medium-hard），50+50 的正式轮次不再缺题。
- 训练侧：冒烟通过且成本核验通过后起 pipe-r9（9B + 27B Teacher，100 题、20 步、并发 16），单卡恢复后起 pipe-r10 对照组（`TEACHER=0`）。
- 判据四条缺一不可：成本、机制、学习信号、长度副作用。明确不追求 TB 2.1 分数提升和 held-out 绝对分数结论。

## 2026-09-18 03:05 数据源改为官方训练切片
- 数据线由会话 xdan-dsh-uni-agent-5e 统一负责，发布了两个切片：`stage1-swe150-tl50-v1`（200 训练 / 8 验证）和 `stage1-swe300-tl200-v1`（500 / 8），小切片是大切片的前缀，验证集共享。保证：审计通过、剔除 eval-set-v1、对 23 个评测做过防污染（15406 道全集派生题拒绝 0、标记 0，SWE 仓库与评测仓库交集 0）。
- 选题规则：各来源内按 sha256(task) 排序，每仓库最多 30 道；验证集取每来源前 4 道。
- 难度：swe150-tl50 的训练题中 SWE 有 59 道 easy、89 medium、2 hard，Terminal-Lego 50 道全是 medium。我们在切片上再筛 medium/hard，得到 148 道（TL 50 / SWE 91）。
- 数据阶段支持 `STAGE1_SLICE_NAME`（5712381）。已请 5e 确认"在切片上再筛子集"是否可接受，或出一个 medium/hard 的官方切片以保证两条线训练集完全一致。

## 2026-09-18 03:45 决定：沙箱继续用 Modal
- 用户决定继续用 Modal，不迁移。依据：RunPod Pod 不能自建 Docker（官方文档写明 "you cannot spin up your own Docker instance or use Docker Compose on Pods"，博客称 Kata 时代的 Docker-in-Docker 已取消；实测无 CAP_SYS_ADMIN、用户命名空间与 overlay 挂载被拒、cgroup 只读）；另租 Docker 虚拟机与修好泄漏后的 Modal 成本同一量级。
- 降本方向改为减少沙箱小时数：每题采样 8→4（成本减半）、轮数上限 50→30（降三到四成），在小切片上先做对比；并发与 GPU 吞吐匹配，避免沙箱排队空等。
- 重新评估迁移的触发条件：出现已付费且闲置的 Docker 机器，或换到支持特权容器、训练与沙箱同机的 GPU 平台。
- 同日成本预估更正：581 道有信号的题（SWE easy 379 + Terminal-Lego medium 202）跑一遍约 4648 条轨迹、约 833 沙箱小时，Modal 约 55–70 美元（此前"100 美元以上"估高了）。以 pipe-r9 成本核验的实测单价为准。**（2026-09-18 05:00 更正：55–70 美元用的是 Function 单价，错。按 Sandbox 单价约 100–160 美元，见下一节。）**

## 2026-09-18 05:10 成本核验阶段修复与单价更正
- **单价更正**：Modal 沙箱按 Sandbox 单价计费（CPU 每核每小时约 0.142 美元、内存每 GiB 每小时约 0.024 美元，是 Function 单价的 3 倍）。09-17 事故计费约 950 沙箱小时，对约 200 实际小时，4.8 倍、约八成空转，不是 14 倍。由 e1 和会话 67 指出，e1 已按此改好 W38 周报第 15、87 行（提交 02791a2）。
- **581 道题预算更正**：约 4648 条轨迹。按 pipe-r4 每条 10.75 分钟算约 140–160 美元；按 pipe-r9 中途实测每条约 0.023 美元（本切片 trial 平均约 5 分钟）算约 110 美元。区间约 100–160 美元，以 pipe-r9 cost 阶段终值为准。之前给用户的 55–70 美元偏低。
- **cost 阶段重写**（`stages/cost_report.py` + `90_cost.sh`）：按小时取本轮时间窗内本轮 app 的 CPU/内存账单（`modal billing report -r h --show-resources --json`，`--end` 取明天以包含当前小时）；app 从任务配置 `environment_kwargs.app_name` 读；测不到记失败；开始前等 300 秒让账单与沙箱回收落定。已原子替换到 11965 的 `src/uni-agent`，pipe-r9 结束时生效。pipe-r9 中途试跑：50 条 trial、4.18 小时、计费 1.14 美元、每条 0.023 美元（中途比值偏高，因为进行中的 trial 已计费但未计入完成时长）。
- **oracle 阶段的沙箱原先落在 `__harbor__`、生命周期 24 小时**：新增 `examples/harbor_opd_rl/tb21_oracle.yaml`（同样的生命周期与 `verl-harbor` app），`common.sh` 默认指向它。未部署到 pod（pipe-r9 的 oracle 已跑完），下次同步时生效。
- **Modal 额度风险**：2026-09-18 00:00–04:35 UTC 全工作区已花 34.77 美元，Tinker 线约 32 美元（eval-pool 约 19、runner 约 8.5），本线约 2.7。pipe-r9 余下约 15 美元。用户只充值了 50 美元，额度可能在今天触顶，需用户确认上限。
- **pipe-r9 训练进度**：第 1 步 23 分钟，第 2 步约 27 分钟。有得分差异的题，第 1 步 4 道中 1 道，第 2 步 4 道中 2 道。第 1 步平均分 0.729，平均回复长度 1.54 万 token，平均轮数 42.6，梯度范数 0.108。训练前验证分 0.924，平均轮数 49.4，几乎跑满 50 轮上限。
- **wandb 每步指标晚一步出现**：VERL 用 `logger.log(step=N)`，wandb 要等 step N+1 写入才提交第 N 行。实时看分数读本地 `train/rollouts/*/*/<N>.jsonl`。

## 2026-09-18 05:25 限制核查（应 e1 建议，对照 Tinker 线 r5 的失败原因）
- **额度**：e1 用账单 API 查到，本账期截至 05:00 UTC 约 400 美元，用户设的上限是 500 美元。Tinker r6 加评估约 60 美元，pipe-r9 余下约 15 美元，放得下，但余量不宽。
- **上下文不超限**：学生 max_model_len 36864，Teacher 36865，都远低于 65,536。第 1 步有 3.1% 的轨迹碰到 32768 回复上限被截断。
- **任务声明的智能体时限没有执行**：`tb21_terminus2_smoke.yaml` 的 `agent.timeout_sec: 1800` 经 `--agent-timeout` 变成 Harbor 的 `override_timeout_sec`，覆盖任务声明值（Terminal-Lego 600 秒、SWE 900 秒）。pipe-r9 前 109 条中，TL 57 条有 9 条、SWE 52 条有 20 条总时长超过声明值（总时长含建环境和判分）。本轮不改：墙钟时间大头是排队等共享 GPU 生成，硬切会把基础设施的慢算到智能体头上，且中途改配置破坏一致性。
- **隐患**：智能体时限 1800 秒等于整条 trial 时限 1800 秒，智能体用满时判分没有时间，整条被杀。本轮最长 1311 秒，p90 1139 秒，尚未触发。
- **下一轮待改**：智能体时限改为"任务声明值 × 倍数"（Harbor 支持 `--agent-timeout-multiplier`），整条 trial 时限设为"智能体 + 判分声明值 + 余量"，沙箱寿命保持 trial 时限的 1.5 倍。

## 2026-09-18 05:40 pipe-r9 效果核查：SWE 部分分奖励有高下限
- 证据 `pipe-r9/reward-floor-finding.md`。`pass_ratio` 下 SWE"什么都不做"下限中位数 0.936（50 道中 30 道 ≥ 0.9），验证集 4 道 SWE 下限 0.95–0.98。训练前验证分 0.924 几乎全是下限，SWE 0/4 解决。
- 前 3 步 SWE trial：解决 26、停在下限 9、低于下限（改坏）22、高于下限 1。没人解决的组在奖励"少动代码"。
- 按步二值解决率（SWE / TL）：第 1 步 0.00 / 1.00，第 2 步 0.45 / 0.68，第 3 步 0.92 / 0.17。每步只有 4 道题，按题波动很大，不能当趋势看。
- wandb 第 2 步：平均回复长度 1.92 万（第 1 步 1.54 万），平均轮数 34.7（第 1 步 42.6），梯度范数 0.08，蒸馏损失 0.101。
- 默认奖励改为 `binary`（仓库已改，未部署到 pod）。pipe-r9 是否停止、改二值重开，待用户决定。

