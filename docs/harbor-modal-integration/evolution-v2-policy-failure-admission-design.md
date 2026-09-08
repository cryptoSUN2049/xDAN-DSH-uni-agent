# 独立 evolution verifier v2：保留可学习的已完成失败

状态：只读设计，待主线程实施指令；不改旧 v1、不追认旧 run、不改变成功标准或奖励数值。

## 已证实根因

`dsh-redact-m1-r1` step1 消费 reward全1，advantages/pg_loss/grad_norm全0。uid `5499f8a9-4b1c-45f4-903b-f445ea6cb375` 的 rollout0 session `session-sample-1-rollout-0-61149de6004a4fad838c8ba9d55aad05` 已完成且得0，但receipt eligible=false。原始receipt：`/root/runs/dsh-redact-m1-r1/artifacts/results/4704d80f84d401acc245067d/verifier-receipt.json`。

原始trace：`artifacts/traces/794ed275455b4e5d142c6796/session.jsonl`，21事件，seq9 str_replace_editor、seq14 cordis_inspect_list，末尾seq20 turn/end completed；SHA256 `7a3f5051e88c73f145cff4101016dddb43cfa1912edbadcb16c1238965e70cc3` 与receipt一致。没有define。因此旧hard_veto标签 `missing_pre_define_inspection` 在这里实际包含“已经inspect但没define”。

`evolution_verifier.py:_score_episode` 的grounding同时要求inspect和define，缺任一便hard_veto；最终details.eligible=not hard_veto。`uni_agent/tasks/dsh/trajectory_audit.py:197–198` 拒绝任何eligible非true，Framework整组evict。故这是可信、已完成普通策略失败被排出训练；不是unfinished、容量不足或已证实invalidtoken。其他当前ineligible还包括拼错工具名cordis_undefined，此提案不放开该类别。

## 最小 v2 合同

保留旧 `_score_episode` 七组件、权重、hard veto判定、reward与accuracy。新 verifier v2 在完整原验证（envelope/hash/fixture/session/metadata/runtime/profile/patch/trace等）通过之后，且仅当：

1. envelope.finished 是真正 bool true，真实trace末事件确认 completed；
2. 原 details.hard_veto **恰好** `["missing_pre_define_inspection"]`（不按包含匹配）；
3. 原 reward==0、accuracy==0，且其余身份/证据验证均合法；

则输出 `eligible=true`，reward/accuracy仍0；附 `admission_kind="completed-policy-failure"`、`original_eligible=false`、原hard_veto完整保留。原来eligible=true样本走 `admission_kind="original-v1-eligible"`，原值不变。其他情况原eligiblefalse不变或原验证异常继续拒绝。不得删除hard_veto、重算正分或转换NaN/错误为0。

这不是把所有模型错误自动收进训练；只修复已有实际证据支持的一类。安全/未知工具/逃逸、profile/patch不符、身份重放、trace/fixture篡改都不放行；`cordis_undefined` 暂仍拒绝。未来扩大准入必须有独立证据与版本设计。

## 文件/API与身份

- 新 `examples/dsh/evolution_verifier_v2.py`：复用旧公共/纯验证逻辑；最好使用 v1 `verify()` 完整验证后的结果再结合经过hash核验的terminal event与envelopefinished，避免复制评分算法。如需读env辅助，不覆盖原env/不伪receipt。输出增加明确admission元数据；v1文件不改。
- 新 `tests/uni_agent/examples/test_evolution_verifier_v2.py`：纯准入helper正负例与实际完整CLI envelope/hash/trace回归。
- 新课程config `examples/dsh/evolution_task_config_v2_policy_failure.yaml`（名称体现课程与verifier版本的区别），command指向新CLI，verifier_version=2及新id/manifest绑定。
- 课程数据准备入口通过明确新release参数或独立薄入口生成新数据版本与新verifier_code_digest；bundle必须包含新v2文件及旧被复用verifier所有依赖。记录父v1codehash，新task_version/TaskRef/source bundle hash与新run_id。既有4train/2holdout原题与合法代码不改；不覆盖旧parquet、receipt、trace、run。
- 原 Task/fresh receipt/trajectory_audit/Framework门保持不改。v2只有完成身份合法样本才生成新的eligibletrue receipt，原审计仍严格复验。不得修改旧receipt以使其通过，也不重新标注旧优化器消费。

## 测试门

1. 唯一missing_pre_define_inspection+completed+完整身份：v1 eligiblefalse、v2 true，reward/accuracy均0；原hard_veto保留。
2. 无define但有inspect；完全不行动但正常completed（若完整身份有效）：同规则0分准入。
3. 同时第二hardveto、未知工具/cordis_undefined、escape、profile/patchmismatch、unfinished/length等终止：不放行。
4. envelope/trace/fixturehash错、错session、末事件与finished冲突：验证异常或拒绝，不变成0分成功。
5. v1原正例、部分分与其他拒绝的reward/accuracy/eligible逐项不变；旧测试完整回归。
6. 新CLI→Task freshreceipt→trajectory audit CPU全合同验证；新模型采样组应保留真实0与1混合时的非零优势。真实optimizer/LoRA数值变化和独立reload另验收，不保证课程一定产生收益。

决策边界：修复准入选择偏差，不是为nonzero制造reward。旧run的0grad结论永久保留；新run需新来源身份与可复验组件证据。

## 原 run 终态复核

自然结束，无需发终止信号。远端 `supervisor-result.json`：exit_code=0、reason=training-exited、elapsed_seconds=1065.022；`exit-code` 为0。

- step1：evicted_samples=1，消费reward min/mean/max=1，advantages全部0，pg_loss=0，grad_norm=0。
- step2：evicted_samples=4，消费reward min/mean/max=1，advantages全部0，pg_loss=0，grad_norm=0。
- 全run当前42份receipt，5份ineligible；已核4份missing_pre_define_inspection、1份unallowlisted_tools:cordis_undefined。这些完成的失败被整组拒绝，使消费分布不能代表全部采样分布。

这是完整流程退出与零学习信号证据，不是成功强化学习。checkpoint1/2是否真正数值相同由主线程独立CPU权重/optimizer审计确认，此报告不以日志0grad替代权重比较。

## 本批实现与 CPU 检查点

已新增 `examples/dsh/evolution_verifier_v2.py`、`examples/dsh/prepare_redact_curriculum_v2.py` 及两份对应测试。配置由发布入口生成 `task-config.yaml`，避免提交容易陈旧的静态bundle digest；command明确指向新CLI、verifier_version=2。输入是原已发布 `dsh.redact-curriculum.v1` 4/2目录，输出新 `dsh.redact-curriculum.v2` 与task_version=2，原prompt/给定实现/题目保持不变。

v2运行时固定父scorer源码SHA `067668803e5f6fdb5f64cd44a17e2f4baef8835e4681a02cdf35d9f6bb4e3748`、base verifier SHA `eb5e0d68779739d04e1038534e5f2799a44cf299e7325ba2f6bef5c793ecf2cd`，规范化3文件hash映射（含v2自身）形成bundle digest，并与可信环境声明核对。新准入还拒绝缺result/重复callId/不匹配toolCallId，避免将宽松父解析的结构异常作为可信失败。

验证：61项CPU通过（v1/v2 verifier、原Task、原trajectory audit及两版课程准备）；Ruff检查/格式通过。新增实际子进程CLI→生产 `_task_result` fresh receipt→原 `validate_trajectories` 正负路径，token数组为CPU测试替身，不声称运行了真实模型或完整DshAgent。原reward0/partial/1保持；profile/patch/unfinished/unsafe/hash/session/duplicate与父源码漂移负例覆盖。无GPU、无旧run重评分、无Framework门修改。

部署准备命令：

```sh
python -m examples.dsh.prepare_redact_curriculum_v2 \
  --repository-root <当前代码根> \
  --source-dir /root/runs/dsh-redact-execute-r1-data \
  --source-manifest-sha256 sha256:<独立可信原manifest摘要> \
  --runtime-executable <固定runtime可执行文件> \
  --output-dir /root/runs/<新的v2数据目录>
```

新训练引用生成的train.parquet、holdout.parquet和task-config.yaml；原来源为完整hash绑定，不从旧receipt反推批准。正式运行/非零优势/数值更新/独立reload尚未执行，由主线程另行验收。
