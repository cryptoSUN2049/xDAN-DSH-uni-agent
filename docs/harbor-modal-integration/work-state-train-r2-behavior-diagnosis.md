# Work-state train-r2：真实A/B行为与任务协议诊断

2026-09-09。通过原SSH endpoint只读检查`/root/runs/work-state-train-r2`，源码run固定`12902fb8849d9fdfa118686207669bbedfcfec37`。未改运行源码、本地实现、原回执、评分或GPU进程。这里核对保存的DSH request header、task prompt、工具call/result、final_response及实际文件；未重建原始backend token输入，不能据此排除增量token/history故障。训练数值结论以主线程消费与参数审计为准。

## 直接执行：已核实的第一层失败

这批不是单一问题。至少同时存在“未真正持久化”“业务对象与工具命令混淆”“未执行的坏tool-call文本”三种情况。

抽取时16个train chain分属4个group UID、每组4 sibling（WS01两组、WS03两组）；全部A实际memory库存为空，全部A无真实写调用。这里是独立episode计数，不将重采样组称为16道独立业务题，也不擅自映射为16次参数更新。

### 1. WS01：A只查看文件，B直接写入错误业务内容

证据chain：`memory-810f7001d1f3495ba2fa1b2573263918`，train、WS01 variant0、sibling0、group `b028da16-bbae-4c9f-acc9-4c4eeba3d6bb`。

- A prompt已明确session A只准备恢复状态，sources/对话不会复制到B，写入后从index.md发现；但开头仍强调“Memory artifacts are optional”，末尾允许brief handoff summary。
- A seq9真实view workflow；seq14/19/24/29/34/39依次view六个不存在memory目标。native反馈是`FS_NOT_FOUND`，提示“does not exist. Please provide a valid path.”。没有create调用，memory目录确实空。
- A最终回复称已review、ready for Session B，并只在最终文本写交接。原finished=true/eligible=true/reward0，符合当前合法低质量A合同，不能因此硬拒该样本。
- B没有任何view，直接seq9、14成功create两文件。落盘`config.json`为`{"config":{"max_retries":3,"timeout":30,"debug":false}}`，`plan.json`为`["str_replace","str_replace","str_replace"]`。
- 工具调用的`file_text`与实际文件原字节一致。这里不是editor把正确业务答案改坏；是模型提交的内容已经错。来源中工作流动作与配置字段没有被B读取。

另一WS01 validation chain `memory-47895f0a922f46128dba33b2b45cb065`同样A只view，B直接把`action: str_replace`及输出路径作为config，plan为`["str_replace"]`。这是相同业务/工具层级混淆的独立观察，不当作训练更新证据。

### 2. WS03：A口头声称已保存，B有未执行的坏tool-call

证据chain：`memory-284f38692f594117a470973b40e8f47b`，train、WS03 variant0、sibling0、group `4204511d-5f8b-4cc5-8ffe-fac24343637d`。

- A实际只view database/requirements/cache三文件，无写调用。最终回复准确复述若干观察，却声称“saved this information in the memory file ... memory.json”。实际memory目录空。自然语言保存声明不等于工具动作，不能由controller代写。
- B整个轨迹无tool/call。assistant/message seq8的content和内嵌stream均为普通text，包含`<tool_call>...file_text... </tool_call>`；最终config描述editor commands/permissions/memory/source paths，而非选择业务组件。
- 对原标签内部文本直接`json.loads`失败：`Invalid control character at line 2 column 567`，file_text字符串未正确闭合。其输出目录为空。因此这次没有可被直接执行的合法JSON调用；禁止“修复候选JSON再执行”而追认原rollout。
- 这说明DSH收到的已经是普通文本；还不能唯一归因于模型或Gateway parser。原始生成是否截断、parser如何回退为content，需要协议审计与真实token证据继续定位。

## 真实工具说明与提示的边界

保存的request/header中system为`You are a helpful software engineer assistant.`；只暴露`str_replace_editor`，其schema明确`command`是view/create/str_replace/insert，`file_text`是create所需文件内容字符串。没有发现schema把“业务config”要求变成“工具config”的指令。

两个值得澄清的任务协议点（是可检验的误导假设，不是证明prompt是唯一根因）：

1. 工具说明泛称“State is persistent across command calls and discussions with the user”，A任务又允许最终handoff summary。虽任务已写“conversation will not be copied”，模型仍把聊天摘要当已发布状态。新协议应直接区分：**只有成功文件写入的原字节会被转交；最终回复只给当前会话，不转交给B；六路径是新输出目标，初始不存在并非缺少输入。**
2. B只说“JSON object”和“ordered JSON array of action names”，与工具schema的command/action词汇同场出现。应明确：**config字段取自公开任务规格/实际恢复资料；plan中的action是任务工作流节点，不是编辑器命令；工具调用JSON只是写文件的运输格式，不得嵌入业务文件。**要求先view公开任务说明和可用索引，仍不得向B透传A私有source/truth。

A任务中“可选memory”应继续表示按需要选择文件，不应变成固定六文件检查单或固定每文件奖励；WS06仍应允许无记忆直接结束。WS01/03/05的必要信息是否保存，仍由真实B结果评分，不增加A满分前置门。

## 最小改进设计（未实施）

1. 先修/核结束原因与真实token/rendering证据。若运输协议损坏，再多prompt也不能替代接口修复。对合法tool-call、缺引号/截断tool-call各做真实codec回归；坏调用如实失败，不自动补写或改为成功。
2. 在新protocol revision中增加上述两段边界说明；可使用仅含字段类型、无本题值的schema说明。禁止示范正确capacity、版本、option映射或正确plan，不强制模型复制oracle步骤。保持原task truth、业务score、A0与B二元终局合同不变。
3. 用新run在相同结构/预算做少量baseline，先看是否真正A create→freeze→B view→业务输出；与r2并列，不追认旧数据。合法A空工件、B无来源/错误JSON依旧0分；成功业务配置有真实工具证据才1分。
4. 若协议与提示核验后仍四个候选全部同类失败，不继续无限扩大同样rollout。下一独立版本可做“只读→持久化→跨会话恢复”的逐段难度课程，保持最后A/B任务验收；这是课程分层，不是给写文件数量加奖励，也不是默认开启教师或SFT。当前主线不扩大到数据生产。

## 文档纠正：completed不证明未截断

此前专题MD/HTML的“不是max-token失败／不是token耗尽”应收紧为：**DSH reported completed；由于上游原始finish_reason丢失，不能排除底层截断。已观察的首个越权动作仍是独立确凿事实。**详见[在线协议审计](work-state-online-protocol-audit.md)。

本次WS03保存的stream也有`finish.kind=stop`，但该stop已在丢失原始原因之后，不能作为独立反证。DSH usage显示outputTokens=255，同样不能单凭它断言模型主动结束：必须核真实剩余预算及原始后端stop/length。此任务仅产出诊断文档，未修改专题或旧报告；由主线程统一纠正状态文案。

## 可复核原始路径与摘要

以下路径相对`/root/runs/work-state-train-r2/chains/`；SHA为不带前缀的SHA256。

| 证据 | 路径 | SHA256 |
|---|---|---|
| WS01 A prompt | `memory-810f7001d1f3495ba2fa1b2573263918/writer/prompt.json` | `2d906639166af3d4c1bd2ce6ea65b88286448b836286769900eaf9a040fdae4e` |
| WS01 A trace | `memory-810f7001d1f3495ba2fa1b2573263918/writer/run/traces/c534b1747a92638d8775a6ab/session.jsonl` | `f18c12c48a7fa38374fc9c7218ecc5467735a6cb36cd81b637d7580a976c1137` |
| WS01 B trace | `memory-810f7001d1f3495ba2fa1b2573263918/reader/run/traces/78798ee2bc718c015c13589f/session.jsonl` | `40df8bbcd2802704653fedc0e3d4a0901160e1a41e38d91135e513d0897aeec0` |
| WS03 A trace | `memory-284f38692f594117a470973b40e8f47b/writer/run/traces/1ebec8dc5d8c881b24d032e2/session.jsonl` | `b988051e00e1218f324b7e3be813449035ce3122a42b5e13a764b83aab40a855` |
| WS03 B prompt | `memory-284f38692f594117a470973b40e8f47b/reader/prompt.json` | `5ecfa32d7a8636cf760b5e21dce98e4a0a259d98f551c5bea642d8bd356110c9` |
| WS03 B trace | `memory-284f38692f594117a470973b40e8f47b/reader/run/traces/7fd65df32506bc500ffa9df8/session.jsonl` | `7642060e94931f201139f69c95802eb1a270d06b41a02e55989fad9ea12b2dad` |
| WS03 B result | `memory-284f38692f594117a470973b40e8f47b/reader/run/traces/7fd65df32506bc500ffa9df8/result.json` | `a807da449a6ffdb017672639de3d7ad4c8c9b1b0e7864c7b43e516574b85aea5` |

## 深度交互

“更多数据”不能自动解决语义对象没被识别与信息没有持久化的问题。优先把保存/转交/业务输出这三个合同说清，并验证真实token/结束原因，成本小于原样扩大采样。最终仍要让模型自己执行正确的读写和恢复，不能用controller代办制造看似完整的训练闭环。
