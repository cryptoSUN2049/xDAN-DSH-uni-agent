# APUS 20K SFT 数据发布与训练执行设计

2026-09-24。用户授权目标：完成全部已选数据处理、发布完整清洗版及20K版到HF，并使用20K启动训练。此文为实施审阅版；数据未ready，训练未启动。

## 目标与边界

- 固定每个上游revision，保留完整原始来源索引；完整版本指所有通过规则的合格记录，不把拒绝/未知记录混为ready。
- 四个新增用户指定库必须分别审计；CodeFlame独立排除Gemini3.1及来源不明/冲突记录，追溯镜像回流。
- 20K按独立task/session组计数；累积前缀行和训练样本另计，禁止重复复制凑20K。
- 初始领域目标：代码/Agent 8000，办公3200，数据2800，翻译2400，写作2000，通用1600。此为旧比例放大后的审计目标，不是已有库存承诺。SuperiorThoughts推理池单独统计，审计后提出具体再分配；不得自动伪造缺失领域或教师。
- 通用保留仅Fable/GPT5.6；其他领域按既有清单允许来源。缺口报告后再补齐或审阅配比调整。
- 继承XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B，revision2367e865d009c13ac81713a2878291d33ab28177；保持原生模板，APUS格式迁移不混入本次实验。

## 架构

```mermaid
flowchart LR
 A[固定版本原始文件] --> B[逐来源解析及教师证据]
 B --> C[Gemini排除/未知隔离/工具结构/许可]
 C --> D[跨源任务簇去重与评测隔离]
 D --> E[完整清洗版+拒绝报告]
 E --> F[分层20K+独立dev]
 F --> G[MiMo模板与监督mask/token验收]
 G --> H[私有HF上传与哈希回读]
 H --> I[两卡LoRA小步验收]
 I --> J[正式1epoch SFT及固定验证]
```

## 拟改文件及合同

- `examples/performance_9b/data_release.py`：source adapters、审计、过滤、去重、分层抽样、manifest与README。
- `examples/performance_9b/sft_dataset.py`：复用VERL custom_cls，支持whole-trajectory/target-message两种监督，拒绝无目标和静默截断。
- `examples/performance_9b/train_sft20k.sh`：显式环境、固定模型/数据、两卡预检和有界训练。
- `tests/uni_agent/examples/test_performance_9b_data_release.py`及mask测试：来源混淆、Gemini别名/未知、前缀组、跨split去重、采样不足、工具闭环、mask精确性。
- `docs/performance-9b/最终训练数据清单.md`及报告：以真实计数更新，保存源revision、license、SHA256、教师和领域分布。
- 大文件放数据缓存/远端workspace，不提交Git。

记录合同：record_id/task_group/source_repo/source_revision/source_item_id/source_license/teacher_claimed/teacher_evidence/status/domain/messages/tools/supervision/quality_flags/content_hash。unknown、excluded、ready分别输出；模型生成工具观察不当真实执行证明。

## HF交付

沿用gump2049私有dataset惯例，建议`gump2049/APUS-Agent-SFT-Full-v1`与`gump2049/APUS-Agent-SFT-20K-v1`。README保留全部上游路径、许可与处理限制；manifest保存hash/版本/配方/seed。上传后回读commit和大小/hash，训练只读固定revision。完整清洗版不发布不可再分发或身份不明样本为ready。

## 三教师独立子版本（用户补充）

新增`gump2049/APUS-Agent-SFT-Qwen38-Fable-GPT56-v1`私有dataset。它从完整合格池按教师证据投影，允许Qwen3.8系列、Fable系列、GPT-5.6系列；精确model ID和证据原样保留。Qwen3.7/GPT5.5/Gemini/GLM/Kimi/Grok不纳入；Claude/Mythos不能未经证据自动映射成Fable。缺失/冲突教师隔离，不靠正文提到模型名放行。继承完整版本的任务组、去重、split与全部质量门，不重新随机切分导致泄漏。

该版本独立发布README、manifest、教师/领域/监督token统计与排除报告；不保证三家等量，先报告合格供给。20K从此子版本还是完整池抽样正在向用户确认；两种来源参数都需可选。通用保留继续只用Fable/GPT5.6，Qwen推理属扩展能力。允许教师仅是必要条件，不替代许可、正确性、工具结构验收。

## 训练预配置与验收

远端`/workspace/verl-uni-agent-harbor-opd-rl`，使用`envs/ua-verl-py312-vllm023-ws1`；VIRTUAL_ENV/UV_PROJECT_ENVIRONMENT/PYTHONNOUSERSITE/PYTHONPATH显式配置。默认Python缺transformers，不可使用。

拟LoRA r32/alpha64、BF16、microbatch1、global batch16、lr2e-5、warmup3%、1epoch、gradient checkpointing。序列长度和最大监督token在全量token分布及显存试跑后冻结，初期remove_padding=false。不得沿用默认lr1e-3/4epochs。

先1–3步smoke：loss有限、adapter确有变化、非空正确mask、重载可推理、保存恢复一致；再启动正式20K。正式训练固定dev监测loss、分域质量、工具协议、输出长度/超时，保存可回滚checkpoint。数据或mask验收失败不得自动进入正式训练。W&B有有效登录则在线，否则明确offline并保留本地结构化日志，不能宣称已实现自动质量止损。

## 验证计划与当前证据

- 数据计数守恒、任务组唯一、训练/验证无同源重叠；缺额直接报错。
- 每来源结构与教师统计、代码/计算参考检查、非可执行领域独立rubric；区分结构合格与能力正确。
- 所有已发现Gemini3.1贡献及未知教师记录不得进CodeFlame ready；不能只看被重写的model标签。
- 真实tokenizer渲染，检查目标token边界与工具返回mask=0，长序列不静默截断。
- 单测与小步GPU验收通过后才正式训练；Ruff两项通过后push。

09-24只读审计：两卡空闲，MiMo权重未安装；数据缓存没有新四库完整文件；办公/翻译/写作未证明足量。旧MoreThought切片tool_calls缺失、Premium教师标签冲突需在最新版本复验。现有无关未提交改动保留。

## 语言约束更新：不纳入俄语

用户明确不需要俄语。此约束应用于完整清洗版、三教师子版及20K训练版，保留原始资产及其原始语言分布不变。HelioAI的5,469条仍是RU+EN原库数量；英文可用量须过滤后单独统计，不能把5,469全部计入英文候选。

逐样本检查问题、reasoning、答案和对话正文；俄语为主或包含实质性俄语监督内容的样本排除。语言不明/混合复杂样本先隔离。不能仅按出现西里尔字母删除，也不能将俄语翻译后冒充原教师英文示范。语言识别不代表教师、许可或质量验收通过。当前仅规则更新，尚未执行正文过滤。

## 实施批准

用户已明确“开始处理数据”“好的 开展起来”，本设计的实施门已通过。先统一母本与过滤，SFT优先验证ms-swift，VERL保留导出及后续OPD/RL用途。现有数据身份/污染/质量门不因批准而跳过；20K最终配方按实际供给冻结。

## Runpod 后台处理合同（用户要求写好后台脚本）

入口 `examples/performance_9b/background.py`：`start --config PATH --run-dir NEW_DIR` 脱离 SSH；`status --run-dir DIR` 查询。每次创建新目录，冻结配置、源 SHA256 和处理器代码；保留日志、PID、原子 status.json 与定时心跳。预检每个源存在且固定 SHA256，空间低于 max(10GiB, 原始文件大小×4) 拒绝启动处理。完整执行 build 后独立核对产物哈希及计数守恒，生成 report.md。失败保留产物及 traceback，不自动重试、不覆盖原版、不自动上传或训练。

状态：STARTING → PREFLIGHT → PROCESSING → VERIFYING → SUCCEEDED；任一步异常为 FAILED。SUCCEEDED 仅表示结构筛选产物已验收，training_ready 始终 false。断电/SIGKILL 时心跳过期且进程消失，status 显示 INTERRUPTED，禁止当成功。文件：background.py、对应单测、运行报告和交接。验证覆盖真实脱离进程成功、源哈希失败、目录不可覆盖、产物校验失败。

## Fable 来源恢复（v2筛选后）

v2所有Fable候选隔离，先恢复原始证据再更改准入规则。新增脚本 collect_recovery.py：读取固定revision与文件SHA清单，下载到Runpod独立目录；PremiumV1仅openai_chat的三split parquet及README，split分别保留，Armand/Teich保留原始JSONL。核验大小和上游LFS SHA，逐文件报告schema、model声明、事件/轨迹行数，不能把事件数当独立任务。输出collection-manifest.json和audit.json；断点重启复用HF已下载内容但不修改原版。总下载上限2GiB，未知大小或路径越界拒绝；来源审计不得自动修改训练池。测试文件大小/哈希失败及split原样保留。当前只做原版归档和来源恢复；PremiumV2 blanket quarantine仍保留，直到建立可验证逐行匹配。
