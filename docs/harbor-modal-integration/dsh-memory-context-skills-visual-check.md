# 记忆与上下文专题状态同步及视觉检查

2026-09-09。本轮更新短课程 `work-state-short-fact-v1` 的真实训练、参数及独立评估证据；历史r4零更新保持原结论。

- 训练源码b47521d：8步、8个n4组、64唯一A/B行、6独立实例。step2/4非零任务梯度，504个LoRA张量4→8变化、399个base张量不变；5—8步梯度0不称为新任务学习。
- 901/902独立reload均exit0、reward1；d4401d3独立离线审计两题passed，各1组2唯一A/B行；两次after-run确认母checkpoint11文件未变。旧stage_score_mismatch原报告保留，未修改原回执或分数。
- 短课程闭环通过，不等于四能力提升、从零部署或全goal完成。S6文档归档由主线程继续。短课程WS07与长期offload WS07按course_id区分。

## 实际浏览器检查

使用gstack `/browse`，新建独立daemon状态 `/private/tmp/uni-agent-short-visual-20260909/browse.json`，未复用或终止其他会话tab。`load-html`加载本地HTML；截图后逐张人工查看。

| 检查 | 结果 |
| --- | --- |
| 桌面1440×1000 | 标题、状态、证据入口与导航清晰；scrollWidth=1440 |
| 手机390×844 | 标题、状态自动换行，无横向裁切；scrollWidth=390 |
| 手机下一步区域 | 实际滚动s10截图，说明与链接清晰无遮挡 |
| 页内锚点 | brokenAnchors=0 |
| console error/warning | 无 |
| 相对文件链接 | 26处全存在；仅文件存在性，不冒充HTTP跳转验收 |

截图在本地临时目录，未纳入Git：

- `/private/tmp/uni-agent-short-visual-20260909/desktop-1440.png`
- `/private/tmp/uni-agent-short-visual-20260909/mobile-390.png`
- `/private/tmp/uni-agent-short-visual-20260909/mobile-next-390.png`

本次只验证文档呈现；训练结论来自消费、参数与独立reload原始报告，不能由截图替代。页面不追踪实时GPU数值。
