# DSH 数据与 SFT 专题研读（只读）

研读日期：2026-09-08。已完整抽取并读取所选五份 HTML 的正文；没有运行源仓库脚本、读取私有 runs、核实 GPU receipt 或调用教师。下文“已实现/已运行”若无特别说明均是被审文档的声明，不是本轮复验结论。

## 来源与冻结身份

### page-016 — DSH 一源双后端：ms-swift / VERL 训练数据设计
- 源文件：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/m3-nanogpt-sft-lora/docs/m3-nanogpt-sft-lora/dsh-ms-swift-one-source-three-projections-design.html`
- SHA-256：`14d48c9bba8f6f3b6fa49edfa3ab5bd5821a0d65737718b51176f9c9dbbc7346`

### page-017 — DSH 自进化数据层规划 v1.1 · 2026-09-01
- 源文件：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/m3-nanogpt-sft-lora/docs/master/DSH自进化数据层规划-v1.1-20260901.html`
- SHA-256：`6395286c73928ca921350760a4b407db883a2229a2acb42a4e49e4dfbd4a27e0`

### page-020 — DSH 全局数据生成地图
- 源文件：`/Users/gumpm5/.gstack/projects/cryptoSUN2049-xDAN-DSH-Exp/designs/global-data-generation-map-20260902/finalized.html`
- SHA-256：`ed0890407030ad3b439a6834ef0f027553798220b59dd44a6634baf245ee5aba`

### page-022 — DSH 模型能力结果导向数据生成计划 v1.0
- 源文件：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/m3-nanogpt-sft-lora/docs/m3-nanogpt-sft-lora/DSH模型能力结果导向数据生成计划-v1.0.html`
- SHA-256：`0c4aa9be102025501a8dfb1e60a8abf8482580c33eb79cb3bd03ea4cbc166072`

### page-033 — DSH 场景 × 能力 SFT 执行生成计划 v1.0
- 源文件：`/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/m3-nanogpt-sft-lora/docs/m3-nanogpt-sft-lora/DSH场景能力SFT执行生成计划-v1.0.html`
- SHA-256：`c2baf55f0d9dfbf4ef03f0b49a738e1a576d9bbf2ff397489d8a32794a869787`

## 最有价值的三个结论

1. 当前主线不缺另一份抽象训练路线，而缺 canonical-first、split-aware 的训练数据入口，以及把 SFT 与 Online RL 的资格分开判定。page-033 点出具体泄漏路径：per-run `swift-sft.jsonl` 及 SFT lineage 没有 task/split，split 只保存在 canonical task；直接拼接这些 JSONL 会把 validation/held_out 轨迹送入优化器。
2. DSH 数据侧确有较新的真实执行声明：page-022（2026-09-04）和 page-033（2026-09-05），绑定 source snapshot `6547e9877bd7`，记载 Terminal 4/4＋Repository normal 1/4＝5/20 accepted teacher trajectories，其中 train 3、validation 1、held_out 1。它比 page-020 的 2026-09-02 0/20 更新。该证据来自 **m3-nanogpt-sft-lora**，不是用户此前提到的 **dsh-official-training**，也不是当前 Uni-Agent/Harbor run。需核对其 canonical/reload receipt 后才能复用数据；不能宣称这5条证明 Agent RL 参数更新。
3. “熟练使用 DSH”与“修改 DSH”已有成熟拆分：Operator O1–O7 与 Maintainer O8–O9。当前8个 executable tasks 只覆盖基础工具时序、bash/editor、部分权限/timeout；不证明 Cordis composition、provider swap、跨 Session 主动 resume、subagent orchestration 或 RSI。应按实际行为建立训练任务，而非把架构名称写入标签就声称掌握。

## 逐文档证据与可复用范围

### page-016：一源双后端

- §1–3：“一源”是内容寻址的来源图，不是一个含大量可选字段的万能 schema。`dsh.sft.v1`、`dsh.preference.v1`、`dsh.online-rl-seed.v1`、历史 `dsh.rl-episode.v1` 各自有语义边界；ms-swift 与 VERL 分别直接投影 canonical source。
- §4–6：golden set 定义 assistant/tool-call loss、reasoning 策略、tool schema/call/result、恢复与安全停止样例；模板、golden set、review 各绑 hash。本文 V1 `reasoning=excluded`、历史 assistant loss=false/current target=true，是旧模板选择而非永恒限制，应对4B/9B重新冻结。
- §3、5、7：旧 episode 不能直接作为 on-policy trajectory；Offline renderer 不能补造 behavior logprobs/exact mask/fresh reward。runtime sidecar 需 exact IDs、response mask、generation logprobs、step ranges、fresh verifier identity。工具/环境 token mask=0。
- §9–10 声称已实现 native renderer、Parquet转换、trajectory validator、lineage、staging+atomic rename；列出 `scripts/trace-training/{training-backend-types.ts,ms-swift-native.ts,verl-native.ts,dual-export.ts,verl_parquet.py}`、对应 schema和spec，**目标镜像 loader smoke、GPU更新、held-out uplift仍未跑**。本轮未审这些代码或测试。
- 一个值得复核的例子：§5“VERL SFT 初始化行”展示的是 prompt/reward metadata，没有显式监督 response；仅凭此 HTML 不能证明符合当前 VERL SFT loader。必须看实际 renderer + 固定版本 loader，不能复制例子当可运行合同。

### page-017：数据层v1.1

- §02、03：固定 DSH 先学 Agent Policy；之后受控 Harness Controller；模型/记忆/Harness归因与生产 mutation 分阶段。三轴正交：训练信号（SFT/Preference/RL）、交互长度（short/long）、任务环境（terminal/repo/nanoGPT）。
- §09–10：DSH durable trace拥有环境事实；Uni-Agent Gateway负责精确token/mask/logprobs；Swift离线、VERL在线。禁止由文本倒推token；模型不能写裁判/共享Registry。
- §11：固定预算的B0/B1对比，模型×Harness配对归因，质量/效率/恢复/合法性分别报告；提到15%效率改善是待预注册提案，不是已达结果。
- 旧范围：`Qwen3.8-27B-Instruct`、nanoGPT hero、80 teacher＋80 control、8 trainable场景、6/2/2 split；它是9/1历史方案，不应直接覆盖当前4B/9B＋terminal优先范围。文档公开数据表的模型归属、许可、数量都是旧快照/卡片声明，本轮没外网核实，不能变成当前采购与训练名单。
- 自身明确：long是规划轴，尚无可运行10+step long environment；训练和实测未批准/完成。

### page-020：全局数据生成地图

- §00–01：题源→准入→可执行环境→教师准备→CPA DSH rollout→fresh admission→canonical→paired control/training→sealed eval；source/task/fixture/run/receipt/canonical/checkpoint身份链、预算链、污染隔离链清楚。
- §04–05：first-party fresh replay、外部可执行train任务、外部bootstrap轨迹、sealed benchmark分用途，不把外部trajectory当first-party evidence。
- §07：sequence SFT、条件Preference/RFT、Qwen top-k logit KD分支；GPT trace不等于Qwen logit KD。仅接受同tokenizer/inputIDs/mask/K=64 PoC是该历史recipe的限制，不是所有KD的普遍定律。
- **日期优先**：9/2 `0/20`已被9/4–9/5 `5/20`文档更新；但后者也还需运行receipt核对。
- 该HTML在用户家目录 `.gstack/projects/.../designs/.../finalized.html`，不能作为团队长期唯一真源；在当前repo记录摘要和hash引用即可，不复制其执行状态作为实时数据库。

### page-022：结果导向计划

- “Target outcomes”：O1 composition发现、O2工具使用、O3长程状态、O4恢复、O5权限停止、O6证据、O7委派、O8维护seam、O9受控Harness演化。
- “Architecture reference”：A1–A10映射profile/composition、capability、lifecycle、loop、Session、execution、orchestration、interaction、control、evolution。要求 documented/source-verified/profile-active/runtime-verified/trainable/planned分级，package存在不等于active。
- “Backward planning”R01–R12：先评测和baseline gap，再造cell和teacher，先最便宜充分信号；没有可重复gap不扩大数据采集。
- “Execution roadmap”：G0报告完成；G1机器catalog计划；G2批量内核已设计待实现；G3 5/20；G4 GPU未启；G7 Online RL独立轨；G8 Harness最终阶段。
- “Training signals”：不能把GPT API文本轨迹改名teacher logits或on-policy rollout。On-policy distillation学生状态/教师分布训练合同尚未提供，不能声称旧资料已有OPD接入。

### page-033：SFT可执行生成计划（最有行动价值）

- “Counting model”：task template/raw attempt/accepted trajectory/SFT message record/train corpus group/evaluation episode六种数量分账。5条accepted不等于5行训练数据，更不等于训练过模型。
- “SFT sample contract”：canonical可能offline_sft=true且online_rl_trainable=false；目前dual release整体analysis_only不能阻塞合格离线SFT，也不能反过来赋予RL资格。train-only corpus必须canonical-first。
- “Operator discovery”：当前8任务多为精确指定工具顺序的短任务；fallback bash不等于provider swap，formatter复用不等于Cordis composition，durable Session采集不等于模型resume。应让Harbor新任务真正测出相关行为。
- “Implementation audit”：单条生产已有；缺矩阵catalog、3场景adapter、campaign scheduler、train-only corpus、paired Qwen runner、GPU SFT和scale controller。其“已实现”仍是旧snapshot文档审计，需当前代码复核。
- “Maintainer track”：10个shadow task families可用作未来任务库候选；seam roles、disposer cleanup、waterfall next、logged model input、event vocabulary、permission scope、canary rollback等。**均为候选，未注册任务；不应今天一起实现。**
- “Promotion gates”：数据通过→checkpoint可重载→行为提升→unseen family/topology→信号升级→Harness超过静态baseline，分别验收；实验B0、GenericAgentSFT、DSHSFT、Preference/RFT、OnlineRL分贡献。

## 建议当前Uni-Agent主线采纳的5项改动（设计层，非已实现）

1. **给当前单任务证据加来源/用途合同**：Harbor task digest、环境镜像digest、DSH composition/runtime revision、verifier版本、model revision、budget、task family与split。DSH继续提供事实，Uni-Agent集中编排；不要复制DSH生产器再造第二套canonical。
2. **把资格拆成三条入口**：offline_sft、online_rl、teacher_distillation各自列阻塞条件；Harbor reward通过不自动使任一轨迹可训练。OPD另需student-generated状态、teacher监督形式、分布/tokenizer对齐或sequence纠错语义、教师版本和成本；现有资料没有提供完整OPD合同。
3. **SFT入口采用canonical-first train-only assembler**：先trajectory/world family分组与split隔离，再原生渲染；目标4B/9B重新冻结tokenizer/template/loss/tool序列化。当前先设计并复核源实现；不要为拿到第一条Harbor CPU smoke先实现完整双后端。
4. **训练任务按真实缺口选**：首批terminal/repo recovery、budget stop、state continuity；Operator先行，Maintainer/RSI延后。每个标签绑定真实工具状态和verifier；不能用短精确脚本任务证明long-loop或DSH全架构。
5. **统一证据索引，保留历史owner**：链接m3数据producer源码/固定commit和release manifest；当前Uni-Agent保存总进度、当前模型/任务范围、迁移决定。把9/1 80+80、9/2 0/20、9/5 5/20、当前Harbor0次分清，不能汇成一个总完成率。

## 推荐对当前最短路径的影响

继续H0 Docker单任务正/反验收 → DSH/Uni-Agent生成真实轨迹并绑定Harbor评分 → 先取得一个可核验训练输入 → 小步更新与独立加载 → task-family-disjoint对照。

离线SFT可以平行复用既有DSH accepted canonical，前提是读取固定release且通过新的split/template入口；无需等待所有Online RL字段齐全。OPD与Modal不是H0先决条件，8/20或20/20老配额也不应成为当前terminal目标的形式门槛。

## 需要主代理明确报告的边界

- 本轮只读HTML，未核验旧代码HEAD/CI、私有canonical、teacher账单、GPU checkpoint；5/20只能称文档记载。
- 27B模型名、ms-swift4.5.2、外部HF资料均为历史配置/快照；不能未经官方与本地loader复核用于4B/9B。
- 继承来源合同与实证方法，不继承所有旧配额、路线顺序、approval条件及部署选择。
- 文档称“较新数据生产已运行”与“当前Harbor/Uni-Agent RL尚未运行”同时成立，无矛盾，区别在worktree、模型角色、训练方法和证据层级。
