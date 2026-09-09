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
