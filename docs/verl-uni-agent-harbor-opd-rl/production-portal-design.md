# 科学训练产线独立入口设计

2026-09-24。用户已批准“独立文档、复用MiMo版式、整合既有方案”的实施。范围为文档与HTML入口，不包含启动训练或部署新infra。

## 目标与架构

新入口 training-production.html → 产线模块/数据合同/组件选型/状态/验收 → 当前总纲与pilot → 原始运行证据。MiMo原报告作为研究依据，不修改、不将其公开机制冒充本项目实现。architecture.html保留历史内容并引导到新入口。

## 文件范围

- 新建training-production.html：独立静态页面，左侧产线架构/阶段目标两个主导航视图，研究依据为辅助入口，目录搜索、状态标签、打印、响应式。
- 更新architecture.html、project-index.md、training-production-charter.md、training-pilot-1k-plan.md、training-system-v2-design.md：统一入口链接，保留原详细合同。
- 更新tasks/todo.md、worktree handoff与项目记忆：完成状态及冷启动入口。

## 页面合同

HTML独立运行，无CDN依赖、无网络数据自动加载；锚点稳定、来源保留外链。页面状态为2026-09-24文档快照，不显示伪实时GPU/进度。组件候选、已验证机制、待建设分别标记。OPD与SFT数据接口分离，RL有效组在纯OPD标N/A。

## 验证

浏览器桌面/移动端：导航切换、目录过滤、锚点定位、无横向溢出、无JS错误。静态检查唯一ID/全部本地链接；核对计划配额与现有验收边界。提交前review，push前ruff双门。原报告hash前后不变。

用户进一步确认：架构与阶段性专项并重。专项包含OPD、MOPD、Verifier、Curator、观测分析infra、MiMo大规模RL机制。每项须有依赖、当前证据、交付物和验收，不把方法调研或组件安装视为完成。
