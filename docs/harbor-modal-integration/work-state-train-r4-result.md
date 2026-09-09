# Work-state train r4：八步工程执行完成，参数没有有效更新

2026-09-09 07:11:13 UTC完成独立CPU采集。源码 `5b4b01b1d0ab656e960d3514d0a3630210913022`，远端 `/workspace/rebuild/uni-agent-work-state-r4`；run `/root/runs/work-state-train-r4`。supervisor child243079，exit0，1920.038秒。未操作GPU、未改母实验或checkpoint，独立reload由主线程另行执行。

完整逐步指标、原审计摘要、拒绝回执路径及证据SHA见 [result JSON](work-state-train-r4-result.json)。新原审计目录：`/root/runs/work-state-train-r4/final-audit-r1/`。

## 真实采样与消费通过

固定 `audit_memory_training` 独立检查原crosswalk、submission、receipt、NPZ和trace/result谱系，以及trainer实际消费JSONL：passed=true、consumption_verified=true、run_completed=true。8/8完整n4组、64/64唯一A/B消费行；unknown/unadmitted、重复消费、crosswalk键重叠及errors全部为空。

存在3次严格组拒绝日志与3份eligible=false阶段回执；失败组未进入最终消费，sync补采样后仍完成8组。未放宽安全准入或追认原失败。

| trainer step | 实际任务 | 四个终态B奖励 |
|---|---|---|
| 1 | WS01-v0-s101 | 0 / 0 / 0 / 0 |
| 2 | WS01-v0-s202 | 0 / 0 / 0 / 0 |
| 3 | WS05-v0-s101 | 0 / 0 / 0 / 0 |
| 4 | WS05-v0-s202 | 0 / 0 / 0 / 0 |
| 5 | WS06-v0-s202 | 0 / 0 / 0 / 0 |
| 6 | WS01-v0-s101 | 0 / 0 / 0 / 0 |
| 7 | WS01-v0-s202 | 0 / 0 / 0 / 0 |
| 8 | WS03-v0-s101 | 0 / 0 / 0 / 0 |

因此是8组、6个唯一task ID、4个family，并非完整覆盖8个不同题目。全程独立训练，无initial/periodic validation。

## 原始token终止边界

现有 `audit_memory_generation_boundaries` 对64条已消费轨迹的289个原始生成段逐段核验，passed=true：289个EOS，0 non-EOS，0 EOS/capacity tie，errors为空。EOS IDs151643/151645来自实际固定模型配置，config与generation_config SHA在JSON；声明容量16384。

这是原token证据，不是恢复backend历史finish_reason；审计器未修改原token/回执。报告中保留审计器原静态limitations文本，其中关于固定VERL终止原因丢失的描述针对未补丁基线；当前r4已使用部署锁记录的finish-reason补丁，补丁验收独立记录，不能用静态说明否定实际部署身份。

## checkpoint与optimizer：如实未通过有效更新判据

使用原脚本 `deployment/checks/checkpoint_delta.py` 与 `optimizer_delta.py` 比较云盘checkpoint4→8，CUDA_VISIBLE_DEVICES为空、OMP/MKL各2线程、可信权重weights_only CPU加载。

- **模型delta passed=false**：504个LoRA张量无变化，399个base张量无变化，全部finite。step4与step8模型文件SHA完全相同：`0ce64d8d9bc5bf0ad96115c93db6e538729ca8daa2155a0bf884c50caa765659`。
- **optimizer delta passed=false**：原审计拒绝原因 `All optimizer moments are zero`，如实保留exit1与报告，不当成脚本执行故障重写通过。
- 额外只读实际checkpoint：step4/8各252个lora_B张量均finite、精确0；各1008个moment张量也均finite、精确0。optimizer内部step集合分别为8/16，不能等同trainer global_step4/8；文件hash差异不能称为权重变化。
- 八步metrics的reward范围、advantage范围、actor loss/pg_loss/grad_norm全部0。没有有效任务梯度，也没有4→8参数变化。没有重新随机初始化LoRA冒充step0；本报告没有原始step0快照。

模型/optimizer/extra/data已保存至 `/workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_4` 与 `global_step_8`，可以用于下一项独立加载验收。成功保存、推进optimizer step与成功重载，是工程证据；本课程有效学习和能力提升仍未通过。保持工程执行、有效参数学习、业务效果三个结论分别报告。
