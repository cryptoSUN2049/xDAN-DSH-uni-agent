# 核心记忆/context：现有原四族的最短基线诊断

2026-09-09。用户最新优先先提交节点、再专攻核心记忆/context；异步扩展暂停。本轮仅只读分析已有报告、根因 JSON 和 tasks/scoring/stage 源码，写此文档；未改代码、未启动 GPU、未提交。这里的命令是现成入口说明，不是本轮已执行结果。

**建议先补齐旧轨迹的 A内容→B读取→工件结果归因，不再机械重跑四题或八步全零训练。** 已有证据充分证明原四族配置全错、同步链路可执行以及有效更新未通过；仍缺的是“哪些实例在 A 保存时已丢失必要信息，哪些在 B 恢复时没用已有信息”的逐事实证据。

## 1. 已经知道的事实，不必再烧一次 GPU 证明

- [r4训练](work-state-train-r4-result.md)：8完整n4组、64唯一A/B消费、6唯一任务；32个B奖励全0，梯度/optimizer moments全0，504 LoRA未变化。原始完成与拒绝组均保留。
- [独立重评分](work-state-r4-zero-reward-rootcause.md)及[JSON](work-state-r4-zero-reward-rootcause.json)：32/32 原奖励与重评分一致；控制器合法参考32/32可被接受；配置正确0/32。不是合法答案被评分器一律误拒。
- [独立四题reload](work-state-independent-evaluation-r1-result.md)：WS01/03/05 v1-s303 都是A0/B0、fresh且合法、实际消费通过；WS06 A max-tokens、B未执行、无消费。无需重跑同一套来证明“还是0”或“模型能加载”。
- selected-r1 的 WS05 A有72次view、6次create；六个memory路径各被view11–12次，来源只view2次，成功create后仍重复读取，最终max-tokens。不是持续权限拒绝引发的必然循环，也不能仅凭此断言“六文件列表是唯一原因”。

短课程已证明单动态事实 A保存→B读取→配置任务可以形成非零学习信号；这不追认原四族有效更新，也不证明完整索引、复杂计划、版本冲突与真实compact能力。

## 2. 不能把 A0 当成 A记忆失败

`examples/dsh/capabilities/work_state/verifier.py:116–152` 的 writer quality 初值为0，只在 reader 分支调用业务评分；A的reward_scope是 `deferred-to-reader`。所以原四族 A reward **按合同固定0**，不是A的事实正确率、记忆完整率或索引可用率。

`stage.py:278–329` 原样打包、冻结、展开A实际memory后给新B；没有控制器补完记忆。`stage.py:331–348` 给B公开来源、固定index入口与输出路径。A源对B不可直接访问，必要事实应在真实memory字节中。文件存在、A0/B0和trace finished本身均不能定位事实丢在何处。

## 3. r4现成分族诊断

下表由已落盘根因 JSON 的32个case逐族汇总，非新采样。“索引view”仅指尝试，不保证成功读取；空memory指产物清单为空，不判断非空memory语义质量。

| 任务 | 已准入B | 尝试view index | A冻结memory为空 | 两输出存在 | 配置正确 | 计划合法 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| WS01 | 16 | 0 | 1 | 13 | 0 | 0 |
| WS03 | 4 | 0 | 1 | 3 | 0 | 3 |
| WS05 | 8 | 1 | 0 | 2 | 0 | 2 |
| WS06 | 4 | 0 | 4 | 3 | 0 | 3 |

**关键修正：6例空memory中4例属于WS06，本来允许不保存；不能把6例都算A失忆。** WS01/WS03各1例空memory是A未传递源事实的明确候选，须结合B公开信息确认哪些必要事实因此不可达。

### WS01：恢复依赖与配置

`tasks.py:77–108` 定义线性/分叉汇合计划、completed、required、配置；`scoring.py:54–96` 校验实际config和plan列表。真实例：需要capacity168/schema_version2，B写100/1和虚构 `config_update`；其他输出还有 `configure_capacity`、`action1`。16例计划均不合法，13例两文件存在也不构成成功。

**已可归因**：B最终配置与计划生成错误、没有尝试固定index。**尚不能直接归因**：A非空memory是否保存对了capacity、schema、依赖和completed，B是否绕过index读了别的memory。应先检查原bundle和完整view事件，不把“没view index”直接等于“完全没读记忆”。

### WS03：多文件事实与索引选择

`tasks.py:109–152` 定义组件目录/兼容要求；`scoring.py:_configuration` 有WS03专有判定。真实例：config写 `catalog_database/catalog_cache`，需要任务允许的具体兼容选项；该例memory为空。3个空计划合法只是无依赖动作需要执行，不表示恢复能力成功。

**已可归因**：最终组件选择错误；一个A无memory且B缺源证据。**待核**：其他三例memory是否包含选项事实、索引能否到达正确模块、B是否读过模块却把类别名当具体选项。已有四例足够先做离线分类，无需立即新增更多WS03种子。

### WS05：作用域、版本与新约束

`tasks.py:153–205` 给A旧事实、B新通知并规定最终权威；真实样本中有handoff/index文件仍未产出最终结果。8例memory非空，只有1例尝试读index；6例连两结果文件都未形成。A重复view至max-tokens的selected-r1为另一个拒绝案例，不能混入这8个已准入B分母。

**已可归因**：B工件交付/配置失败；selected-r1 A停止策略失败。**待核**：A有没有保留scope/revision/source，B新通知是否被实际读取，模型是沿用旧事实、误用时间优先，还是根本未进入决策。仅文件清单不足以区分。

### WS06：不需要记忆的负例，暴露通用业务问题

`tasks.py` WS06 给完整公开短任务；A允许不持久化。r4四例memory空是合法的，B仍配置全错；真实例公开peak+reserve应得125却写100。这是B算术/阅读/工件遵约失败的证据，不能归因记忆没保存。

v1-s303 reload在A max-tokens中止，只证明A没及时结束，不能推断B能力。保留该失败即可；在停止策略或任务呈现未改变、也没有新的诊断问题前，不必反复重跑WS06等待它偶然结束。

## 4. 最短下一步：对旧原始证据做事实矩阵

以现有32条case为索引，只读对应private原件；不改旧run、receipt或reward。无需重新全量评分，已有32/32核验足够；新增检查集中于尚未读回的语义和先后关系。

每条记录：task/family/chain/原fixture哈希；A来源成功view证据；必须恢复的事实；A实际memory中的原文/JSON值与路径；index链接有效性；B公开notice已含哪些信息；B成功view返回的事实与时间顺序；最后config/plan错误。输出按以下类别拆分，允许一条多种故障：

1. **A传递缺失/错误**：A可见且B任务必需的事实，没有保存在任何B可达memory，或保存成错误事实。
2. **A索引失败**：事实存在，但固定入口缺失/悬空/指向A源绝对路径，无法正常恢复；单纯不写不必要文件不算失败。
3. **B检索失败**：有效index/事实可达，但B没有成功读取必要内容就生成结果。
4. **B使用/计划失败**：B实际成功读到了正确关键事实，仍输出默认100、错选组件、重复/虚构/乱序动作。
5. **停止/安全/基础设施失败**：max-tokens、越权或证据损坏单列，不装成普通错误配置，也不计完整训练组。

当前摘要JSON只有memory清单、index view尝试和最终产物，不含全部memory文本/成功返回内容；上述A/B细归因必须从 `/root/runs/work-state-train-r4/chains/<chain>/` 的writer来源、packed/frozen bundle、reader展开文件及trace读取，并核原摘要。原件位置可由case.fixture_path与对应crosswalk反查。原件不可达时标unknown，不猜因果。

优先抽取三族各一个非空memory且B配置错误的实例，加WS06的125→100，先验证矩阵能区分A与B，再对剩余已存在原件补全。此“抽取”是离线审计优先顺序，不筛选训练数据或隐藏失败。

## 5. 现成 base 单题入口：只有明确新问题时才执行

如果原件无法回答某个阶段问题，或需要确认当前固定源码下结果，再用现有 `prepare_memory_training --mode val` 跑一个指定公开dev任务。不依赖 short adapter，不传resume/mother，不启动训练。prepare支持单题选择；单题独立run可避免一题拒绝遮住其他结果。

下列在已经部署并核pin的GPU主机固定checkout内执行；本轮未执行。复用既有venv，先按runbook核有效VERL源码和runtime。新ID示例不可覆盖任何旧run：

```bash
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
WORK_STATE_RUNTIME="$("$PYTHON_BIN" -c 'from deepseek_harness_runtime import bundled_runtime_path; print(bundled_runtime_path())')"
CORE_RUN="core-memory-ws01-$(date -u +%Y%m%dT%H%M%S)"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
  --output-dir "/root/runs/${CORE_RUN}-data" \
  --run-root "/root/runs/${CORE_RUN}" --run-id "$CORE_RUN" \
  --runtime-executable "$WORK_STATE_RUNTIME" --runner-python "$PYTHON_BIN" \
  --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
  --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
  --family work-state-v1 --course work-state-v1 --mode val \
  --evaluation-task-id work-state-ws01-v1-s303
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
  "/root/runs/${CORE_RUN}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
  "/root/runs/${CORE_RUN}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
  "/root/runs/${CORE_RUN}" --memory-root "/root/runs/${CORE_RUN}/chains" \
  --run-id "$CORE_RUN" --output "/root/runs/${CORE_RUN}/core-consumption-audit.json"
```

WS03/WS05/WS06对应ID为 `work-state-ws03-v1-s303` / `work-state-ws05-v1-s303` / `work-state-ws06-v1-s303`，每次换新run ID，不能默认全跑。现入口val n1、完整A/B、fixed sync、supervisor上限3600秒；stage总token8192、每轮4096、runtime1800秒，严格finished/安全门保留。这是已有base参数，不是warm-start。

**现成入口限制**：不能通过该val CLI选择train v0-s101（选择器只接受validation ID）；不能只启动B、替换成oracle memory或对相同B固定A做配对重放。`evaluate_work_state_tasks.py` 是依赖mother/resume的reload套件，不是base单题基线入口。不得手改split、manifest或frozen memory绕过限制。

若下一步需要“固定真实A产物重放B”和“oracle handoff可解性”配对，必须另作诊断入口并保持独立实验身份，不能把oracle memory伪装成学生A。只有离线矩阵仍不能区分关键因果时才做这项最小扩展；不先扩任务数或实现整套新课程。

## 6. 验收边界与停止条件

本轮任务对象是 `config.json` 和 `plan.json`：`scoring.py:54–96` 模拟检查计划依赖与已完成集合，**没有执行外部数据库迁移、部署或有副作用工作流**。报告“计划工件合法”，不把 `plan_execution` 字段名写成“真实迁移已完成”。

诊断交付应回答每族最先可证实的失败阶段、未决项、原件索引及最小修复假设。若证据明确指向B通用配置/输出而非记忆，先修这个最小障碍；若是A信息丢失或索引悬空，再改相应记忆呈现/任务合同并版本化。旧分数不变，短课程成功不替代核心多文件目标。

当前不需要重复证明r4零梯度、不需要先warm-start、不需要新增144条数据，也不需要继续异步扩展。真实context操作仍按原完整目标另验，不能把文件记忆诊断结果冒称compact通过。
