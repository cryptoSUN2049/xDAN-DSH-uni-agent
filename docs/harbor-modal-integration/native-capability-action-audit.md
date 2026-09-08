# N1 原生四能力动作盘点

日期：2026-09-09。只读源码与合同审计；未调用模型、GPU或外部API，未实现新Agent Loop。以下任务是下一批可执行设计，不是已训练或已通过的结果。

## 1. 审计身份与实际执行边界

DSH源码按固定 `b2369692ea530007075ebcd18d39fdba0bbd3982` 使用 `git show` 检查，来源本地 `xDAN-DSH-Exp`；不以该仓最新工作目录冒充当前部署版本。SDK/runtime为0.1.3a2，Linux runtime摘要`d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。原生配置采用`profile=sdk-minimal`与`examples/dsh/evolution.patch.yml`。

| 边界 | 已有实现位置 | 实际含义 |
|---|---|---|
| Task启动/评分 | `uni_agent/tasks/dsh/task.py:389`，`DshArchitectureTask.run()` | 单次agent.run后生成envelope，再调用operator verifier；当前不是A/B复合Task |
| 输入 | `uni_agent/agents/dsh/agent.py:131`，`prompt_from_messages()` | 只允许一个user消息及system消息；拒绝把assistant/tool旧对话重放成新会话 |
| SDK执行 | `uni_agent/agents/dsh/runner.py:62` | `DeepSeekHarness(config)`中一次`harness.run(prompt, session_id=...)`；DSH内部拥有循环 |
| 隔离身份 | `agent.py:220`起与`runner.py:104` | Gateway session派生独立DSH home/artifact与dsh_session_id；回执绑定trace hash、profile、patches |
| 工作目录 | `DshArchitectureTaskConfig.workdir`、`DshAgentConfig.default_workdir` | 显式传递cwd；LocalSandbox不会自动为每个样本创建安全隔离文件系统 |
| 部署示例 | `examples/dsh/evolution_task_config_v2_fast.yaml` | LocalSandbox、sdk-minimal、原生runner、512每请求上限；文件是旧verifier v1示例，不能把文件名v2当成准入v2 |

原生进程工作目录隔离是任务隔离，**不是恶意代码安全沙盒**。固定sdk-minimal源码的sandbox-policy为`danger-full-access`，editor使用本地文件系统；新增任务不得声称绝对阻止访问宿主路径。第一批只运行受控课程，验证器/测试答案不得出现在学生可读工作目录。强隔离需求另由OS/容器环境实现，不能只靠提示词。

## 2. 当前模型真正可见的动作

固定DSH源码路径：`packages/bundle/sdk-minimal/cordis.patch.yml`、`packages/fs/tool-str-replace-editor/src/index.ts`、`packages/extensions/tool-cordis/src/index.ts`。

| 动作 | 精确用途 | 约束 |
|---|---|---|
| `str_replace_editor` | `view`（可`view_range`）、`create`（`file_text`）、`str_replace`（`old_str/new_str`）、`insert`（`insert_line/new_str`） | create不能覆写已有文件；本版本没有可假定的undo_edit命令；maxOutputChars=16000只是输出裁剪，不是智能上下文管理 |
| `bash` | sdk-minimal Linux persistent bash | 是现有原生能力，但首批四能力课程可限制合法动作不依赖shell；评分后置限制不是系统权限隔离 |
| `cordis_inspect_list` | 列当前Inspect provider及方法schema | 先发现再查询，不能把provider方法误当业务Service调用 |
| `cordis_inspect_query` | 参数`platform/provider/method/input`，来自实际list结果 | 原生课程只用host，避免client无页面响应；精确查询而非盲取完整Service目录 |
| `cordis_inspect_self` | 查询当前Session动态对象和实际状态 | 实例ID由运行时产生，不从训练数据硬编码 |
| `cordis_define` | new语义前缀→返回pluginId/packageId；existing pluginId→追加不可变Package | 定义不等于激活，code.host为普通JS函数体，无TS/import转换 |
| `cordis_run` | 精确pluginId/packageId，mode=run或update | 首次、当前重启或回退用run，切不同Package用update；以真实状态判断成功 |
| `cordis_stop` / `cordis_undefine` | 停止与删除当前Session动态插件 | stop保留Package/当前版本信息；undefine是不同生命周期动作 |

`evolution.patch.yml`仅增加cordis-host-runner与tool-cordis，不安装ContextPilot、专门memory工具或上下文压缩工具。sdk-minimal也未列入这些插件。不能出题要求调用虚构的`memory_write`、`compress_context`、`request_promotion`。

## 3. 四能力最小任务：每项两族加一个负例

### A. DSH能力发现与调度

1. **精确发现族**：给业务目标与只读输入文件；先inspect_list，再选择正确Tool的声明查询。oracle检查查询对象类型、schema字段和证据引用。变体改变合法业务目标、无关provider与当前注册工具；provider名称以当前runtime真实返回为准。
2. **版本生命周期族**：提供两个受控候选工具实现，注册→运行→多输入业务调用；切换第二Package，判断结果再回到旧Package或清理。复用现evolution插件与verifier工具配对/实例身份代码，新增多Package状态断言。
3. **负例**：不存在所需Tool但存在相似Service名称；应说明缺口或选择合法替代，不伪造provider、pluginId或结果。基线曾发生错误Service查询导致巨大输出，课程应保留该真实失败机制。

### B. 上下文与事实保真

1. **定向取证族**：把带行号的长记录放文件，题目只需少数字段；用view_range读取相关区段，输出答案+来源定位。同预算与读全文件方式比较正确率、事实准确和输出量；不以压缩token数量作主奖励。
2. **冲突证据族**：文件中包含旧规则、新变更和无关日志。学生读取带时间/来源的证据，生成小型事实清单并据最新有效规则作决定；oracle检查保留关键约束、区分推测、覆盖旧事实。
3. **负例**：一个关键字段没有足够证据，摘要中不得补造。把猜测写入“事实”应失败；完整回答“不足以确认”按任务合同评分。

当前支持的是**文件取证与外化笔记**，不是已实现自动context pruning。若要验证动作前projection、上下文过滤或ContextPilot树分支，需要新增实际接口/观测合同；不能用view_range替代后声称这些机制已打通。

### C. A→B跨会话记忆

1. **约束交接族**：Session A读需求/决定并用create写`handoff.json`；Controller冻结该文件。fresh Session B仅获得目标和冻结handoff路径，主动view读取后完成新问题。原始A材料、transcript和最终答案均不提供给B。
2. **记忆修订族**：A先记录偏好/约束，再看到明确修订，通过str_replace更新持久文件；B新进程新Session面对不同任务，必须用新版且说明来源。变体包括废止事实、冲突未解决、应保留的稳定约束。
3. **负例**：旧版本记忆或另一个chain的文件被交换；Controller通过chain/hash/version拒绝错配。无记忆对照不能隐含接收A transcript；B缺必要信息应明确不足，而非猜出隐藏答案。

控制端冻结合同：独立A/B工作目录与dsh_home/session；只接受白名单普通单链接文件，拒绝symlink/路径穿越/超预算；冻结原始bytes+SHA与chain_id/A_session/B_session/split；拷贝到B独立目录后再执行，不让B继续读写A目录。A输出的文件是记忆内容，不是训练答案标签。

当前`DshArchitectureTask`只调用一次agent.run；需新增**两阶段任务编排**和chain verifier，将两次独立DSH执行关联起来。它不是在DSH外重做Agent Loop。第一步先验证A/B因果评估和两份receipt；跨阶段RL的组身份、mask、任务结果信用归属需显式适配后才能训练，不能先把A/B轨迹简单拼接。

### D. 受控RSI / Harness改进

1. **先利用技能族（R1）**：A任务工作区已有验证有效的技能说明/候选源码文件，学生自然发现、读取并在新业务输入调用。无技能／自然发现／显式提供三组；显式提示组只诊断可用性，不计自主发现成绩。
2. **窄候选改进族（R2）**：固定模型，给同一故障机制的训练示例；学生用原生文件动作写候选源码，注册测试后提出采用/拒绝。Controller对新输入测试、冻结候选文件及父版本；新进程重新加载验证，再由Controller执行并验证回滚旧版本。先一个纯转换工具，不改DSH核心/验证器。
3. **负例**：候选仅硬编码当前样例、破坏其他输入或修改验证器。独立用例拒绝晋升；候选失败可以归档但不可deploy，恢复旧版本必须真实执行，不仅改JSON里的active指针。

现`examples/dsh/evolution_verifier.py:363`只校验最终报告status属于promote/reject/rollback与ID/证据字段。它没有持久晋升语义。R2新增的CandidateRecord/控制端部署回滚不能直接冒用现有七分项verifier名称与版本。

## 4. 最短下一改动与顺序

| 顺序 | 具体改动 | 不做什么 |
|---|---|---|
| N1.1 | 新课程manifest，列四能力/两族/负例、任务版本、实际动作、verifier身份与family/chain split；从另会话数据包导入受验证实例 | 不重新生产另一套教师数据 |
| N1.2 | 新原生准备脚本为每sample分配工作目录、冻结fixtures、配置独立verifier；A/B先各自单session CPU/脚本诊断 | 不改既有M1 pinned verifier与历史产物 |
| N1.3 | 加文件证据/事实verifier；合法完成失败与不可用证据分开，成功率/事实保真/恢复/成本独立报告 | 不奖励工具数、摘要长度、插件数 |
| N1.4 | 新A/B任务编排器+冻结artifact/chain合同，两次调用现DshAgent，先完成真实评估；再补Gateway多session训练归属 | 不安装第二套MemAgent loop，不默认ContextPilot存在 |
| N1.5 | R1先复用文件技能；R2增加versioned CandidateRecord和Controller晋升/加载/回滚，固定模型先测Harness-only | 不把status=promote当部署成功，不修改评估器 |

配置应新命名，不覆写`evolution_task_config_v2_fast.yaml`或原M1 reward合同。每一步先有CPU正反例，再真实原生运行。四能力课程的正式RL需学生有成功探索且奖励有区分度；全失败先诊断数据/动作、必要时SFT，不能持续空组重试。

## 5. 验收与边界

八个任务族和四个负例是首批设计覆盖，不保证统计功效。训练、开发、封存按family/故障机制/chain划分；仅换用户名不算新任务。记忆成功必须依赖合法转交产物且事实准确；RSI成功必须新进程/新任务复用。预算、完整率、拒绝率、token/时间与失败原因均留记录。

本审计没有新增工具API，没有验证ContextPilot已装，没有实际调用模型，不能将建议任务写成通过。Harbor暂停GPU期间只保留已有合同和历史结果，原生四能力优先。

## N1首批实施规格：单文件记忆冻结合同

2026-09-09已授权小批实现，仅`memory_artifacts.py`及测试，不接Task流程。

- `freeze_memory_artifact`：控制端传source_root、单个精确白名单relative_path、expected_source_sha256、source_version、chain_id、writer_session_id、max_bytes、新output_dir。校验源路径各组件无symlink、普通单链接文件、读前后身份/大小/时间稳定、实际hash；创建0700新目录，写0600原始bytes及规范manifest，不覆盖旧目录。返回manifest/content摘要，供控制端外部固定。
- `load_memory_artifact`：控制端传冻结目录、独立保存的expected_manifest_sha256、chain/writer/source_version、新reader_session_id及预算；严格JSON与文件hash/大小/身份检查。reader不得等于writer；返回不可变bytes与reader绑定记录，不自动写到B、不调用SDK、不评分。
- manifest不是自签可信来源，必须由控制端持有外部摘要；只改manifest+文件不能自我通过。source_version也是控制端声明身份，不声称读取仓库自动证明发布版本。
- 用dirfd/O_NOFOLLOW逐级打开目录与文件，O_NONBLOCK避免FIFO阻塞；拒绝绝对/../空白名单、软/硬链接、重用目标、错误chain/version/writer/reader、内容/manifest篡改及并发读期间变化。B真正fresh Session/工作区仍由后续Task控制端负责，字符串不等于进程隔离；本模块不是安全沙盒。

### N1单文件合同实现结果

已新增`uni_agent/tasks/dsh/memory_artifacts.py`及`tests/uni_agent/tasks/test_dsh_memory_artifacts.py`。先红测试缺模块失败，再实现；37项合同测试通过，与既有Dsh Task回归合计49项通过，Ruff双检查通过。覆盖读期间源文件变化、嵌套目录软链接、硬链接/FIFO、目标复用、冻结后源文件变化不影响快照、manifest重复键/额外字段/NaN/布尔size、源版本/chain/writer不符、reader=writer及源/读端预算。

Linux/Mac用真实文件权限检查，不假定chmod成功就安全；目标创建后立即复核私有目录/文件权限。类似已知RunPod共享盘不能保证私有权限时拒绝，不静默降级。macOS应传`/private/tmp/...`或实际目录，`/tmp`软链接会按明确无软链接规则拒绝。

写入失败可能保留本次新建但未完成的目录，调用者不会获得成功receipt，load无独立manifest摘要也无法验收；不自动覆盖或重试该目录。控制端可保留诊断后选择全新目录。此模块只返回读端已验证bytes，不自动拷贝到B工作区；仍未接Task链编排、模型采样或跨阶段RL。

## A/B真实执行隔离：固定DSH源码复核（只读设计）

### 当前配置不能阻止B读取A

固定`b2369692ea530007075ebcd18d39fdba0bbd3982`的实际实现：

1. `packages/fs/fs-local/src/index.ts:41`的配置仅`cwd`、`diffBasisMaxBytes`；约L60明确cwd是resolution default，不是containment boundary。`resolve()`对绝对路径不会限制在cwd。
2. `packages/fs/tool-str-replace-editor/src/index.ts:89`的resolveTarget要求模型传绝对路径，然后直接`ctx.fs.resolve`。因此“换B工作目录”不阻止`view /绝对路径/A/原始资料`。
3. `packages/fs/fs-sandbox/src/index.ts:1`与README明确所有mode的reads无阻碍，仅writeText/editText增加策略围栏。换成fs-sandbox并设read-only或workspace-write，**仍不能禁止读A**。workspace-write还允许平台temp roots，不能解释为精确B文件写白名单。
4. `packages/fs/fs-observation-policy`是观察后编辑/CAS规则，不是保密访问控制。
5. 当前sdk-minimal加载persistent-bash、bare fs-local；evolution.patch还开放动态插件代码执行。只限制editor路径而保留shell/动态Host代码，学生仍有旁路。

因此当前无一个已核实的SDK config字段可直接写成`readRoots=[B]`。文件冻结模块保护转交产物完整性，不保护A目录免受同权限B runtime读取。

### 最短原生路径：封闭memory动作集 + 可信前置策略

目标仅为本轮受控memory任务的“模型工具调用不能读取A、不能修改冻结handoff”，不是通用恶意代码隔离平台。

- 沿用同一个DSH SDK/Agent Loop，另设`memory-closed`专用composition身份，不用现evolution.patch。只保留模型面对的`str_replace_editor`；禁用/移除persistent-bash/pwsh与动态cordis插件、PTC代码执行、网络/任意Service调用及未来未声明工具。其他课程继续使用原composition，不能在旧奖励版本下静默变更。
- 复用真实扩展点`packages/core/tools/src/index.ts:136`的`tools/pre-execute` waterfall：返回`{kind:'deny',reason:...}`时在tool body前拒绝；仅满足role/path/command白名单才调用next。不自行解析模型token，也不新增执行循环。
- 一次runtime只承担一个A或B角色，策略配置由控制端只读注入。使用独立runtime/home/session/cwd，策略合同绑定role/chain/stage/source version/allowlist摘要。
- **A角色**：只允许`view`明确输入文件与当前memory文件；`create/str_replace/insert`只能作用于单个指定memory输出文件。输入、规则与评分文件不可改。
- **B角色**：只允许`view`冻结handoff与B问题文件；如任务需写答案，仅允许在一个指定答案文件create/str_replace/insert。禁目录view（避免探测路径）、所有A文件、session日志、凭据、源manifest与评价器目录。
- 路径必须经过lexical/canonical检查，拒绝`..`、软链接/硬链接/非普通文件；create只允许精确目标名且父目录固定。只做字符串前缀比较不足。持有批准文件身份或由受控backend在打开时核查，不能先检查A路径再让异步阶段打开已替换的对象。
- B没有任意代码执行/建链接能力时，可信editor处理模型字符串参数的白名单可作为本课程动作边界。若允许候选JS、bash或不可信并发文件写者，则该威胁模型不成立，须升级到OS用户/namespace等原生进程限制；不能拿这套薄策略宣称隔离恶意插件。

`ctx.tools.restrict({allow:...})`也是真实API，但只允许agent-scoped context，且只按工具名过滤，不检查路径。固定源码还注明scoped registrations保持可见，因此单靠restrict不能覆盖动态注册旁路。它可用于隐藏非课程工具的schema；权限最终由全调用前置策略拒绝未白名单名称。SDK root agent创建窗口目前没有本项目现成接线，不能伪造一个配置键解决。

### 待补最小合同与实测门

1. **薄policy插件与装载**：现有固定SDK未提供本项目的memory path allowlist插件。需按DSH现有插件加载方式打包一小段可信policy并固定hash，或在DSH-Exp增加正式插件再出发布物；不能仅把任意YAML当作已生效的权限。具体patch selector/发布方式需实现时按loader验证，不在本只读审计中捏造配置。
2. **composition自检**：一次无需模型的runtime工具目录检查，必须恰好只有课程允许工具；禁用工具不仅从schema隐藏，直接调用也应拒绝。启动时若policy缺失/配置错误，整个任务失败，不能回落sdk-minimal全工具。
3. **双进程真实拒绝测试**：Controller在A目录写唯一canary，B使用已知A绝对路径、`../`、symlink/hardlink别名尝试读取；必须在工具执行前拒绝、返回中不含canary。B读冻结handoff成功；改handoff拒绝；A写memory成功；新目录/新session/load identity与冻结摘要匹配。
4. **策略旁路负例**：直接call bash、cordis_define、动态工具、PTC等未允许名字失败；不把“不告诉B路径”或“碰巧模型没读A”作为通过条件。
5. **A/B链再接线**：以上CPU与真实runtime拒绝测试通过，再将memory_artifacts合同与两个原生Task/runner调用串联；先评估因果隔离，之后补跨session训练信用合同。

这一方案不用Docker、不需要立即建设完整安全平台；但**不是纯配置已可用**。现有配置能缩小工具集合，真正的读白名单还缺薄前置policy/backend接线与实际否定测试。当前步骤只读，没有声称已实现这些防护。
