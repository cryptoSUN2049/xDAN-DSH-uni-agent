# G1 HTML 浏览器视觉审计与修复复验

审计日期：2026-09-08。首轮只读检查后，经授权仅修改两页的正文长词换行和当前状态摘要，未改训练代码或 GPU。使用已安装的 gstack `/browse`（已读取 SKILL.md），Chromium 实际打开本地 file URL；无需 HTTP server，未暴露 run 目录。检查时源码 HEAD `8a7f23c8c6e2c530df90f43aaee013883087afa0`，其他会话有在途修改。

## 最终复验结果：F1 / F2 已修复

- F1：两页正文 `p` 增加 `overflow-wrap:anywhere`。路线图在 375×812、390×844、1440×1000 下 document scrollWidth 分别为 375、390、1440；原溢出段落不再超出自身宽度。375px 的 P3.3 操作链已目视确认自然换行。
- F2：两页正文顶部新增当前验收摘要，明确 M1 两步数值参数更新、独立 reload/留出通过；Harbor v2 真实 Docker 四模式通过、学生 RL 进行中未验收；当前 sync 并非 fully async。新增 G1 Goal、验收追踪表、handoff 和手动运行 MD 入口。路线图旧 P1 状态均标为“历史快照”，系统图 bridge 标注改为 Docker 已验证、学生 RL 待验收。
- 两页桌面/移动截图已逐张打开目视检查；未见新碰撞或文字裁切。两页 console 无 error/warning。
- 更新后本地 href：系统规划 32 个、路线图 13 个，文件与 HTML fragment 全部存在。实际点击新增“验收追踪表”成功打开本地 MD；路线图 `#P3` 点击后 target top=24.109px。
- 本次已发现问题均修复并复验通过，不宣称完整 WCAG 审计或 G1 训练验收已完成。

复验截图（已实际打开目视检查）：

- `/private/tmp/g1-plan-fixed-desktop.png`
- `/private/tmp/g1-plan-fixed-mobile.png`
- `/private/tmp/g1-roadmap-fixed-desktop.png`
- `/private/tmp/g1-roadmap-fixed-mobile.png`
- `/private/tmp/g1-roadmap-fixed-mobile-overflow.png`

以下保留首轮发现作为前后对照；其中“只读未修复”为首轮状态，以上述最终复验为准。

## 首轮范围与结论

| 页面 | 桌面 1440×1000 | 移动 390×844 | Console | 本地链接 |
|---|---|---|---|---|
| `uni-agent-system-plan-v2.html` | 标题、侧栏、正文卡片无碰撞；scrollWidth=1440 | 标题合理换行、导航折行为普通顶部导航；scrollWidth=390；宽表格在独立 table-wrap 横向滚动 | 未发现 error/warning | 28 个本地 href 的文件/fragment 全部存在 |
| `task-roadmap.html` | 标题、侧栏、阶段卡片可读；scrollWidth=1440 | 主要内容可读；存在小幅页面横向溢出，见 F1 | 未发现 error/warning | 9 个本地 href 的文件/fragment 全部存在 |

真实点击验证：路线图 `P1 工程贯通` 跳到 `#P1`，平滑滚动结束后 target top=23.625px；系统规划 `03` 跳到 `#architecture`，target top=23.5625px。路线图“系统规划v2”跨页链接成功打开对应文件。DOM 检查两页当前文档的所有 `#` 链接均有目标。链接全量检查为本机文件及 HTML id 存在性检查，不代表外网 URL 或另一台机器可用。

## 真实发现

### F1 · 低优先级：路线图移动端长英文操作链溢出

- 位置：`task-roadmap.html` 的 `#P3.3`，完成证据段落中的 `prepare/collect/validate/train/evaluate/compare`。
- 390px viewport 下 document scrollWidth=392px；375px 下仍为392px，产生17px横向页面溢出。
- 定位测量：该段落 clientWidth=286px、scrollWidth=340px（390px viewport）；不是 table-wrap 的预期局部横向滚动。
- 截图：`/private/tmp/g1-roadmap-mobile-overflow.png`。
- 建议未来只给正文长单词加 `overflow-wrap:anywhere` 或给该操作链添加可换行点。此次按只读范围未修复。

### F2 · 文档状态需要更新，不能作为当前验收仪表板

路线图首屏仍写“P1.1 成对版本同步设计已完成，待按项目 Human Gate 确认后实施”、卡片仍写“P1.3 H0未运行”；系统规划架构图 Harbor bridge 标注“待接”。这些是浏览器实际可见文字，与本会话已完成的版本同步、M1训练/reload以及 Harbor Docker 工程验证不在同一进度点。

页面本身声明 handoff 保存当前实测状态，因此属于静态设计快照陈旧，不是训练失败。建议下一批更新入口状态摘要并直接链接最新 acceptance-tracker/goal；不要把所有运行细节复制到 HTML。截图 `g1-roadmap-desktop.png`、`g1-roadmap-mobile-p1.png`、`g1-plan-mobile-architecture.png` 可复核。

## 截图证据

已实际打开并目视检查以下 PNG：

- `/private/tmp/g1-plan-desktop.png`：系统规划桌面首屏。
- `/private/tmp/g1-plan-mobile.png`：系统规划移动首屏。
- `/private/tmp/g1-plan-mobile-architecture.png`：移动架构图。
- `/private/tmp/g1-roadmap-desktop.png`：路线图桌面首屏。
- `/private/tmp/g1-roadmap-mobile.png`：路线图移动首屏。
- `/private/tmp/g1-roadmap-mobile-p1.png`：移动P1阶段。
- `/private/tmp/g1-roadmap-mobile-overflow.png`：移动P3长词。

截图存于本机临时目录，未提交二进制；可能随系统清理消失。

## 执行限制与工具情况

一个早期 shell 批次的多个 `browse` 命令报告 `/health` busy 并失败；之后相同 daemon 恢复，未强制重启或安装工具，重新执行导航/截图成功。早期未成功批次中使用的 `#p1` 小写测试 selector 与实际 `#P1` 不符，后续已更正并实际点击成功，不将测试拼写错误计为页面缺陷。首次点击立即测量遇到 CSS smooth-scroll 中间态，因此最终坐标取滚动结束后的独立调用。

本次未做全站可访问性、颜色对比或外网链接审计；也未把页面可视化通过解释为 G1 训练验收通过。
