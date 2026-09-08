# Resident memory stage 准备与冻结

已批准实施；仅控制端CPU接线，不启动模型/backend，不写TQ。文件：新增 `examples/dsh/capabilities/memory_training_stage.py`、`tests/uni_agent/examples/test_memory_training_stage.py`。

接口：OperatorSpec固定root/runner/runtime/hash/checkpoint/family，GroupContext固定run/partition/group/sibling/global_steps。prepare_writer_stage(operator, context, chain_id, gateway_session_id)创建新的私有chain目录与writer fixture/profile/YAML；StageSpec返回路径、原prompt、metadata、文件hash与expected identity。操作配置仅写可信YAML，不接受sample覆盖。freeze_and_prepare_reader(writer_spec, execution, reader_gateway_session_id)先校StageSpec文件/runtime pin，再真实trajectory_audit；绑定TaskResult与trajectory、context/session/group、真实metadata/envelope/receipt；用原score复核实际trace/source/memory。仅A reward1、eligible/finished通过后冻结，并创建B只读frozen/question的profile和配置。A/B各home与artifact独立，不调用memory_chain.run_stage/推理CLI。

测试先红后绿：私有配置无共享、source/fixture/config/runtime变动拒绝；真实DSH Task+新训练verifier子进程产生合成动作回执后才能freeze；混group/session/parent/reward/旧trace拒绝、低质量与越权拒绝、重复freeze拒绝、B policy不含A source且没有写目标。CPU合成证据不等于真实RL。配置/sessions由可信Framework控制，不是OS级安全沙盒；实际版本完整性由已交付credit合同在组级检查。

## 实现结果

prepare_writer_stage / validate_stage_execution / freeze_and_prepare_reader与OperatorSpec、GroupContext、StageSpec已交付。新stage私有prompt.json、fixture.json、closed.patch.json、task.yaml及相关源码hash绑定；runtime重新核验，envelope原始prompt与stage准备prompt一致。校验接口返回(receipt,envelope,rescore,fixture)，方便后续组级credit使用原始身份。

10项新增CPU测试通过，与独立训练verifier及原memory chain回归共76项通过；全仓Ruff check/format-check通过。共享测试助手 `tests.uni_agent.examples.test_memory_training_stage.execute_synthetic_stage` 执行真实TaskConfigResolver→DshArchitectureTask→verifier子进程→磁盘回执，只有Agent动作和Gateway tokens为明确合成。完整writer→冻结→reader→独立重评通过；混group/session、源文件变化、错误记忆、修改prompt、复用reader身份及重复freeze均拒绝。

本模块不启动backend，不赋跨会话credit、不写TQ。A reward1门不变；reader policy仅含frozen/question且writeFile=null。实际策略版本完整性留给已实现memory_credit组级合同；OperatorSpec checkpoint_identity是操作员pin引用，不是从模型权重自动计算的证明。Framework还须绑定当前加载版本、执行超时与取消清理。外部控制端对象是可信输入，接口不是接受不可信字典的远程RPC。
