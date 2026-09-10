# Core r4：母训练工程证据持久归档

完成时间：2026-09-10 07:31:07 UTC。原执行checkout `/workspace/rebuild/uni-agent-core-511bd71`；母run已终态。此归档不包含正在进行的独立reload，也不声称参数/reload报告已归档。

## 归档与校验

- 归档：`/workspace/reports/core-train-r4-engineering-evidence-20260910.tar.gz`
- SHA256：`0a0f6826ae28fe2bd40a448e89055ae921f601b2f6c2c39d5cb5d142cffff54c`
- 压缩大小：**49,014,953 bytes**。
- **338,899个源文件、184,603,866未压缩bytes**；另含 `archive-members.jsonl` 与 `archive-manifest.json`，共338,901个逻辑tar成员。
- 所有源成员逐项回读核名称、大小、内容SHA256；再次读取原文件核相同hash，确认归档期间源内容未变。两个内嵌清单与外部清单hash相同，末尾没有额外成员。
- 开始时目标不存在，采用exclusive创建，没有覆盖既有归档。

下列外部文件均位于 `/workspace/reports/`：

| 文件 | SHA256 |
|---|---|
| `core-train-r4-engineering-evidence-20260910.manifest.json` | `b3ce6fe449fac6bad6db752788ccfb472b9567987245d243014e817bed884c3c` |
| `core-train-r4-engineering-evidence-20260910.members.jsonl` | `f34037086aeb70a9f67feceb324080e0cbde2af05fcc47f850de9e61560b7228` |
| `core-train-r4-engineering-evidence-20260910.verification.json` | `658e690e6c492c33db7cd69922bd18587f092d3c5007ed38f5e27da04f3efc08` |

## 范围

| 原始位置 | tar内路径 | 内容 |
|---|---|---|
| `/root/runs/core-train-r4/` | `core-train-r4/` | 母run manifest、监督日志/终态、A/B fixture、trace、receipt、冻结memory、轨迹JSON/NPZ、消费dump/crosswalk及被拒尝试 |
| `/root/runs/core-train-r4-data/` | `core-train-r4-data/` | 准备manifest、配方、controller资产/可见输入、train/validation parquet、task.yaml；排除training.env |
| `/workspace/rebuild/uni-agent-core-511bd71/dsh-work-state/core-train-r4.jsonl` | `metrics/core-train-r4.jsonl` | 原checkout的母训练metrics快照 |
| `/workspace/reports/core-train-r4-final/consumption.json` | `final/consumption.json` | 原511正式消费审计 |
| `/workspace/reports/core-train-r4-final/coverage.json` | `final/coverage.json` | 16任务/消费/10拒绝组统计 |

逐成员清单保留原路径、tar路径、原内容SHA256和大小。controller truth仍是控制器资产，不得作为actor输入或训练示范。

## 排除项与运行边界

- `core-train-r4-data/training.env` 按名称排除，未读取；SSH key、系统认证文件、模型provider凭据目录不在所选归档根范围。
- checkpoint/model权重不入tar。checkpoint独立持久位置 `/workspace/uni-agent-g1/checkpoint/core-train-r4/`；本tar不是可独立加载模型的完整备份。
- 所有reload run/data目录排除。final报告只取consumption/coverage两个固定文件，不含后续参数或reload报告，即使它们在归档期间生成也不自动纳入。
- 不包含源码checkout、venv或外层shell环境快照；重建环境使用固定源码和部署锁。
- 全部选中源文件检查常见PAT/HF/OpenAI/private-key及URL内嵌凭据模式，未触发；已知环境/credential文件名先排除。模式扫描不能保证识别所有未知格式秘密；本次未读取系统密钥或打包凭据目录。
- 禁CUDA，CPU线程环境限制1，nice=10，gzip level1；流式tar/hash并清理成员缓存，不将整包读入内存。没有停止/修改reload或源文件。
- 实际权限复核：脚本调用chmod0600后，云盘stat仍返回归档、两个外部清单、verification均**0666**；因此不声称文件权限已收紧。tar内部每个成员mode设为0600。访问控制仍取决于所挂载volume/主机权限，不能把chmod调用成功等同已生效。

首次只读验证入口误将TarFile当迭代器，报TypeError；归档写入已完成且没有重写。随后改用TarFile.next()完整重验338,901成员通过，verification记录为最终结果。源证据和归档字节均未因该脚本错误而改变。

## 限制

正式消费通过与16步全零的原始证据均保存，失败/拒绝尝试未删除。归档成功不等于有效学习、能力提升或独立reload完成。参数变化及reload须各自验收并另行归档，不能追认为已包含在本tar。
