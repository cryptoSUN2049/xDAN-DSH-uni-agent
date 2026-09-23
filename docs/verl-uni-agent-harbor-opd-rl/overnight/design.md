# 今晚多领域单教师OPD：执行与报告合同

2026-09-24，用户已明确批准实际测试、过夜训练、配置多领域数据和active goal。

目标：现有Qwen3.8-27B教师→Qwen3.5-9B学生；多领域单教师OPD，非MOPD。原版9B/27B/有效训练checkpoint分别同预算验证，HTML诚实显示缺失与失败。

阶段：兼容性CPU→HF/vLLM评分 → 固定revision数据分组构建 → 双卡LoRA纯OPD短程16步（资源探针可缩短但记录）→checkpoint独立加载 → 分域固定验证 → HTML汇总。
GPU0学生训练/rollout，GPU1教师。Decision Index用户授权停止，已确认897129退出。不得清理不属于本任务的进程。

本目录文件：train.sh（训练配置）、build_data.py（来源/拆分）、reward.py（评分覆盖显式）、evaluate.py（同预算生成/独立结果）、report.py/index.html（报告）、state.json（状态）、dataset-manifest.json（数据谱系）。文件尚未全部实现。

接口：数据需prompt messages、data_source、reward_model ground_truth、extra_info provenance；评测逐样本记录output、token_count、truncated、score/status/verifier。未知/不可评分不当0分加入能力均值；纯OPD内部reward占位与报告评分严格区分。

不使用付费沙箱，不擅自恢复已暂停DecisionIndex，不运行超大模型，不把静态SFT答案当on-policy。

验收：数据训练验证身份不重叠；领域配比+token统计；teacher logprob与HF对照；梯度非零且checkpoint存在；重载后独立验证；退出码/失败理由记state，报告生成不依赖训练成功。

局限：短程小验证集仅验证管线与方向；开放题没有独立可靠judge不得宣称综合正确率；code需隔离执行环境，通过前不报执行成功率。每5步开发评测和step4/8/16保存；最终评测checkpoint集合只含实际可加载产物。
