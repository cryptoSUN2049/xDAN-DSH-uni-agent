# Core r4：正式消费审计结果

原运行 `core-train-r4` 已终态；使用原执行 checkout `/workspace/rebuild/uni-agent-core-511bd71`、原venv及 `PYTHONPATH=.:verl` 执行正式 `audit_memory_training`，CUDA禁用、CPU线程限制1。审计exit0。本文仅下载既有报告，不再次运行审计，不改变运行/模型/来源门。

## 结论与范围

`passed=true`、`consumption_verified=true`、`run_completed=true`。16/16完整n4组、64条A→B链、128条唯一消费行（A64/B64）；errors、unknown_or_unadmitted_consumption、duplicate_consumption、overlapping_crosswalk_keys均为空。

实际消费16个独立训练task，全部variant0；WS01/WS03/WS05/WS06分别4/7/4/1组，即16/28/16/4条链。520是可用训练实例数，不是本次已消费数；本审计不证明有效梯度、参数变化、optimizer推进或能力提升。原始报告保留该限制。

已终态writer fixture记录26个尝试group、104条尝试链；监督日志明确10个被拒group，合计14个直接失败sibling。其余同组合法sibling也按完整组规则不消费：10×4=40条链不进入消费。不能将14直接失败、40未消费链与10拒绝组混为一个计数；也不能将被拒组内合法reward1追认成更新。

## 远程原始报告与本地封装

本地同名JSON将两个远程文件的解析内容完整收录在 `sources[filename].content`，另保留原始字节hash/大小/path。它是封装JSON，不冒称与任一远程文件字节相同。coverage快照时间：2026-09-10T07:24:15.135402+00:00。

| 远程文件 | 原始SHA256 | bytes |
|---|---|---:|
| `/workspace/reports/core-train-r4-final/consumption.json` | `sha256:9d27bf4f4b65ed4facdef708c8e6d1472dc0e9e80dd4ece7e0a860348e9a14bb` | 14564 |
| `/workspace/reports/core-train-r4-final/coverage.json` | `sha256:7ca17116793eb762f519ccd4a36ad6a04902690dcf023062bb5dc71ef7a6733a` | 8350 |

## 实际消费16题

全部task ID前缀为 `work-state-memory-core-v1-`；每行1个n4组、4链、8条A/B消费。逐组原crosswalk路径/hash保存在本地JSON的coverage内容中。

| step | task后缀 | group_uid |
|---:|---|---|
| 1 | `ws03-v0-s1001` | `1469d0c4-8d8b-4435-9901-bc5da6ba8309` |
| 2 | `ws01-v0-s1002` | `4e7def1d-18f7-4f5a-80bc-6f3a286a17b0` |
| 3 | `ws03-v0-s1002` | `1fcb6053-a86d-42c0-86d8-0cffe3b9e838` |
| 4 | `ws05-v0-s1002` | `5d8fc6ab-ab56-463a-92c0-b767c670310e` |
| 5 | `ws01-v0-s1003` | `dbace927-f111-4b51-8f58-fd74fc83a49d` |
| 6 | `ws03-v0-s1003` | `5b659c39-fcf2-4354-9bff-110d0b04f378` |
| 7 | `ws05-v0-s1003` | `41ffa531-39e0-44bf-9aa4-723cef9b75f9` |
| 8 | `ws03-v0-s1004` | `c6d27af7-52b6-401b-8692-5e336a47f0d3` |
| 9 | `ws05-v0-s1004` | `11e81431-559a-4372-be30-060c39f25700` |
| 10 | `ws06-v0-s1004` | `83fb61a7-a505-4738-a5e9-47641962ab00` |
| 11 | `ws01-v0-s1005` | `b8295e7b-5b46-4da0-a4e3-f1f52645399d` |
| 12 | `ws03-v0-s1005` | `e26e0ce5-8f24-4d40-8a38-c53db3fc393d` |
| 13 | `ws05-v0-s1005` | `6e873e86-cd76-4fa1-bf1b-a86d42e7ad74` |
| 14 | `ws03-v0-s1006` | `b0220c5b-e691-431e-9d13-3b9aefb2ce60` |
| 15 | `ws01-v0-s1007` | `4589ed9c-1bff-4d9e-82ce-dd0ef30a125b` |
| 16 | `ws03-v0-s1007` | `5128872e-2301-4cb9-83d8-61557f822a62` |

## 十个拒绝组

来源为终态writer fixture.training_stage.group_uid与 `supervision/train.log` 的 `strict rollout group rejected ... no trajectories will be written`。这些组未进入正式消费crosswalk集合；未修改任何准入规则。

| task后缀 | group_uid | 直接失败sibling / 4 | train.log行 |
|---|---|---:|---:|
| `ws01-v0-s1001` | `0cf3c2e8-777f-49bf-9f2a-5264c72d2287` | 2 | 1221 |
| `ws05-v0-s1001` | `f5ce3d38-3356-4f50-86aa-d1980502a8a8` | 1 | 1276 |
| `ws06-v0-s1001` | `7cd1e3ec-44dd-4e88-a7bb-b31edfd72503` | 1 | 1292 |
| `ws06-v0-s1002` | `5c2ba7d1-707c-454e-b670-206e78adebdf` | 1 | 1347 |
| `ws06-v0-s1003` | `143e3d33-a203-471e-a5af-84123df69387` | 3 | 1407 |
| `ws01-v0-s1004` | `35d5ab5f-3caa-4638-84fc-de0af2b937ef` | 1 | 1475 |
| `ws06-v0-s1005` | `eefb65de-b44a-4b27-8c2c-62bdefd73ecf` | 1 | 1617 |
| `ws01-v0-s1006` | `50793ed2-3a45-4b97-a28a-8637400c1666` | 1 | 1657 |
| `ws05-v0-s1006` | `566c6e15-643f-4915-a410-cb26c0d0481b` | 1 | 1691 |
| `ws06-v0-s1006` | `f0be8835-bdda-40c7-a0d9-944d319c7b89` | 2 | 1727 |

WS06前三组失败原因及被拒组内合法reward1的receipt路径/hash，保留在 [消费进度快照](core-r4-consumption-progress.md) 的独立补充小节。正式消费通过与运行零奖励/有效学习结论分开；checkpoint参数审计、after_run母文件验证与独立reload由各自报告确认，不能由本文代替。
