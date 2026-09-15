# Tinker 训练系统 HTML 文档设计

2026-09-15。当前任务是生成可审阅的系统方案，不执行付费训练或新增云部署。

## 目标
将已有 Tinker + Harbor + Modal 的代码、技能与 SDK 契约整理为初学者可读、工程师可执行的离线 HTML。明确四个目标：工程闭环、评分可信、泛化提升、公平对照 Opus 4.6。

## 页面架构
概览 → 4个核心目标 → 服务架构图 → 8步训练流程 → OPD/RL/hybrid 模式交互 → token/API契约 → 数据和评测 → 分阶段实施 → 启动命令 → 云部署和运行治理 → 验收矩阵 → 来源。
单文件 HTML，内嵌 CSS/JS/SVG，无 CDN。侧栏导航、训练模式切换、步骤展开、打印。显示方案与已实现状态，交互不伪造实测状态。

## 文件改动
- docs/tinker-harbor-opd-rl/system-plan.html：主要交付。
- docs/tinker-harbor-opd-rl/system-plan-spec.md：本设计。
- tasks/todo.md：任务进度。
- tasks/tinker-harbor-opd-rl/handoff.md、memory.md：本轮结果与入口。

## 技术内容契约
以 Cookbook upstream 485726f、实现 f96cc38、安装 tinker 0.29.0 为本地事实；当前官方文档用 Context7 与 browse 交叉核验。异步 SDK 的直接值和 APIFuture 分开写。单样本 KL 可负；全词表精确 KL 不属本实现。严格 mask/shift/固定 token scoring 是未来云端验收项。

## 验证
HTML 结构、内部链接、无密钥、桌面和手机无正文溢出；browse 实际渲染、切换3种模式、展开步骤、console 检查、截图。现有训练测试记录单列为历史证据，不追认为本轮云端验证。文档完成后本地提交，保留 worktree。
