# MiMo + DSH 9B RL 核心目标复核

## 目标与范围

长期目标：让 9B policy 在固定 DSH harness 下，通过真实工具交互和任务反馈提升完成工作的能力，形成可复用、可追溯的云端训练体系。

当前里程碑：MiMo Code 小样本 → DSH → Harbor / Modal → Uni-Agent / TransferQueue → VERL / Runpod 的有效 GRPO 更新、checkpoint 保存及独立重载续训。打通后扩大任务池，再做同预算留出评估；工程验收与能力提升分别报告。

不把现有 20K 编程 SFT、历史 terminus-2 训练或手工正确补丁的 verifier 校准算成本轮训练成功。不声称原样复现 MiMo 论文规模和分数。

## 固定边界

- 起点：XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B，revision 2367e865d009c13ac81713a2878291d33ab28177。
- 数据：MiMo-V2.6-RL-oss Code，revision 639865fd3374018d6cb29b9fb82dd531406fcf5f；2698 行合同审计通过不等于全量任务运行通过。
- DSH：b2369692ea530007075ebcd18d39fdba0bbd3982；SDK/runtime 0.1.3a2，sdk-minimal。
- DSH 是 agent loop；Harbor 管任务与验证生命周期；Modal 承载沙箱；Runpod 承载模型推理与训练。
- 复用既有 vLLM / FSDP / LoRA 路线及冻结 uv 环境。Mac 只编辑、调度和读取小证据。
- 隐藏测试仅进入独立 verifier；基础设施故障不能当作合法 reward 0。

## 验收门槛

1. 真实模型生成完整 DSH 工具轨迹，任务产物经过独立 verifier，回执与任务/session 匹配。
2. 训练采用原始采样 token IDs、mask、logprob 和 policy version；工具观测不当作模型动作监督。
3. 同一步存在有效奖励差异、正负 advantage、有限非零梯度及实际 adapter 参数变化。仅 step 增长、weight decay 或全零 advantage 不算有效学习。
4. 保存 checkpoint；新 run/controller/Ray/session 重载模型、优化器等状态，再完成有效更新。当前 TransferQueue 无原生队列快照，不声称恢复在途队列。
5. 留存失败、成本、清理和训练证据；后续独立任务评估才能判断能力改善。

## 已完成与剩余

已完成任务合同审计、版本固定、真实 DSH 多轮工具调用；修复 Harbor 独立 verifier 测试注入并完成原生 0/1 校准；32K 上下文配置及 CPU 回归通过。

尚未完成本轮有效 GRPO 更新、checkpoint 保存/独立续训及能力评估。r4 失败证据已归档；r5 冻结源码已准备。

## 本轮资源决定

用户指定复用 high-performance（db7kewdkd71js6），SSH 157.157.221.177:11403，双 RTX PRO 6000，网络卷 72jdno5cuk。用户明确授权停止该机推理任务、清空 GPU，保留 Pod、环境、模型与数据。

本轮起初 SSH banner 超时；查明默认流量经过 utun4，单次 SSH 使用 `ProxyCommand=nc -b en0 -G 8 %h %p` 绑定 Wi-Fi 后成功，未修改全局网络配置。核验 PID 103940 的模型与端口身份后发送 SIGTERM，服务及 Engine PID 104728 均退出；实测两卡均为 0 MiB，compute-apps 为空。保留其他 CPU 服务、Pod 和网络卷。

复用既有 Pod 时不运行旧 owned-gpu-watchdog，不设置删除该 Pod 的清理动作；训练使用独立身份、限时 supervisor，只回收本轮进程和 Modal 沙箱。

双卡可用不代表必须先改造分卡架构。优先沿用已准备的单卡 colocate_async recipe 完成验收；需要吞吐或显存扩展时再单独验证双卡配置。
