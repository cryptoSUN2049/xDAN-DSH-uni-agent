# 记忆与上下文技能专题：视觉检查

2026-09-09，gstack browse 实际打开同名本地 HTML；未启动模型或修改 Markdown 规范。

- 1440×1000：document.scrollWidth=1440；390×844：document.scrollWidth=390。无页面横向溢出。
- 内部导航缺失锚点 0；实际点击“八个任务族”到 #s6；所有本地文档链接存在。
- 浏览器 console 无消息；无外部脚本依赖。
- 已人工查看完整桌面/手机截图、手机首屏与任务卡片：标题、状态区、导航与正文可读，卡片在手机变单列，无裁切。
- 首页明确标为设计；r1失败/r2 val385秒通过/train-r2失败待核是首版时的状态快照（下方复核已更正），不宣称RL通过。总方案 v3 新增入口并修正同一旧状态。

截图（本机临时证据）：

- `/tmp/dsh-memory-skills-desktop.png`
- `/tmp/dsh-memory-skills-mobile.png`
- `/tmp/dsh-memory-skills-mobile-top.png`
- `/tmp/dsh-memory-skills-mobile-tasks.png`
- `/tmp/dsh-memory-skills-desktop-tasks.png`

视觉验收不等于真实 compact 工具、训练、能力或独立 reload 验收。

## 完整规格导读复核

根规范扩为16节后，HTML仍保留概览，新增第11—16节导读及本页锚点；所有入口打开完整MD，不依赖浏览器Markdown锚点。明确WS01—WS12、数据schema、候选reward和实施验收均是设计。train-r2更新为initial val的A同轮读写产生错误事实而被质量门拒绝，无B/n4/更新/checkpoint；v3同步。

实际gstack复核1440/390两种宽度均无页面溢出、缺失锚点0、console空，所有本地链接存在。已实看新增手机导读截图 `/tmp/dsh-memory-skills-spec-mobile.png`，导航换行、卡片与文字无裁切。未修改完整MD或源码。

## 首批实现状态更新复核

2026-09-09。仅更新专题HTML/对应MD与本报告；保留既有布局与能力退出条件。首页现列核心6085a13、recipe/audit8010835、229 Python+6 Node与31 recipe/audit回归、Linux 8结构/106真实工具请求通过。GPU状态明确限定12:13:55 UTC+8快照，学生运行中，W2未完成、无已验收训练更新、能力门未通过。旧memory train-r2失败不覆盖。

- gstack browse实际打开本地HTML：1440×1000和390×844，document.scrollWidth分别1440/390，无页面横向溢出。
- 内部锚点无缺失；实际点击“八个任务族”到#s6。
- 25个本地文档链接均存在；参数审计实际文件为`work-state-parameter-audit-plan.md`，已使用真实路径；新RL手册入口可达。
- 浏览器console无错误。浏览器daemon首次检查短暂busy，后续命令正常；未强制重启或清除其他会话状态。
- 已查看桌面与手机首屏截图，状态正文、长run名自动换行，链接未裁切；不改视觉设计。

本机临时截图：`/tmp/dsh-memory-skills-status-desktop.png`、`/tmp/dsh-memory-skills-status-mobile.png`（全页）；`/tmp/dsh-memory-skills-status-desktop-top.png`、`/tmp/dsh-memory-skills-status-mobile-top.png`（实际视口）。视觉检查不代表GPU任务已通过。

状态后续更正：移除首页短时GPU占用数值，改为稳定的“GPU基线已启动、尚未通过”。WS01首A真实只读来源写入越权失败与正常completed并列，未误记max-token故障；链接handoff跟踪最新结果，W2仍未完成。
