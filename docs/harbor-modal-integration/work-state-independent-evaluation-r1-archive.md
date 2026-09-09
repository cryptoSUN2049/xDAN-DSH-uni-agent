# 四题独立评估证据持久化

2026-09-09，suite已终态且报告冻结后归档。仅封存当前suite，不改变3题verified、WS06 max-tokens拒绝及全部实际A/B奖励0的结果。

- 云盘：`/workspace/reports/work-state-independent-evaluation-r1-20260909.tar.gz`
- SHA256：`c584f240d2276eb7e9b81bb0dd9553284ec735b150669ece194bbc8fd3a4ce01`
- 1,508,657 bytes；12,247源成员，另含1份archive-manifest.json。
- 逐成员清单：同目录`work-state-independent-evaluation-r1-20260909.manifest.json`，SHA256 `eb21b52de1c4d0807fbb22ce8572bf47a2966876b69902c02ee507157b717e31`。
- 所有成员回读字节数/SHA/精确集合核对通过，源总大小7,644,475 bytes。[机器验证结果](work-state-independent-evaluation-r1-archive.json)。

范围：`/root/runs/ws-r4-isolated-eval-r1`完整suite、同级launch JSON/log，以及`work-state-singletons-cpu-r1`的result.json/pytest.log/junit.xml。保留全部trace/NPZ/fixture/7份A/B原receipt、原评分与消费audit、metrics、summary及独立run配置清单。

四份training.env排除且未读取；强token/private-key模式扫描未命中其他成员，不宣称通用秘密检测认证。未扫描/root家目录、凭据、SSH/git配置，原run未改，未复制源码、母run或大checkpoint。原[母r4与旧reload归档](work-state-r4-evidence-archive.md)继续独立保留。

```bash
cd /workspace/reports
sha256sum -c work-state-independent-evaluation-r1-20260909.tar.gz.sha256
```

归档通过是持久化验证，不替代[本次结果](work-state-independent-evaluation-r1-result.md)的分层解释或W4有效学习证据。
