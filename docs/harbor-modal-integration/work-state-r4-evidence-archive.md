# r4工程证据云盘归档

2026-09-09。母训练、原reload、selected-r1均退出，selected最终审计完成后归档。归档通过只代表证据持久化，不改变实验结论：母训练8步exit0/零梯度；原reload失败；selected-r1 exit1，WS05 max-tokens，2组/0实际消费，母checkpoint 11文件未变。完整验收仍未完成。

- 归档：`/workspace/reports/work-state-r4-engineering-evidence-20260909-r1.tar.gz`
- SHA256：`1d19e4f757a8d9df8610a9f3e3f6d52957a5ac3ea141c06ef85f2bee13b86093`
- 大小：18,128,085 bytes；源文件88,467,308 bytes。
- 逐成员清单：同目录`work-state-r4-engineering-evidence-20260909-r1.manifest.json`，同时置于归档根`archive-manifest.json`。
- 清单SHA256：`e0e2ab2b94e8a856298193e1d4f41e064a1a0f56023bac63a09e2eb6d2accf84`。
- 验证结果：[机器可读报告](work-state-r4-evidence-archive.json)，远端同前缀`.verification.json`及`.tar.gz.sha256`。

## 精确范围与验证

仅扫描`/root/runs`下白名单：`work-state-train-r4`、`work-state-train-r4-reload`、`work-state-r4-reload-selected-r1`三run及对应`-data`；它们现有launch JSON/log与preflight JSON；`work-state-eval-selection-cpu-r1`的result.json、pytest.log、junit.xml。selected preflight在launch内部完成，没有臆造独立文件。

原trace、NPZ、fixture、receipt、数据parquet、冻结库存、消费记录、metrics及最终audit全部保留。168,670个源文件逐成员记录相对路径、原路径、字节数与SHA；归档写入前再次核源hash，归档完成后逐成员解压读取、核字节数/SHA和精确成员集合，全部通过。总成员数168,671，额外1个是归档清单。原run没有改写或删除。

三份`-data/training.env`整份排除且未读取内容；排除路径在清单与验证报告中。只对其余白名单文件执行强token/private-key模式检测，未命中；这不是通用秘密检测器的安全认证。未遍历/root家目录、SSH/git配置或凭据。没有复制checkpoint大文件（已在/workspace）或checkout源码（已GitHub）。复建环境文件须从固定源码/manifest重新prepare，不能把本归档描述为包含私有运行环境的全盘镜像。

## 手动复核

```bash
cd /workspace/reports
sha256sum -c work-state-r4-engineering-evidence-20260909-r1.tar.gz.sha256
```

逐成员manifest存于云盘及归档中，后续消费重验仍须恢复原路径语义或显式映射，使用固定源码与checkpoint，不能更改原回执身份。

结果边界：[母训练报告](work-state-train-r4-result.md) · [原reload报告](work-state-train-r4-reload-result.md) · [selected最终报告](selected-r1-result.md)。
