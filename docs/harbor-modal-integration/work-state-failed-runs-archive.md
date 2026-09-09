# Work-state失败运行：最小脱敏报告归档

已保存到网络云盘 `/workspace/reports/work-state-failed-runs-minimal-20260909-r1.tar.gz`，42,696字节、32成员（31份证据/清单加归档manifest）。SHA256：`83b0d52c27c233ed51a07baaa038162bc19eecd44cacef787e872b5be19edfb1`。归档逐成员回读与写入内容一致，文件权限0600；旁边保存同名`.tar.gz.manifest.json`。

完整成员、每个原文件SHA与归档副本SHA、删除字段路径及限制见 [归档JSON](work-state-failed-runs-archive.json)。原 `/root/runs` 文件保持原样，没有移动、删除或修改。未操作GPU、未改运行中r3源码。

## 收录范围

- `work-state-val-r1`：失败结果、消费审计、运行/部署身份、supervisor结果、数据manifest与任务清单、已存在crosswalk。
- `work-state-train-r2`：原generation-boundaries-audit、supervisor结果、运行/部署身份、数据manifest与任务清单、11个crosswalk以及原metrics JSONL。保留passed=false与已消费/未证实消费的区别。
- `dsh-finish-reason-canary-r1/result.json`：固定Linux runtime四case报告；只收报告，不收session homes或原事件。
- `work-state-r3-linux-checks/{pytest.log,junit.xml,result.json}`：30项Linux测试证据；pytest.log原SHA `75ac1492ebe9b287bb711cbbdf460f25cef45ff1e182a9c233ee3ba471c151ca` 与既有记录一致。

## 脱敏与边界

采用文件白名单；预检常见PAT/API key/Bearer/private key/URL内嵌密码模式，仅允许输出命中文件路径，未打印值。本次31个候选无模式命中。仍主动删除JSON内environment/env/command/argv及敏感credential/provider配置字段，7份manifest/报告用`.sanitized.json`成员名保存；记录原SHA与脱敏后SHA，不称原字节副本。启发式扫描不能保证识别一切未知凭据，因此不以全目录打包替代白名单。

明确排除homes、provider配置、凭据、raw DSH traces/events、NPZ token数组、Parquet、模型权重、checkpoint、完整训练日志和源码。整个tar不包含授权token或shell环境快照；跨节点重新部署仍应从固定仓库版本与原部署方案操作。

这是**最小报告留存，不是完整portable证据或全量复现交付**。仅凭此归档不能重跑原始consumption/token审计，也不能重新训练；原大体积/原轨迹证据仍在原位置。报告SHA可以校验之后找回的原文件，不能替代缺失文件。canary的模拟HTTP结论、历史零梯度和安全拒绝均未改变，不追认有效学习或完整八步通过。
