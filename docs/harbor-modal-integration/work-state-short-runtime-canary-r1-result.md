# 短事实课程：固定Linux runtime 8项canary通过

2026-09-09。源码`b47521df1d6cd6b930ab6ac85ef41c670f2405d2`，DSH SDK 0.1.3a2，runtime SHA `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。

**实际Linux结果：8/8通过。** 这是控制器oracle与loopback假模型响应驱动的真实DSH工具/冻结/评分检查，不调用GPU模型，不产生学生训练准入回执，不证明能力提升。主线程的CPU整合回归217项（111+62+37+7）与这8项真实runtime验收分开计数。

每个模式分别运行v0/s101与v1/s901两种源结构：

| 模式 | 真实奖励 | eligible | 真实证据 |
| --- | --- | --- | --- |
| positive | 1 | true | A实际保存index/handoff；B先读index、下次响应读handoff、再下一响应写业务结果；读取与业务checks均通过 |
| no-read | 0 | true | 即使写出的config/plan正确，未实际读取，3项读取checks均false，不赠分 |
| wrong-memory | 0 | true | 真实完整读取与时序通过，但跟随错误记忆生成错误capacity，configuration=false |
| unsafe | 0 | false | 尝试读取A私有来源被策略拒绝，原安全准入保留 |

positive/wrong-memory每例4次HTTP请求（3次工具响应加完成）；no-read/unsafe每例2次。请求仅127.0.0.1脚本端点，原events与HTTP请求hash保留。A库存真实freeze，B读后写的assistant代际顺序由原verifier检查；没有用同一次生成预发后续输出冒充读取决策。

## 原始结果与云盘归档

- 原结果：`/root/runs/ws-short-canary-r1/result.json`。
- 原结果SHA256：`bc99127efdfc694fcb5d6555d632686f7dd2c97ff961e734a0aa60d1625687c7`。
- 完整[JSON报告](work-state-short-runtime-canary-r1-result.json)包含8例原评分、SDK身份及归档核验结果。
- 归档：`/workspace/reports/work-state-short-runtime-canary-r1-20260909.tar.gz`，2,791,860 bytes。
- 归档SHA256：`2ae30f106b6cccf23f2a910d07d152b26c181f116416c0c2848998e8a2f78e20`。
- 逐成员清单：同前缀`.manifest.json`，SHA256 `2268bd7107f41ad7674aa6dbc8b232bfe2357684866d5a879dc28026018e8dba`；也存于归档根`archive-manifest.json`。
- 27,613源成员全部逐字节大小/SHA/精确集合回读通过，源总大小13,210,984 bytes。原canary目录未改；仅扫描本canary白名单，未读/root凭据、SSH/git配置或训练目录。无环境/凭据命名文件需排除，强token/private-key模式未命中；不宣称通用秘密扫描认证。

```bash
cd /workspace/reports
sha256sum -c work-state-short-runtime-canary-r1-20260909.tar.gz.sha256
```

旧四族课程与旧失败证据不修改。本次仅证明WS07合同在固定runtime上可解、零分与拒绝边界正确；真实学生在线RL、非零梯度/参数更新和独立reload另由训练结果验收。
