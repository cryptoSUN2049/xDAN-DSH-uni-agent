## Fable恢复后台已完成

- collection-v1 succeeded：70文件501430864字节，原版留Runpod；小报告`docs/performance-9b/fable-recovery-v1/`。
- PremiumV1 6365行含591Fable/5705unknown/69其他Opus；train仅526Fable声明，val33/test32不可用于训练。V2全标Fable不能继承。
- V2 base_v1 5381行source_row_hash与当前固定V1无匹配，未恢复逐行教师或split，保持隔离；下一步查哈希算法/历史revision/完整内容匹配。
- Armand18370事件行（63文件）、7431处Fable模型声明；Teich244行无model字段。数量不是独立任务或准入数量。

## 数据字段契约已保存（权威入口）

- 用户要求确定并保存columns设计；文档`docs/performance-9b/统一训练数据字段契约-v1.md`及`.columns.json`已落盘。
- apus-sft-v1固定27列，messages/tool_calls/supervision固定子结构；tools_json和function.arguments物理存为严格JSON字符串，校验时解析对象；thinking独立字段。
- 原版不改；中立母本保留完整审计；训练视图由固定任务manifest导出。数据schema与apus-chat-v1协议分离，不在母本自动注入品牌system。
- 当前仅字段设计冻结；screened-v2未完成schema迁移、HF回读、mask与tokenizer验收，不得称正式母本或training_ready。

## 当前后台任务：Fable证据恢复

- Runpod `/workspace/apus-data-cleaning/recovery/collection-v1/manifest.json` 查看status/current_file；日志`collection-v1.log`，脚本`collect-recovery.py`。禁止重复并发启动。
- 固定inventory下PremiumV1三split单一Parquet、Armand/Teich原始JSONL，只归档与schema/model声明审计，无训练准入。
- 下载上限2GiB，本轮约500MB。17项回归通过；不同inventory复用目录在任何写入前拒绝，原始文件SHA核验。
- 下一步先取终态manifest与audits小报告，Mac不取原版大数据。HF额度仍未解决，不能称已发布。

## 最新：身份测试结束，回归数据主线

- 用户明确不再扩展身份测试，回到数据处理。MiMo9B已下载Runpod并完成88身份请求/2工具请求；原始结果在docs/performance-9b/mimo-identity-test。未在输入暗示MiMo的54请求没有MiMo/小米输出，但不能证明训练数据无该名称或衍生来源不可识别。
- 测试vLLM服务1059369已发SIGTERM释放GPU；权重保留。启动需VLLM_USE_FLASHINFER_SAMPLER=0避免CUDA12.8/SM12.x采样JIT失败。不要因此改共享训练环境。
- 数据v2已SUCCEEDED；293074行输入，62030结构候选，26757关联组件。候选无Fable，不能启动原定20K；各来源原因与报告见screened-v2-evidence。
- 下步恢复Premium来源：base_v1 5381/crownelius59先追原始证据；manusagents79560教师混合继续隔离。Krazy1000仅54提示、调用字段缺失，不是模板问题，不能猜测修复。
- 开始在Runpod恢复源inventory（premiumV1、已有清单Armand/Teich），不在Mac下载大数据。

## 最新：Runpod 后台处理脚本

- 入口 `examples/performance_9b/background.py`，操作文档 `docs/performance-9b/后台数据处理操作.md`。
- 当前运行 `/workspace/apus-data-cleaning/reports/screened-v2-background`；用 background status 查询，勿启动重复运行。冻结代码、配置、SHA；10秒心跳、失败留证、不自动训练/上传。
- v2 已修复 val 划分漏检、同层teacher/model冲突遮蔽、孤立tool结果、同源任务及跨源相同prompt联结。v1只保留诊断，不用于最终统计。
- 84项回归通过，全仓ruff双门通过。当前并不代表20K或训练ready。

## 最新：Mac 清理与 Runpod 原始数据副本

- 设计已获用户“开始处理数据/好的开展起来”批准；当前先归档，训练适配后做。不要沿用下面历史“未批准”状态。
- 本轮清理失败处理产物约8.04GB，另删除3个无打开文件的可重建HF Arrow缓存约3.69GB；uv缓存39GiB因占用锁超时未清理，未强制删除。
- 原版8库17文件共3,992,734,383字节已复制至Runpod `/workspace/apus-data-cleaning/apus-source-archive-v1`，逐文件大小/SHA256全部核验一致。本机原版仍保留。
- HF私有归档上传失败：403 Private repository storage limit reached。不能称已上传或擅自转公开；待解决额度后从远端续传。
- 证据：`docs/performance-9b/mac-cleanup-and-remote-archive.json`、`source-archive-upload-manifest.json`。
- 处理器76项测试通过，仍未提交；第一次本机全量处理磁盘满，失败输出已清理，无有效20K版本/训练。后续在Runpod CPU上继续处理，勿回Mac生成大中间文件。

## 双框架数据适配设计

已核ms-swift官方messages/Agent roles/loss字段和本地VERL源码，新增docs/performance-9b/ms-swift-verl数据适配方案.md。统一母本后两导出，不重复清洗；当前VERL需custom_cls支持target_message_index。尚未实现。用户已明确确认“从CodeFlame数据中去掉Gemini3.1”，不存在取消限制；未知/冲突来源隔离。

## 最新语言约束：排除俄语

所有派生训练版本排除俄语；HelioAI原版5,469 RU+EN仍登记，英文子集数量未知。检查prompt/reasoning/answer，不改写俄语冒充原始英文。文档/JSON规则已更新，尚未执行语言过滤。

## 来源补漏完成：15个原始库

用户重列11个链接，去重7库，旧台账覆盖5库；新增HelioAI/Claude-Fable-5-5500x（卡片5469、license unknown）和KrazyKitty/Fable-5.1-Max-Reasoning-Filtered-1000x（卡片1000、与MoreThought重叠待核）。原始台账MD/JSON及分布/索引已更新至15唯一库；新增两库仅README和元数据，未下载正文，未改20K配额。

## 最新交付顺序：原始台账先于抽样

用户要求先完整登记所有原版路径、各库分布/数量，再规划抽取，最后20K训练。已建docs/performance-9b/原始数据资产清单.md及JSON，共13唯一仓库（近期指定5+原方案8），原版声明与实测分开。project-index已按此排序。五个近期库主训练文件下载完成，其他8库本轮仅刷新固定README/API，不误称全量落盘。QwenAgent下载24910已成功结束。四库审计JSON与能力缺口表齐备；尚未实现正式清洗/上传/训练。

## 20K目标与真实供给对比已完成

权威规划docs/performance-9b/20k数据规划与能力缺口.md：建议7K代码/3K推理数学/3K办公/2.5K数据/1.5K翻译/1.5K写作/1.5K通用。是建议目标非ready数量。新增QwenAgent固定rev fbe918e...；下载session24910需核。四库实际审计JSON已完成：Fable5.1工具名/参数损坏，Superior污染1587test，CodeFlame90K未知身份，Premium混合来源却统一Fable标签。不能按原始卡片总量启动训练。设计批准和20K选全池/三教师池两问题仍待答复。

## 当前主线：完整数据、三教师子版与20K SFT

用户要求完整清洗/20K抽样/上传HF并训练；追加仅Qwen3.8+Fable+GPT5.6子版。设计在docs/performance-9b/sft20k-execution-design.md，AGENTS Human Gate明确批准尚待答复；20K从全池或子版抽样也已提问。尚未实现处理器、上传或训练。HF账号已核gump2049，沿用私有。当前两卡空闲，MiMo权重缺；VERL默认全assistant监督，必须适配target_message_index。

下载暂存/private/tmp/apus-sft20k/raw/。Superior固定版已完整扫描9640行（math6212/reasoning2151/code1277），证据sft20k-source-audit.json，只做结构检查非ready。Fable51/Premium/CodeFlame完整下载已完成（Premium为85K train parquet），均在同一raw目录。分布与准入证据正汇总至数据集能力分布清单.md及各sft20k-*-audit.json。不要覆盖现有未提交分析脚本变更。

## 数据清单v3.3：CodeFlame排除Gemini 3.1

用户要求独立处理CodeFlame，排除Gemini 3.1系列；未知/冲突来源隔离，跨前缀与轨迹组防回流。最终清单M1已写验收规则，尚未执行全量过滤。后续必须报告过滤后任务/教师/token分布，不能沿用原库190K当可用量。

## 数据清单v3.2补充

新增用户指定CodeFlame/SuperFusion聚合入口（卡片称190K/GPT5.6约50K），逐教师/原始来源筛选，未全量审计。详见最终清单M1；1K配额未暗增，通用保留仍限定Fable/GPT5.6。

## 数据清单v3.1补充

用户指定Fable-5.1-Filtered-5000x、SuperiorThoughts-1及Premium V2，已补入`docs/performance-9b/最终训练数据清单.md`。前两份明确要用；Fable优先既有160池，SuperiorThoughts扩展配额待审计冻结；Premium混合教师逐条筛选。仅卡片/元数据核验，未全量下载或训练。

# 全版本 checkpoint 评测交接

## 2026-09-24 当前最终清单v3

- 唯一配方权威docs/performance-9b/最终训练数据清单.md，原v1/v2降为历史。
- 用户要求通用保留也只用Fable/GPT5.6：80条改Fable20/GPT60；Cascade/Math/Science当前配额0。
- train1000领域不变：400/160/140/120/100/80。现成520+新生480；新生含保留80，实际来源不足保留缺口，未ready。
- 文档、HTML和索引已统一引用最终清单；当前没有新训练或批量生成。


## 2026-09-24 当前配方v2：强教师核心

- 用户明确Fable+GPT5.6为核心。权威入口docs/performance-9b/agent-sft-data-plan-v2.md。1000目标=代码/终端强教师400（GPT240/Fable160）+办公160+数据140+翻译120+写作100+保留80。
- 600现成示范+400新生产；core400仍待完整文件准入，不保证Fable160已存在。旧v1.1降为历史，不能混用440/560数字。
- 任务数/前缀行/loss token区分；whole-trajectory与next-action监督独立；建议首轮分层混训，阶段训练另设对照。
- 明确代价：代码从20%增至40%，须监测目标工作能力是否受挤压。dev100/sealed200相应分配，总规划仍1400独立任务。


## 2026-09-24 强教师配方修订

- 用户指出Fable/GPT基础示范不足；strong-teacher-sft-review.md核对画像冲突、官方卡、切片及GPT6搜索。
- 1K领域总配额不变；代码200改GPT5.6=100、Fable原始/独立池=60、OpenSWE=20、新生=20。现成440+新生560；均目标非ready。
- GPT5.6累积前缀仅监督最后assistant；Fable镜像model_attested必须实筛，当前切片不能证明合格子池存在。原始Fable无明文CoT不等于不可做动作SFT。
- GPT6搜索返回4个候选，暂无可直接纳入的通用Agent母本；优先规划真实自生产，不把评测答案当训练。


## 2026-09-24 文档目录统一与数据配方

- 用户要求文档统一到docs/performance-9b/；整个旧文档树已迁移，内部相对结构保留。worktree与tasks目录名不变。历史JSON原始运行路径保留为证据，不当新执行入口。
- 当前数据权威agent-sft-data-plan-v1.md：1000独立训练目标，代码200/办公200/数据200/翻译150/写作150/保留100。420现成SFT+80开源环境新生+500自有新生=1000；未构建ready。
- 校准100（含20）+train1000+dev100+sealed200=1400独立任务规划。Curator编排，Uni-Agent真实执行，verifier+独立rubric验收。
- 模板专项独立；未启动新训练或付费生成。未提交外来物料随目录保留，勿混入本次提交。


## 2026-09-24 主线收敛：数据生产与20种子

- 用户确认tool-call自有格式后续按独立小实验执行，不阻塞数据主线。
- agent-sft-seed20-plan.md列办公/数据处理/翻译/写作/代码各4题，输入→工件→grader负例；三档数据准入、20→100→1K门禁。当前规格不是fixture或真实轨迹。
- 先O01/D01/T01/W01/C01五锚点建设；教师API与硬费用上限待核，未发起付费执行。
- apus-chat-v1-tool-call.md已形成完整专项；本轮文档整合待校验/提交。


## 2026-09-24 APUS Tool Call专项

- 新权威文档docs/performance-9b/apus-chat-v1-tool-call.md，覆盖数据/API/token三层、MiMo/Qwen差异、ID/参数/流式、mask、迁移实验及验收。已接项目索引与MiMo HTML。
- 当前仅文档；尚未实现模板/parser或启动训练。v1建议先E1外部适配，保持MiMo模型可见序列；多调用/并行/多模态不自动放行。
- 下一步冻结支持范围和golden样例，再真实对照；上游模型来源保留。


## 2026-09-24 Agent SFT 数据与协议方案更新

- MiMo HTML扩至18章，增加用户数据画像准入、GPT6-sol候选教师真实执行、Curator工具选型、Qwen/Apus协议迁移和多harness受控实验。
- 新agent-sft-data-production-design.md保存架构/文件范围/接口/测试计划；portrait-audit.json为画像与目录抽查证据。
- 画像内嵌81本地条目/354HF候选，扫描2026-06-20，非当前ready库存。部分目录只有README，小样不等于全量。
- 后续用户已确认继承MiMo权重，名称apus-chat-v1；HTML #apus-chat-v1为最新草案，优先保留原生序列化+API适配。当前会话gpt6-sol标签不等于已配置批量API，provider/计费与额度待实查。
- Agentic-v2部分模拟环境，不计真实工具成功；画像多处静态SFT标on-policy OPD不予继承。保留原始报告不改写。
- 未下载新权重、未启动付费数据生成或训练；下一步是按设计合同做接口/数据准入小试点。


## 2026-09-24 MiMo Agent SFT 9B 专题

- 新报告 docs/performance-9b/mimo-agent-sft-9b-report.html，14章：SFT起点/数据/mask原理/轨迹/数据工厂/分域GRPO/多harness/复现边界/两卡路线。已接产线HTML与索引。
- 固定HF revision 2367e865d009c13ac81713a2878291d33ab28177；模型卡、元数据、PDF33–36页摘录及hash位于mimo-agent-sft-evidence/。
- 结论：监督SFT蒸馏不是OPD；公开权重不是表6各域RL模型。完整SFT超参与语料未核验，不能声称精确复现。
- 远端检查时两卡0MiB/0%，MiMo权重未下载；旧evaluate.py强制thinking-off、默认原版tokenizer且无工具，不能直接作为新Agent选型评测。下一步须冻结原生模板/工具/预算合同再运行对照。


## 2026-09-24 日常工作Agent目标与双线推进

- 用户收敛目标：接近Opus4.6日常工作/Agent能力，OPD有效性验证为主线，同时规划mid-training数据。
- 新设计与实测审计：docs/performance-9b/daily-agent-capability-plan.md；新HTML顶部已链接。
- 旧30题仅14条可评分、无工具；teacher只多过一条关键词，代码min_Jumps样本存在题面示例冲突，不可据语法通过宣称教师功能优势。
- Qwen卡片部分Opus比较非同口径；新100个工作任务规格为待构建开发诊断，非已完成评测。1K文本配额不冒充Agent课程。
- midtraining历史123GB画像不是当前可读库存：主要是小样；先核验来源/完整性/许可/token，再依能力缺口配方。
- 本次只读GPU时两卡0MiB/0%，未启动新训练/付费Opus/沙箱。下一步数据/评分与画像、控制门；不要因卡空闲跳过准入。


## 2026-09-24 独立产线HTML入口

- 用户批准独立于MiMo研究报告建立我们自己的科学训练产线。新唯一入口：docs/performance-9b/training-production.html。
- 双维导航：产线架构 / 阶段目标；研究来源辅助入口。Curator、Teich、Verifier、观测控制与OPD/MOPD/规模化RL专项均写明职责、状态和验收。
- 原MiMo HTML未修改，architecture.html保留历史并链接新入口。详细总纲与1K合同仍为权威设计，HTML不代替原始证据。
- 本轮仅文档/导航，无训练或infra部署；1000条尚未ready、云观测与质量止损仍待验收。
- 文件：training-production.html（16节）、production-portal-design.md；索引/总纲/历史架构/记忆同步。后续继续数据与grader、事件与控制建设。


## 2026-09-24 当前主任务：科学训练产线与1000条pilot

- 用户已确认：建立完整专业可观测、可分析、可诊断修复的大模型训练产线，1000条多领域单教师OPD为首个受控实验；长期MOPD目标保留。
- 先读 docs/performance-9b/project-index.md → training-production-charter.md → training-pilot-1k-plan.md；HTML唯一导航为training-production.html。
- 当前仅设计/盘点/项目记忆索引已更新；1000条未构建、未启动新训练。原始源足够多，但代码120条、科学旧40审计仅4保留、聊天头部240行均不能直接扩成高质量1000。
- 现有原生文本OPD链路已验收；不能说Uni-Agent/Harbor工具路线、W&B云端与真实verl-insight后端、质量止损已全部接通。按P0合同/评分→观测/控制真实验收→有界pilot推进。
- 最新新文档/已有修改位于既有performance-9b worktree，保留之前未提交变更；勿stash/reset或把旧纯RL提案作为本轮启动依据。

## 2026-09-24 夜间单教师 OPD（已完成验收证据）

- **完整测试执行完成，非全门禁通过**：统一入口 `overnight/index.html`，结论 `tokenizer-opd-compatibility/full-verdict.md`、机器门禁 `full-acceptance.json`。当前thinking-off文本OPD链路通过；thinking1024单例未闭合，原mode driver exit1保留，禁止称全部适配。
- 真实训练runs/opd-live-acceptance-20260924 exit0；2microbatch/8条/4455token，独立loss和grad误差0、mask外0、teacher ID错位0、coverage pass。248文本LoRA全部非零B，110视觉零B；导出/独立30题重载SHA一致，infra0。评分math4/5、IF5/8、knowledge1/1，code/chat未计正确率。
- 17案例9模式+8现场，6091response token；HF/vLLM mean0.00825642、P950.06524849、parser全通过。实际live teacher vsHF8/8通过，weightedmean0.00907492。工具原生mask5控制通过但生成传输mock。
- thinking2048独立诊断exit0，1751token闭合、正确391，原1024前缀完全重现；不替换原fail，新增尾部未评分。HF默认EOS248044/endoftext，而live VERL正常EOS248046/im_end；forced评分可比，不宣称生成停止等价。
- 本轮无需继续GPU作业；未启动扩量训练。后续是统一停止配置、合格数据扩量/固定验证/封存测试/代码聊天评分；不将兼容通过当高性能证明。W&B仍offline。




- 深度兼容验收完成：driver1037003 exit0，GPU释放。2736响应token五域文本重放+EOS，HF/vLLM mean0.008197/P950.064773，原生parser IDs全对齐。真实概率loss误差2.78e-17、grad4.34e-19；四组边界控制通过。证据deep-evidence/，结论deep-verdict.md，已整合overnight报告。只支持当前文本单轮关闭thinking；历史原始张量未保存，不能声称精确重建。新扩量训练尚未启动，用户允许考虑扩量，优先补合格数据/评分和固定验证。

- 后续新请求：用户要求进一步确认适配、定位VERL源码，并允许考虑数据不足时扩大训练。当前先做深度验收，不重复原122条冒充扩量。远端runs/opd-deep-audit-20260924，driver1037003；CPU实际loss独立损失/梯度/边界控制通过，HF五域文本重放+EOS已完成，vLLM对照运行中。原训练没存逐token张量，重放不是历史精确重建。文档tokenizer-opd-compatibility/deep-source-audit.md、deep-design.md。待结果完成后再定扩量与验证集。

- **最终：19:06:59 UTC全部队列完成，driver979002已退出。** 正式16步、四ckpt导出、五adapter独立重载均成功；7版本×30题=210输出，infra0。最终step16 math5/5（base4/5），IF5/8、knowledge1/1不变；仅幂塔题4037token内输出boxed0352改善，不能外推全面收益。
- **最终入口**：docs/performance-9b/overnight/index.html。final-analysis.json置顶结论；final-evaluation-audit.json逐条身份/重评分；final-weight-audit.json实际远端权重SHA与导出及eval一致；training-completion-audit.json全16步有限loss/grad；sampling-audit.json128轨迹覆盖121样本。最终summarize已显式重跑，medians与reload关联已更新。
- **页面验收**：桌面1280×720截图检查、手机390×844无横向溢出，7模型对照表，report-qa.json锁定HTML SHA。远端control-attempt2保留全部日志、权重和W&B offline run。无新增付费沙箱调用。
- **后续非本轮完成条件**：科学扩量、代码隔离执行评分、聊天质量评分、封存测试、近重复污染审计、W&B同步、性能触发止损、thinking/tool专项。不要把本轮有限验收改称全面高性能训练完成。此前时间线为历史快照。

- 19:00:08 UTC：step12 exit0、30/30、reload=true，math4/5、IF5/8、knowledge1/1，与base14条已评分逐题相同，code/math各1截断。最后step16 PID1035826运行。step12结果已同步本地。report.py新增可选final-analysis.json（paragraphs/columns/rows）置顶结论，数据尚未填写；最终应完成该文件、重跑summarize/report、全模型一致性审核与浏览器QA。

- 18:52:58 UTC：step8完成30/30、infra0、reload=true；math4/5、IF5/8、knowledge1/1，14条已评分与base逐题相同，step4关键词退步已恢复。step12 PID1035056运行，最后step16待跑。step8同步本地；最终必须运行更新版summarize.py，当前driver缓存旧版。

- 18:45:58 UTC：step4独立评测30/30、infra0、reload=true，math4/5、IF4/8、knowledge1/1；相对base IF退步1题，其他已评分逐题相同。step8 PID1034287运行，之后12/16。step4结果已同步本地。analysis-notes新增base/teacher逐题解释：IF唯一改善为双关键词要求；共同数学失败因4096截断，无最终boxed，勿事后改分。

- 18:39:10 UTC：teacher27B同预算30/30完成、infra0，math4/5、IF6/8、knowledge1/1；相对base仅IF改善1题，其余已评分逐题相同。step4 eval PID1033521启动，后续8/12/16。teacher结果已同步本地，全部正式reload与最终分析仍待完成。

- 18:30:40 UTC：base9B同预算30/30完成，infra0；math4/5、IF5/8、knowledge1/1，code/chat无正确率。smoke与base逐题14条已评分结果全部相同（improved0/regressed0）。teacher27B评测PID1032692活跃，四正式ckpt仍排队。base结果已同步本地models/base-9b；勿与旧diagnostics-v1比较。

- 18:26 UTC：export-full exit0，step4/8/12/16均exported，各权重SHA不同；原版9B独立eval PID1031927运行，后续teacher与四ckpt。完整sampling-audit已刷新16步128轨迹、121唯一样本、unmatched0，分域instruction34/chat33/code32/math26/knowledge3。report新增training-completion-audit展示，已部署；Ruff定向双门通过。

- 18:25:14 UTC：正式16/16步完成，train997761 exit0，最终验证结束；export-full PID1031707已启动。四个checkpoint step4/8/12/16均存在；training-completion-audit.json核对全16步loss/grad有限。driver979002将继续base9B/teacher27B/四ckpt评测。sampling-audit目前仅前15步120样本，最终须刷新加入第16步。目标尚未完成。

- 18:17 UTC附近：正式训练直接TaskRunner日志已step10，checkpoint tracker=8，driver979002/train997761仍活跃。新增sampling-audit.json：前9步72条rollout通过完整role/content渲染精确唯一匹配，unmatched=0；instruction20/chat18/code16/math16/knowledge2。仅代表生成，不代表对应更新已完成；训练结束须刷新到全部16步。report.py已部署展示此证据，HTML同步本地。环境主进程/TaskRunner/WorkerDict再次实测VIRTUAL_ENV一致，PYTHONNOUSERSITE=1。

- 18:06 UTC：正式step4 checkpoint tracker=4，已提前CPU导出到control-attempt2/adapters/global_step_4/lora_adapter，248模块非零B，SHA e77be511b0ad21dc88425a2ee1992cee3cf45377555a9bd15c57a1e72c09e846。export-step4-early.log exit0。后续driver全量导出可复用该adapter。训练997761仍运行，step4验证收尾，日志指标最后step3（验证后才输出step4指标），勿重启。

- 18:03 UTC：正式full已2/16，PID997761，TaskRunner1002227。step1 loss0.19377/grad0.60547/71.67s，step2 loss0.30731/grad0.76563/56.62s；actor/lr日志是scheduler更新后的下一步LR（5e-7、1e-6），step1实际LR0。下一保存step4。若主日志buffer延迟，读/tmp/ray/session_latest/logs/worker*1002227.out。
- 汇总脚本新增中位数及按hash关联generation_reload_verified；运行中的driver已缓存旧summarize模块，最终必须显式执行新summarize.py再生成report.py，勿忘。报告已加入源码/命令hash、W&B offline、原始checkpoint验收、分析快照。全仓Ruff双门通过；HTML桌面/手机无横向溢出（中间快照QA，最终仍需刷新）。

- 17:39 UTC里程碑：smoke训练→导出→独立重载30/30全部通过。248模块非零B，adapter SHA6735b4e27cc8a2d622692ee5944a4d989cd76f1b530b9b860447a4cef2083ff8与eval一致。smoke4096预算math4/5、IF5/8、knowledge1/1、code/chat未评分；尚无同预算base对照不能宣称提升。
- 正式16step train-full PID997761已于17:39:29启动，driver979002继续。目录runs/overnight-opd-20260924-attempt2，仍使用v2数据122/30。后续每4step保存再全部导出/评测。

- 17:32 UTC关键进展：attempt2 smoke训练exit0，step1保存完成；loss0.1948945、grad_norm0.671875、lr1e-6、step109.48s、response_mean456.75、clip_ratio0.125。原进程979006已退出；driver979002进入export-smoke，PID996760。仍需导出非零B与reload-smoke验收，full尚未启动。

- 17:18 UTC实际进展：attempt2 driver979002/train979006存活；TaskRunner983493环境继承已实测写environment.json。actor WorkerDict985141初始化成功；teacher vLLMHttpServer986661/Engine987113/Worker987452正在GPU1加载27B（6/18 shards，约53GB）。GPU0学生参数offload当前约1.3GB；尚未训练更新。Ray细日志/tmp/ray/session_latest/logs/worker*986661*.err，主日志缓冲不完整。无必要不要重启。

- 17:07 UTC最新：v2数据部署122train/30val完成，attempt2 driver979002已启动，使用新数据目录data-overnight-opd-20260924-v2。旧driver970046和teacher977897均已退出，旧40题两模型均完成。先查attempt2/state.json和train-smoke.log。
- v2严格排除math/science uncertain，science仅3train/1val；不能用于领域效果结论。完整80题审计quality-review-80.json/md保存。正式eval4096，训练1024。

- 17:02 UTC最新：attempt2 waiter977686已核对命令后停止（仍在等待，未训练），原因真实逐题审计发现3项验证数据问题；数据agent正在复审math40+knowledge40。旧driver970046/teacher977897继续评测不动。修订数据版本冻结后重新启动attempt2，勿误认等待器活着。MCQA parser已补<B>/Option Selected，需统一重评分旧诊断。

- 16:59 UTC：原版40题短预算1024评测完成，但数学7/8截断；attempt2正式所有评测统一4096（训练rollout仍1024，需报告限制）。旧结果保留为短预算诊断，不与4096混配。配置检查成功exit0，显式激活uv环境，Ray py_executable绑定同环境。

- 最新：attempt1 smoke因缺flash-attn失败，旧driver970046正在跑base/teacher评测，勿中断。attempt2 waiter977686等待其真实退出后启动；新control路径为旧路径加`-attempt2`。训练改sdpa+remove_padding=False，smoke warmup0确保非零更新，full保持warmup2。
- uv创建的Python3.12.3环境确认：torch2.11.0 / transformers5.8.0 / vllm0.23.0 / ray2.54.1；attempt2显式设置VIRTUAL_ENV、UV_PROJECT_ENVIRONMENT、PYTHONNOUSERSITE和PATH。仍需验证Ray worker实际继承。
- 评测return_dict=False实机list[int]通过；IF/code空响应误判已修复，禁止空答案通过。

- Goal active：用户睡眠期间继续真实训练、评测与HTML报告。今晚单教师27B→9B，五领域，非MOPD。
- 服务器 control：`/workspace/verl-uni-agent-harbor-opd-rl/runs/overnight-opd-20260924-control`；driver PID970046，smoke PID970050，16:48 UTC启动。先查state.json、driver.log、train-smoke.log，不重复启动。
- 数据160 train/40 val，各域32/8；code/chat无可靠正确率，不计综合。
- CPU tokenizer、HF/vLLM评分门通过；105响应token mean_abs_error0.01044，p950.07962，仅短序列关闭thinking试验。
- 修复vLLM sampler兼容：VLLM_USE_FLASHINFER_SAMPLER=0。用户授权的Decision Index PID897129已停止。
- 顺序：smoke1→导出/重载评测→正式16步每4步保存→base/teacher/所有有效checkpoint同预算评测。当前仅smoke启动，未证明更新成功。
- 脚本与HTML：`docs/performance-9b/overnight/`；后续同步远端state、index、models、metrics回本地。
- 自动报告10秒刷新；时限停止已实现，性能触发止损尚未实现；W&B offline。异常需保留日志并修复，不重复空跑。
- 当前分支performance-9b，已有未提交变更，勿覆盖。

## TL;DR
- **2026-09-24 当前目标/决策入口：先读 [MOPD项目记忆](mopd-project-memory.md)**。全面能力多教师在线蒸馏为主线；下方训练/评测状态均按历史时间理解，非实时报告。
- 用户要求每个版本 checkpoint 全量评测，取得整体结果。
- 本轮S2所有保留版本，加原版与S1 step12；GPU0全量队列持续运行。
- 已有完整结果：原版64.10%、OPD12 43.27%、RL20 50.96%、RL40 47.76%、RL60 46.15%；OPD12/RL20已补齐infra缺失。
- 新授权：TB2.1→SWE-bench Verified，固定原版/OPD12/RL60，GPU1。数据审计完成，正在验证沙箱/评分器。全量启动待核实既有Modal900美元上限；当前账单856.04美元。
- 先读 `docs/performance-9b/checkpoint-full-eval-design.md`；旧训练历史在该 docs 目录的 `tasks/handoff.md`。

## 本轮交付物
- `docs/performance-9b/checkpoint-full-eval-design.md`：候选清单、流程图、接口、费用、验证与拟改文件。
- 本文件：当前任务冷启动入口；文件行数可用 `wc -l` 复核。

## 设计约束
- 不把0题/exit0当成功；78题每题4条才是完整结果。
- 不合并bf16 LoRA；保持模型、数据、采样、评分口径可追溯。
- 不杀其他会话进程；训练结束的全局Ray清理完成后才开批量评测。
- 非平凡代码改动遵守用户提供的 AGENTS Human Gate，设计批准后实施。

## 已发现真实行为
- 原版与 OPD12 的相同0.6显存配置曾成功；失败step20初始化前额外占用约14.38GiB，checkpoint尚未加载。
- 静态路由检查未发现错卡，历史没有物理GPU UUID/占用PID证据；不能推断占用者。
- eval_val_only.sh 吞掉底层异常，0题结果仍退出0。
- S2保留 OPD10/11/12，RL20/40/58/59/60；58模型文件偏小，未证明完整。

## 下一里程碑
- [x] 清点保留文件、pinned去重与只读故障分析。
- [x] 设计落盘。
- [ ] 用户批准设计与范围。
- [ ] checkpoint完整性检查、显存/路由诊断与首题真实验证。
- [ ] 修复失败传播；实现可恢复队列与回归测试。
- [ ] 逐版本78×4，配对与行为统计，完整总报告。

## 分支/部署状态
- 分支 verl-uni-agent-harbor-opd-rl，清点前 HEAD fa2653a，工作区当时干净。
- pod SSH：root@157.157.221.177:11965，密钥 ~/.ssh/id_ed25519。
- 2026-09-20 12:37 UTC：第60步checkpoint已保存，最终验证4/8任务完成，GPU0工作，GPU1空闲。不能当当前实时状态。
- 本任务未部署代码、未启动新批次、未跑新CI；已写设计不等于已完成实现。

## 冷启动 checklist
1. 读设计与本交接，查看用户是否批准及范围答复。
2. 查git状态，保留所有已有改动。
3. 查训练收尾、GPU UUID/进程占用和Tinker排期、Modal额度。
4. 核查全部候选checkpoint文件，处理58异常。
5. 按批准设计完成首题真实验证，再运行全量队列。

## 2026-09-20 执行更新
- 训练12:53 UTC PASSED，最终60步保存；delta失败原因是损坏的step58，supervisor已完成退出。
- 新文件 eval_result_check.py：精确parquet任务身份、每题样本数、checkpoint加载证明、底层退出码；validation.json complete才通过。
- 新文件 eval_checkpoint_matrix.py：manifest哈希、数据/基线哈希、进程锁、GPU空闲检查、每版本独立目录、有限重试、0样本停止、配对/行为汇总。
- manifest：docs/performance-9b/checkpoint-full-eval/manifest.json；服务器 runs/full-matrix-manifest-20260920.json。
- Probe：runs/matrix-probe60，脱机sid2663882，GPU0，step60，1题1次，原推理配置0.6/36864，model-only加载；14:20 UTC开始。
- Queue：runs/full-matrix-20260920-launch.log，gate.json/state在runs/full-matrix-20260920；初次等待进程已停止并更新竞态保护后重挂。
- step58 archive损坏已确认；保留证据，标记unavailable。
- 测试：14项新功能测试通过，Ruff全仓双门通过；更广回归卡在本地pandas/parquet子进程，已终止，不能宣称全套通过。
- 本地改动尚未commit/push；服务器已单文件部署，后续必须核对身份再交付。
- 下一次先检查probe validation.json：只有complete才让全量开跑；失败时队列会停，不反复空跑。

- 15:20 UTC复核：probe于14:55:35 UTC完整通过，1题1样本，得分0；第60步成功加载。队列重新启动sid2686667，首版本step60全量；仍需检查status.json实际running。

## 2026-09-21 继续推进
- 13:46 UTC远端队列仍在运行，非全部完成。RL60 attempt2完整46.15%，差-17.95pp [-25,-10.90]；RL40 attempt1完整47.76%，差-16.35pp [-24.36,-8.65]。
- OPD12/RL20各两次后仍311/312，原队列标exhausted。固定以attempt2补缺，不能挑得分高的attempt。
- OPD12缺TL10836：tmux no server；RL20缺TL08999：verifier timeout300s。只补infra缺口，不改已有效0分；由eval_supplement.py新模块执行（实现中）。
- GPU0评OPD10，GPU1空闲可补缺；运行队列仍旧进程，不能声称新代码自动热更新。
- 新证据目录 docs/performance-9b/checkpoint-full-eval/evidence-20260921/。
- 尚未得到全版本整体结果；用户明确要继续推进。

## 2026-09-21 补测部署
- eval_supplement.py 与 test_harbor_eval_supplement.py：9项补测测试+5项队列测试=14 passed，Ruff全仓双门通过。
- GPU1补测驱动：runs/run-supplements-20260921.sh；日志runs/supplements-20260921.log。固定OPD12/RL20 attempt2各补1，输出各自-label-supplemented-20260921目录，原attempt不动。
- 源全量队列status仍会显示这两项exhausted，不自动改写其他进程state；查询必须额外读取新目录validation.json、pair.json。
- 汇总时保留缺失当0的source_coverage_adjusted_framework_rate与补齐aggregate_framework_rate；历史infra事件不抹掉。
- 校验主要口径为framework resolved，behavior脚本raw reward solve_rate不同，不能混用。

## 2026-09-21 补测完成与跨集方案
- 补测驱动14:43:23 UTC exit=0。OPD12/RL20 aggregate validation均complete、errors=[]，每题4次无缺失。
- OPD12补齐43.27%，相对原版-20.83pp，95%区间[-28.53,-13.14]；RL20补齐50.96%，差-13.14pp，区间[-18.59,-7.37]。pair已存到checkpoint-full-eval/evidence-20260921/。
- 用户询问OPD+RL是否无效、能否评测其他软件benchmark。新文档docs/performance-9b/cross-benchmark-proposal.md记录结论边界、TB2.1/Verified/EvalPlus可行性和三模型对照方案。
- TB2.1 parquet远端存在；Verified适配入口存在但未端到端验证。新benchmark尚未启动。不能将本次序列训练结果推广为所有OPD/RL无效；缺严格纯RL对照。

## 2026-09-21 新跨集评测授权与部署
- 用户明确要求完成TB2.1后SWE-bench Verified三模型同预算评测，原队列继续。范围/manifest/config/audit均在docs/performance-9b/cross-benchmark/。
- Verified500题已下载。两套与实际S2训练500题的canonical ID/repo/题面哈希/词7-gram相似度检查无重叠；任务内容SHA已存，不能称语义污染完全排除。
- Verified500个verifier均采用FAIL_TO_PASS/PASS_TO_PASS及ResolvedStatus.FULL。远端nop/oracle控制驱动sid3495293，日志runs/cross-benchmark-20260921/verifier-controls.log。
- 新driver eval_benchmark_matrix.py，base/OPD12/RL60各固定3题探针后全量（TB n3、Verified n1）；--probe-only只验证不启动全量；base补缺已支持。新20测试通过；旧gate/matrix14通过；全仓Ruff lint/format通过。
- TB每题声明时间最多24600秒，Verified7800秒；配置外层分别25200/8400秒，sandbox25800/9000秒，同benchmark三模型一致。资源随任务，不压缩官方题目为满足旧3000秒。
- full计划2301条轨迹；已询问用户是否调高共享900美元上限。未获答复前不能默认扩额或启动整个full队列。小规模验证继续，GPU0旧矩阵不停止。
- 真实控制已完成：TB cancel-async-tasks、Verified astropy均nop0/oracle1；build-cython-ext oracle在planarity1.0.0/networkx3.6.1组合缺pos，作为已知参考解问题保留89题主结果，不能算模型失败证据。
- GPU1 TB三模型probe-only已发起，日志cross-benchmark-20260921/tb-model-probes.log，状态status-tb21-probe.json；不自动进入full。后续查真实加载/样本状态，不能把启动当成功。
- 新旧针对性回归合并34项通过，全仓Ruff519files通过；源码和manifest远端SHA与本地一致。全量仍未开始，预算答复待收。

## 2026-09-23 HF 数据归档完成

- 三套数据已重命名保存到 gump2049 私有 HF 仓库；入口 `docs/performance-9b/hf-data-archives.md`，机器记录 `hf-data-archives.json`。
- 保留上游固定 revision、数据文件、许可证、README 与 provenance SHA256。远端内容核验完成。
- 下一步仍是训练准入审计；不要把 archived_unvalidated 当成可直接训练。
- 当前分支 performance-9b；本次归档不修改训练进程，不能据此更新实时训练状态。

## 2026-09-24 Qwen Max数据补搜

qwen38-max-sft-review.md固定3库revision、区分Max-Preview/27B，候选有真实用途与污染限制，当前配额0。v2强教师核心不变，未下载全量/训练。
