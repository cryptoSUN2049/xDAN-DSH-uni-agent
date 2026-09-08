# T2 参数化日志工具：独立业务 oracle 与公开 fixture

状态：本子任务仅实现业务函数参考判定及数据，不实现 DSH 注册/调用/清理验证，不运行模型或 RL。

## 目标与边界

学生在 DSH 注册工具，按输入筛选日志并脱敏；此处 Python oracle 只计算输入的正确业务输出，永不加载或调用学生代码。后续 verifier 必须另行验证注册身份、至少两次不同输入真实调用、代码冻结后的独立隐藏输入、停止撤销与终态清理。公开4个train/2个dev仅工程数据；dev不是最终隐藏测试集。

## 公开 API 合同

`evaluate(records, *, severity=None, service=None) -> list[dict[str,str]]`

- records 必须为JSON数组；severity/service仅接受字符串或null，非法顶层参数抛ValueError。
- 每条记录必须是JSON对象且timestamp/service/severity/message四项全部为字符串。缺项、null、数字等非字符串记录跳过。空字符串是合法字符串。额外字段不保留。
- severity、service采用区分大小写的精确相等过滤；null表示不过滤，两个非null条件按AND结合。空字符串过滤器匹配空字符串，不等于null。
- 输出按输入顺序保留上述四字段。不排序、不去重、不解析timestamp，不修改输入。无匹配返回空数组。
- 只对message内匹配下述明确语法的ASCII邮箱替换为`[REDACTED_EMAIL]`，保留其余文本与标点；其他字段不脱敏。
- 邮箱语法：local为ASCII字母数字/下划线/百分号/加号/减号构成的非空片段，以单点连接；domain为ASCII字母数字开头和结尾、内部可含减号的标签，以点连接；末标签必须至少两个ASCII字母。允许大写和`+tag`，不接受连续点local或下划线domain。这是任务确定的匹配语法，不声称完整RFC邮箱识别。

## 文件与架构

- `examples/dsh/capability_tasks/log_tool/oracle.py`：独立参考函数与公开语法常量。
- `.../fixtures/train-01.json`至`train-04.json`、`dev-01.json`至`dev-02.json`：各有不同业务记录、至少两次调用，保存输入与约束，不存oracle输出或学生代码。
- `tests/uni_agent/examples/test_log_tool_oracle.py`：手写期待值、边界、不变性和fixture拆分检查。

流程：fixture输入 → Python oracle → 期望输出；未来学生工具输出 → 独立verifier逐项比较。oracle不依赖学生回报的reward或success。

## 测试门

先RED再GREEN：AND过滤、顺序/重复保留、email多次脱敏与标点、额外字段去除、missing/非字符串跳过、空条件与无匹配、非法顶层参数拒绝、输入不变；所有6个fixture合法，各split身份/输入独立且每case至少两种调用。Ruff与CPU pytest通过后交付，真实DSH执行仍为待完成门。

## 严格轨迹 verifier（G1 下一增量）

新增 `examples/dsh/capability_tasks/log_tool/verifier.py` 与独立 tests，不修改历史v3 verifier。
可信入口 `verify_trace(path, expected_digest, *, fixture, tool_name='filter_redact_logs')` 使用现有 `_load_trace` 校验原始JSONL摘要，复用 `_tool_calls/_tool_results` 的Session逻辑事件解析；纯 `evaluate_events` 仅供解析后的测试/调用，不能替代来源身份校验。完整task envelope/session/runtime/receipt由后续集成入口另绑定。

固定b236源码合同：`packages/extensions/tool-cordis/src/index.ts` define render行215，run render行269–278，inspect_self单Plugin行128–139（字段在根对象），stop行344，undefine行374；`providers.ts:48–61` Tool.listTools返回data.tools。成功工具canonical value不写durable event，业务输出必须render为JSON文本，不读取不存在的result.value。

验收有序阶段：空动态Plugin inventory及不存在候选Tool的inventory → 唯一new Plugin define成功 → 同P/Q首次run，读取真实R → inspect_self同P为running/currentQ/activeRunR → Tool inventory出现候选 → 至少两组不同records的公开fixture业务调用且输出oracle一致 → 同P stop成功 → Tool inventory候选消失 → 同P undefine成功 → 空动态Plugin inventory。允许阶段内额外只读inspect_list，禁止其他写操作或其他业务调用。starting不代表running，必须后续独立inspect成功；待启动只读观测可重复。

所有tool/call与tool/result必须串行、唯一且一一匹配；source.callId与toolCallId一致，失败/孤立/重复结果拒绝。完整终止事件须completed。结果里记录P/Q/R及调用身份，普通功能/生命周期不满足返回passed=false；原始hash/格式损坏抛异常。

此合同只评公开调用与生命周期，不支持隐藏输入执行，不防恶意学生篡改同宿主证据；后续可信隔离执行器与哈希固定必须独立实现。不得把其通过表述为抗恶意代码安全或RL完成。测试包含错P/Q/R、重复ID、失败结果、缺失/乱序、错输出、重复inputs、停止后仍可见、未清理等负例。

## DSH Task 集成增量

主代理新增 task_bundle.py / verifier_cli.py 及对应测试，复用当前 dsh_architecture Task，不创建新的 Agent Loop。fixture公开输入→hash固定task metadata→DSH SDK/Gateway执行→严格trace verifier→现有Task生成fresh receipt→既有VERL训练入口。数据层输出4 train与2 validation（来源public dev），不称sealed holdout。

数据合同绑定task_id/version/split、fixture路径与字节hash、runtime digest、verifier代码bundle、sdk-minimal及patch身份。CLI读取既有DSH_TASK_*环境和哈希绑定envelope，核对安装代码bundle与fixture，再调用独立verify_trace。可信输入损坏退出2，不伪装0分；真实模型业务失败返回0分并保留原因。新文件先CPU合同测试，真实runtime后再标集成通过。

### 准入与任务得分分开

完整可信的失败轨迹（工具明确返回isError、错误业务输出、错Plugin参数、漏清理、顺序不符合任务）保持`eligible=true, passed=false`，可作为0奖励学习。重复/孤立/不匹配call-result、缺少显式布尔isError、非法事件/参数JSON等无法可靠对应调用的结构证据保持`eligible=false`；原始trace哈希错误直接抛出。先完整配对全轨迹再做任务状态机，不能因早期普通失败掩盖后续重复ID。结束原因检查仍独立，最终Task.finished由上层envelope合同决定。通过只表示公开rendered业务结果和生命周期可验证，非隐藏输入或canonical内部value验证。

准备入口 prepare_training.py 仅写新私有run目录：train.parquet、validation.parquet、task.yaml和manifest。检查所选runner Python实际解析的runtime二进制hash；默认VAL_ONLY=True，最多1个公开dev样本作为学生baseline。训练开启是后续单独运行参数，准备数据不等于已训练。保留现有训练shell入口与显式容量/单卡LoRA配置，不改变全局训练框架。
