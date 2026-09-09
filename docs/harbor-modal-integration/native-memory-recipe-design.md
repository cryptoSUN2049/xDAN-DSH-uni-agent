# Resident memory 最小 recipe

目标：用现有单卡 DSH ops → VERL v1 sync → NativeMemoryFramework 入口运行 A 写入、freeze、B 新会话读取。默认仅 val；显式 train 才启动 n4 GRPO。不是新 trainer，也不是第二套 Agent Loop。

新增 `examples/dsh/capabilities/prepare_memory_training.py` 与对应 CPU 测试。准备器生成单族一条 train 和一条 public-development val 调度记录、占位 task YAML、环境和 Hydra 尾参数清单；实际任务内容由已有 StageSpec 在私有目录生成，两条记录不能算独立能力留出集。支持 constraints 或 updates，每次一个 family。

固定 sync、train n4、val n1、all trajectories、真实 TaskRunner、strict 四门、StageSpec 独立审计；关闭旧静态 postprocessor，其全局目录不适用于 A/B 私有 stage。保持阶段原始 reward，末 B reward 由固定 VERL GRPO 广播。A=1 准入门不变。

实际准备 API：`prepare(output_dir, run_root, run_id, runtime_executable, runner_python, model_path, model_revision, family='constraints', mode='val')`，均为 keyword-only。checkout 由已导入模块的 `ROOT` 确定，不接受外部 checkout 参数；runtime SHA 和 VERL/Student revision 来自当前 `g1-deployment-lock.json`，不接受手填 runtime SHA 覆盖。新目录拒复用；SDK/runtime 0.1.3a2 探针清空旧 PYTHONPATH/PYTHONHOME/CUDA；记录实际集成 HEAD/branch、VERL SHA、deployment lock、模型 config/tokenizer 身份及 source closure。启动只消费清单环境/固定 argv，重新校验所有源/输入/runtime/model hash 和 checkout，跨 cwd 导入预检，owned supervisor 7200s train / 3600s val。模型 revision 必须等部署锁，但仍不冒充外网来源验证。GPU部署前还需核该 HEAD 干净且 source 已被 Git 跟踪；准备器记录文件哈希不能替代 clean-checkout 审计。

命令入口：`python -m examples.dsh.capabilities.prepare_memory_training prepare|check|launch`。完整参数及先 val 后 train 操作见 [recipe runbook](native-memory-recipe-runbook.md)。Hydra 尾参数用 `postprocessor_kwargs=null` 清除旧字典；空字典合并会保留旧 roots。launcher 显式创建 700 的 `run/chains`，不能依赖测试 fixture 预建父目录。

测试：先 missing module red；真实 Hydra compose 原训练配置与完整命令尾参数，再调用 NativeMemoryFramework.from_config（仅 fake gateway）；验证 n4/val1、动态私有 roots、无静态 postprocessor、禁止旧 artifact/run 复用、runtime/hash/版本拒绝。无 GPU。真实 resident token version、TQ 消费、更新和 reload 尚需后续 GPU 验收。

CPU结果：6项通过（18.66秒）；真实 shell 执行分支仅以记录 argv 的 Python stub 替换最终计算，真实 Hydra/from_config 解析通过。launcher 的 CPU 冒烟实际生成首 A StageSpec，证明父目录创建；仅替换 nvidia-smi 与 supervisor 子进程。未启动 GPU、未宣称模型训练或提分。
