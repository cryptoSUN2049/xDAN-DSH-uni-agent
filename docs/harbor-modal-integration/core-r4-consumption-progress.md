# Core r4：已消费步骤 1–9 快照

快照时间：2026-09-10T06:44:34.726106+00:00 UTC（新加坡时间 UTC+8）。运行根 `/root/runs/core-train-r4`。只读指定已完成的 `rollouts/1.jsonl` 至 `9.jsonl` 及其九个对应 crosswalk/A-B fixture；不读取活跃第10步，不调用 after_run，不重做完整token或梯度/optimizer审计，不修改远端。

## 当前可确认计数

- 9 个 n4 完整消费组、36 条唯一 A→B 链。
- 72 个唯一 dump.uid/TQ key，A 36 条、B 36 条；每步均4A+4B，跨这9步未重复。
- 9 个独立 task ID，均 variant0；WS01 2题/2组/8链/16条A-B行，WS03 4题/4组/16链/32行，WS05 3题/3组/12链/24行，WS06 0。
- 这9步dump的72个score均为0；其中A为延迟奖励，不能用A0判定保存质量。本快照不重新核验receipt评分、token/version span或梯度。
- 实际已消费独立任务是9/520；36次采样链不是36独立题。准备数据规模不等于消费覆盖，WS06尚未在本范围消费；不据此推断它被永久跳过。

## 逐步任务与来源

每个完整ID均为 `work-state-memory-core-v1-` 加下表后缀。每行1个n4组、4条链、8个唯一A/B行。

| step | task后缀 | crosswalk group目录 | expected policy |
|---:|---|---|---:|
| 1 | `ws03-v0-s1001` | `1c2f7e0faa414043b9a62ade9de3774b` | 0 |
| 2 | `ws01-v0-s1002` | `08c92b7a0b8340a1b30e3634d8b1862a` | 1 |
| 3 | `ws03-v0-s1002` | `3dd63d12d00c4a0ba1f598eef2620b8f` | 2 |
| 4 | `ws05-v0-s1002` | `0a6e90c54160495cb77cb9cf758c6531` | 3 |
| 5 | `ws01-v0-s1003` | `1db9b06c82c841fbb74ddfd3399f30ea` | 4 |
| 6 | `ws03-v0-s1003` | `45337051f42a464d9f0fdb0a70d929e1` | 5 |
| 7 | `ws05-v0-s1003` | `c723e0e1c7be447d9d7498047387b5a5` | 6 |
| 8 | `ws03-v0-s1004` | `243df0c2aaf74881b1a65624c853e02f` | 7 |
| 9 | `ws05-v0-s1004` | `c51e475be16443409248baf4929108ee` | 8 |

路径：`rollouts/<step>.jsonl` 与 `chains/groups/<group>/crosswalk.json`。每个dump.uid集合与该crosswalk.items.tq_key集合精确相等，均8项；crosswalk.global_steps匹配step、partition=train；每个chain的A/B fixture.task.task_id一致。实际消费的 task 身份来自这些fixture，而不是按schedule预计。expected policy只是crosswalk字段，此次不冒称重审了实际逐token策略版本。

## 可复核哈希

下列均为SHA256，不含 `sha256:` 前缀。

| step | rollout | crosswalk |
|---:|---|---|
| 1 | `204558a3b735564bedb4829e7ab9e36efc5547a2f1885537cd5c11403d30dd31` | `66751c4968d62e9ed675b821854de1d8c5d77e4af1e86f821802178559f2c850` |
| 2 | `df9c22b21c299c3e17b09475f3a8c1a8e69f26bbbb38f1068428fdedd4890b0e` | `4e3097f9d5f1b0c5b7ae2cde166b0be3bcb26179b5d0e2a2d276cfc90f46007a` |
| 3 | `216f3e39a2606a735077a1391851f76115558c4391222cf389dcf3acace02e1a` | `9cd2f2ce40b2269df3c3e134fd6e7daf4422e6d28d29c8765afd06851ced95e4` |
| 4 | `149d90ac8d7fe06096a68ddfac03dba41b944388ee383ed08fdb43878aa030e5` | `8568e6fc7bef0c87591ec98708ff816c2e9e36e687b93897f0da81eabc91cbd7` |
| 5 | `74d49abfd78f8c9d3040fbf312727136e22711b7af72c001c38dfc01074125eb` | `af8a75890c96f29cdab17a3932f165d5bef5cf6a712e551a2b04cdede2e5305d` |
| 6 | `b6fe0748768e58f2d1c3002d59d047574fca18de30f39e3da8c89caef7edcdcd` | `2f2199db37ede70c45ae91cde1efc2492bc61754db8ed6024b5271902f6d865f` |
| 7 | `8df90c60767d5cf3e1b16aa03b6b3cb7946cbcc04c0367a619764472356a8f08` | `85d9bc24382d2a84bdf60e77bd9bc5ad523177269c6dabd45a1d69818b0ed93f` |
| 8 | `58203c72da0866fa7d399219067cc95f540290fe8c3acbf826391fa138d4b8ef` | `0557af157eb6947712c0702f4d67a33644e3b504b83326e3d1593003d4a3d03d` |
| 9 | `a1044b3f8aec7d33e33f2db22aae4022a42c0bcaf10b510dc0536de6379ccc67` | `983e216925058f094e7449a9c4b8c6c7d2da25c5402a6d53139732cd4f9a7e92` |

## 使用边界

这是运行中消费覆盖快照，不是全run准入通过、16步终态、有效学习或效果评估结论。被拒/evict但未出现在这9个dump中的尝试不计消费；快照也不统计总尝试/拒绝率。最终由终态审计核全部原件、原奖励/版本、唯一消费、有效更新与checkpoint/reload。
