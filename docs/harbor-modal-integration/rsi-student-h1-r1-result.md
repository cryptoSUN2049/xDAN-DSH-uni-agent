# RSI 学生候选 H1 r1 真实评估

固定执行源码b1c568bc4a158309f1435d907cd51ec96538ea92。候选438ad34856e6169fb0cdc92a219ea2b4c7f5c4f6440114879652f4ce3b2942a8来自已审核学生P，不是控制器手工配置；使用candidate-evaluation overlay，父active仍保持fd91e253…。

H1于2026-09-09 21:59:36(SGT)启动；监督子PID325100，exit0、266.021秒，无健康失败；实际两题推理49.9秒。独立result_binding与audit_episode均通过，2条唯一真实TQ消费，任务finished/eligible；GPU已释放。

| 任务 | H0 | H1 | 实际行为 |
|---|---:|---:|---|
| inspect-discovery | 0 | 1 | H1成功调用inspect_list并回答host/Tool/listTools；38模型token |
| file-constraint | 0 | 0 | H1读对文件，但仍把value写成max_attempts=3；89模型token |

两题各一次、同固定模型/任务/预算。新候选解决了已暴露的inspection权限限制；文件输出错误未修复。平均分0→0.5是本轮两题开发观察，不是统计显著泛化收益，不是模型参数更新。

[完整独立审计](rsi-student-h1-r1-result.json)。H1准备manifest SHA256=ad62faa9c4c14d7a76da069a0d737fef1f71833d81188bf91712d3d7ed02bb3f；原run=/root/runs/rsi-student-h1-r1/H1。新paired准备中的H0未运行，比较必须用原真实parent-baseline H0。本文未执行晋升或回滚；组合比较器还需联合重验P来源、四条worker及两边身份后再输出Registry可消费的比较回执。
