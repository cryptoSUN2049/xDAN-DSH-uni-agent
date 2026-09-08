# N1 受控 RSI 候选持久选择合同

状态：主线程批准 CPU 实现；不启动学生、GPU或另造 Agent Loop。

目标：将模型候选提议与控制端晋升分离。固定父候选与内容 hash；独立开发比较通过后，
控制端原子切换持久 active 指针，独立新进程读取相同候选；真实回滚到父候选。
这证明持久选择，不等于 DSH 已实际加载或能力提升。

## 文件及 API

新 `uni_agent/tasks/dsh/rsi_candidates.py`、对应 tests；复用 memory_artifacts 的
无软链接目录、受限普通文件、私有读写与 sha 检查，不改其代码或旧 evolution verifier。

- `initialize(root, parent_spec, pins)` 返回外部应保存的 pins/candidate/active SHA。
- `Registry(root, expected_pins_sha256)` 固定控制端外部登记的环境与评估策略。
- `register(spec, parent_sha256)`：固定父 hash，返回候选记录 hash。
- `promote(candidate_sha256, receipt_path, expected_receipt_sha256, expected_active_sha256)`。
- `load_active(expected_active_sha256)`：返回候选与指针，包括候选 hash，供现有执行器加载。
- `rollback(expected_active_sha256)`：实际将 active 改回当前候选的父候选，返回新指针 hash。

候选只允许 `{schema, profile: sdk-minimal, allowed_tools: [...]}`，工具名来自当前固定
DSH 的白名单；不包含代码、patch路径、数据集、评分器或任意可执行配置。实际工具策略
overlay由独立可信执行器解释，必须把 candidate hash 带入其 profile/patch/run 证据。

pins 固定 model/runtime/base_harness/devset/verifier SHA、开发 case ID 集、逐题 token 预算。
开发比较 receipt 固定 schema、父/候选 hash、pins SHA、每个精确 case ID 的父/候选结果
（finished、eligible、reward、tokens、外部真实评估 receipt SHA）。全部正常完成且可信，
逐题无回归、总收益严格增加、候选逐题不超预算才可晋升。每侧结果必须用不同真实 receipt ID。
至少两个开发实例；实例是否独立由控制端冻结的 dev manifest 证明，字符串不同不自动证明。

外部 receipt SHA 只证明字节固定，**不是签名认证**。调用者须是控制端，先验证这些比较值
来自独立执行/DSH receipts，再将 expected SHA交给模块；学生不能自行传 expected SHA授权晋升。
本模块不伪造 fresh receipt 或 RL reward，不读取/改变封存测试集。

## 持久性、安全与测试

registry 必须新建且实际兑现0700/0600，使用/root或本地/tmp（Mac canonical /private/tmp），
不放宽MFS权限。目录/读写拒绝软硬链接、非普通文件、错误hash。固定父和pins不可被候选替换。
fcntl锁串行比较交换；transition记录先写入且fsync，再temp+fsync+os.replace active指针，
随后fsync目录。失败可能留下未被active引用的不可变记录；不能误认为发生晋升。

测试：新进程load、晋升后父回滚、旧active CAS拒绝、错父、receipt篡改/错pins、case遗漏/
重复、NaN/布尔奖励/预算超限、失败/未完成/回归无增益、共享receipt、任意code/路径字段、
非法工具、registry/source软硬链接、权限与重用目录。无学生/GPU运行、无捏造覆盖率。

工程验收以后仍须：可信overlay加载候选→固定模型独立开发比较→真实业务新任务与回滚
复跑。只有这些 runtime 证据齐全后才能称 RSI 执行链通过；本模块单独通过只记持久选择合同。

## CPU 实现结果与下一步 API 接线

已完成 `rsi_candidates.py`。27 项新测试与37项 memory_artifacts 回归共64项通过；
真实新Python进程分别读取晋升后和回滚后的持久选择；双并发CAS只有一个晋升成功。
另验证atomic replace失败原active不变、回滚后旧比较/重新包装的旧episode回执均拒绝。
未修改旧verifier/fixtures、未启动模型或GPU；不声称统计覆盖率或runtime部署完成。

`pins` 必含独立 evolution_run_id、model_sha256/runtime_sha256/base_harness_sha256/
devset_sha256/verifier_sha256、至少两个case_ids、max_tokens。跨registry候选因pins绑定而拒绝。
模块保存固定比较原始字节与transition历史；active回滚不会删除既有证据。
开发receipt history审核上限10000条transition，超过明确失败，不静默跳过旧回执检查。

API调用顺序（控制端伪代码，仅说明调用位置）：

```python
initial = initialize(private_registry_root, parent_spec, pins)
registry = Registry(private_registry_root, initial["pins_sha256"])
candidate_sha = registry.register(student_declarative_spec, initial["candidate_sha256"])
# 独立可信执行器：父/候选分别加载实际策略，执行固定开发case；审计真实DSH receipts。
# 从已认证评估结果构建comparison，控制端在registry外保存其hash；学生不持有这一调用权。
selected = registry.promote(candidate_sha, comparison_path, comparison_sha, initial["active_sha256"])
loaded = registry.load_active(selected["active_sha256"])
# 下一次真实DSH启动：将loaded.spec解析为受控overlay，记录loaded.candidate_sha256。
restored = registry.rollback(selected["active_sha256"])
# 新进程load_active(restored["active_sha256"])，再由同一执行器加载父overlay并复跑。
```

load返回 `runtime_deployed=false`，以免把读取配置误认为已施加策略。
候选allowed_tools只声明允许组合；不能保证对应Cordis插件在基础Harness已启用，也不提供
host安全沙盒。真实overlay接线必须核定base_harness hash、工具可达性及最终加载策略digest，
不允许学生把registry/pins/devset/verifier路径变成候选字段。
