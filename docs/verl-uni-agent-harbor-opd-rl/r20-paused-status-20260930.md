# R20 暂停交接（2026-09-30）

用户明确“现在账户没钱了 暂停”。已停止本会话持续监测和后续云端推进；不恢复或新建 GPU，不执行备用校准。旧 R19 Code 工程目标已经完成，当前 R20 扩展暂停，不改变旧目标验收结论。

## 最后实际训练证据

- 新run `mimo9b-002549-r20e`：原生两rank成功从R19 C4加载model/optimizer/RNG/scheduler，进度4/5。
- 当前采样17个完整backend events均policy4；前两条completed并独立评分0，后两条最后读到running。
- 四条实际trainer消费、step5有效更新、C5和最终token/checkpoint/Insight联合验收未证实。
- 07:54 UTC 新的只读W&B GraphQL返回`crashed`、history0；配置仍为两卡、resumeC4、target5。没有补写任何history或finish。

## 连接与账户

SSH在认证之前断开。Runpod MCP和现有CLI查询Pod `db7kewdkd71js6`均404；MCP当前账户Pod列表0。CLI账户余额实际为`-$0.5895114386`、全账户currentSpendPerHr为`$0.347`；后者不是训练GPU费率。用户随后明确账户无余额并要求暂停。本会话没有调用Pod停止/删除。

不能把W&B crashed或Pod404当作原生exit0、已保存C5或完成所有Modal回收的证明。当前无法向原生进程发送停止信号；owned Modal终态、云端checkpoint存储和R20 SSH授权项尚未复核。

## 恢复顺序

1. 确认补充余额后的实际账户、Pod与存储；不自动重建付费资源。
2. 在可访问服务器上核C4/C5实物、15文件SHA和完整marker；不假定旧磁盘还在，也不把未验C5当有效parent。
3. 先核所属Modal资源及scoped R20 key/端口，再恢复新身份的训练。
4. 重新明确预算与固定截止；原1790759992窗口不重计、不默认为续期。
5. 后续真实消费/有效更新/W&B/Insight验收仍待完成；五域状态仍仅Code001661闭环已验收。

证据：[暂停状态](evidence/r20-user-paused-status-20260930.json)、[断连后的真实W&B API](evidence/r20e-wandb-after-ssh-loss-20260930.json)。
