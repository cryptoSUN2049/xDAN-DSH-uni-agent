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

