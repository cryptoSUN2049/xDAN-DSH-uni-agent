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

## 06:48 UTC 补充：WS06 已尝试但前三组被拒，step10开始消费

此节保留上方06:44的1–9步边界不变。补充观察时间 **2026-09-10 06:48:49 UTC / 14:48:49 SGT**；只读已终态WS06原件及已完整写出的step10/11（各8行，读取前后文件大小稳定且uid集合与crosswalk相等）。未读取活跃第12步、未运行after_run；下列原件hash随后再次只读核取。

prepared `train.parquet` 实际按seed交错排列 WS01→WS03→WS05→WS06；WS06 s1001/s1002/s1003/s1004 分别位于第4/8/12/16行（1-based）。前三个WS06 n4组均已采样，因A失败被完整组门拒绝，不能归因“尚未采到”。fixture.training_stage.group_uid与下列监督器拒绝行一致：

| task后缀 | 完整group_uid | 拒绝原因 | `supervision/train.log`行 |
|---|---|---|---:|
| ws06-v0-s1001 | `7cd1e3ec-44dd-4e88-a7bb-b31edfd72503` | 1/4链失败：A max-tokens | 1292 |
| ws06-v0-s1002 | `5c2ba7d1-707c-454e-b670-206e78adebdf` | 1/4链失败：A max-tokens | 1347 |
| ws06-v0-s1003 | `143e3d33-a203-471e-a5af-84123df69387` | 3/4链失败：2个A max-tokens；另1个completed但eligible=false | 1407 |

三行日志均明确 `strict rollout group rejected ... no trajectories will be written`。s1003那个completed/不准入A的trace包含对只读 `writer-data/sources/request.json` 的 `str_replace` 尝试；不能因completed而忽略越权。以下5个失败A均未进入B。

关键receipt相对路径均以run根 `/root/runs/core-train-r4` 为基准；表中SHA256无前缀：

| task | 完整chain / writer receipt相对路径 | SHA256 |
|---|---|---|
| s1001 | `chains/memory-8ac7847fc48f4f8abbd9eb2f3f33abc8/writer/run/results/f67604342adbd32707ee319e/verifier-receipt.json` | `686799dfa3f287472c333b9dd81c203730c435384ca786bb5fb023fe70e7ba4b` |
| s1002 | `chains/memory-7262562d020f4cfcaf1c39215f078045/writer/run/results/46c324c4101c3b5d27bb0495/verifier-receipt.json` | `b7d3ec98ca815c7371c2a984809d592dd9811c10fcfbabe85e71c76ec3e8f0d0` |
| s1003 | `chains/memory-5cd83c454cf94773bcfb108cbc27e28e/writer/run/results/d35809f411bac0f708b222b7/verifier-receipt.json` | `bdc9462e9a601bbef502eb9d441772075497808ae9b1ba4eb3c1a3867fe1c425` |
| s1003 | `chains/memory-879c2531014140189dd72423677867f4/writer/run/results/c8d026279c42dd4bdbb5942b/verifier-receipt.json` | `861abf5b050265d891242e77bfbc74fe71c5314a24351ab863bbf62f6a560b52` |
| s1003 | `chains/memory-a198270c35284ad1a56aa9fcdcdfd63c/writer/run/results/0399aa7e6c98c73484139bce/verifier-receipt.json` | `aa056f9eb28ba45db16e1980ae46b131684dfb0809565c84ca762a452a7b7e48` |

### 真实reward=1存在，但未消费

s1001组的sibling3、chain `memory-401d590be7f4429b93e5b3a98b6a09f9`，B原receipt为 **reward=1.0、fresh=true、finished=true、eligible=true**。来源：

- `chains/memory-401d590be7f4429b93e5b3a98b6a09f9/reader/run/results/a55318cae7c503f9aaca8d86/verifier-receipt.json`
- receipt文件SHA256：`26c3f525e11f33db79243579f10d7ec5b97dfbe3178bfe8e2da30533559a66b4`。
- receipt绑定trace SHA256：`5eff054a0a81a9a6b044a14e6925c4795b72a52b7b541ee61e55db32067ac5c2`。

该组另一个sibling的A max-tokens，因此整组被拒；**这条合法高分不得追认训练消费、非零优势或有效更新**。这也说明“已消费奖励全零”不等于“全部尝试都没有成功”。保持完整组合同，不挑出高分补入训练，不修改原奖励或运行。

### 新增已消费step10/11

| step | task完整ID | crosswalk group目录 | 消费 |
|---:|---|---|---|
| 10 | `work-state-memory-core-v1-ws06-v0-s1004` | `53248775b7ce4840aa0e6b8ca22be4c7` | 4A+4B，4条完整链，dump score全部0 |
| 11 | `work-state-memory-core-v1-ws01-v0-s1005` | `5d7bd55ebd184cae9afaf67087b59342` | 4A+4B，4条完整链，dump score全部0 |

step10的真实采样group_uid是 `83fb61a7-a505-4738-a5e9-47641962ab00`；四个链分别为 `memory-e36436e195da44bdaadbca9decd31b98`、`memory-72037b0551184a47be9a6db64e9db4f2`、`memory-db5b6e74bb8b4af298bccc5577ab22b4`、`memory-23f12cd20d0f4d0aa0ab4f6212af36cb`，其A/B原receipt均finished/eligible=true。group_uid与crosswalk目录ID是不同字段，不混用。

| step | rollout SHA256 | crosswalk SHA256 |
|---:|---|---|
| 10 | `61a7876b2d1d1e34fd52f9961c8b9f8a27475b20ba714c215cdddc8c30c506b8` | `ab6c0d128b37f9b62258fa0b536b05ef242aef186aafde1fcb2f7b21c36b7114` |
| 11 | `c4690d8e1a1efc31e59a073b0715e2699772bde0ceb64d7abcba1c59aad9dc36` | `cd46a08b6ffc7972662e262316487e555bdc6f34df356f26e68dad1a40ff0d17` |

合并已完成1–11步：11个独立任务、11个n4组、44条链/88条A-B行；WS01/WS03/WS05/WS06分别3/4/3/1组，四族已消费覆盖。仍不是16步终态、完整审计或有效更新结论。
