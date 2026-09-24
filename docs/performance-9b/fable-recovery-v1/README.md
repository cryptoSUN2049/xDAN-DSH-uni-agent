# Fable原始来源恢复v1

Runpod已完成70文件、501430864字节固定版本收集及大小/可用LFS SHA核验。原版仍在 `/workspace/apus-data-cleaning/recovery/collection-v1/raw/`，此目录仅收回小报告，不保存大原版。

| 来源 | 原始计数 | 教师证据现状 |
|---|---:|---|
| Premium V1 | 6365行（三split合计） | Fable声明591、unknown5705、其他Opus69 |
| Armand | 18370原始事件行、63个JSONL文件 | 7431处Fable声明、59处synthetic；不是7431独立任务 |
| Teich | 244行 | 此次metadata扫描没有model字段；须核发布者声明与原始结构 |

Premium V1 train 5728行中Fable声明526；validation33、test32条Fable不能混入训练。V1的教师标注和V2统一Fable标签不一致。

V2 base_v1的5381行按source_row_hash直连本次固定V1版本，0匹配。不能据此继承原始model/split；后续需检查哈希算法、历史revision和完整内容指纹，不猜造映射。当前无新增训练准入，V2继续隔离。

详见manifest.json、分文件audits、premium-lineage-audit.json。扫描的rows/events与工具/模型字段计数不等于独立任务数或工具完整性验收。

## V2 base_v1内容匹配

将V2 base_v1的5,381行与当前固定PremiumV1三split按规范化完整`messages`内容匹配（不依赖上游`source_row_hash`）后：884行匹配，4,497行未匹配。匹配的884行落在V1 train794/validation47/test43；原始model声明为Fable499、unknown328、Opus-4-6/7/8共57。V1 train中只有444条匹配行声明Fable；其余350条不能继承Fable标签。V1 validation/test即使匹配也不能进入训练。

这是内容与split证据，不是教师身份独立认证；匹配失败可能由历史revision、内容改写或hash/规范化差异造成，不据此断定样本来源不存在。报告：`premium-content-lineage-audit.json`。
