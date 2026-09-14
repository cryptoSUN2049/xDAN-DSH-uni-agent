# 固定版本与实验追踪

`g1-deployment-lock.json` 是 G1 训练部署的唯一可执行版本事实源。任何训练、诊断或 Harbor 任务都必须从该文件读取版本，并把实际解析后的值复制到 run manifest；README、聊天记录和旧报告不能覆盖锁文件。

## 必须绑定的身份

- DSH：release、source revision、SDK/runtime wheel SHA-256。
- Uni-Agent：仓库、分支和 commit。
- VERL：仓库 commit、source overlay manifest 和 overlay SHA-256。
- 模型：名称、revision 和本地文件清单摘要。
- 数据：train/holdout 文件 digest、数据 manifest、split 和 verifier digest。
- Harbor：版本、平台、镜像 digest、执行 manifest。
- 环境：Python、CUDA、PyTorch、`uv.lock` digest 及启动配置摘要。

## 运行前后规则

1. `prepare` 阶段校验锁文件、源码和工件；缺失或不一致时拒绝启动。
2. `run-manifest.json` 记录锁文件版本、实际 import/source 身份、数据和配置摘要。
3. 版本号相同但 source revision 不同，视为不同运行环境；必须重新构建/核验 wheel，不能沿用旧证据。
4. DSH、Uni-Agent、VERL 或 verifier 发生漂移时，旧 run 只能作为历史实验，不能追认当前基线。
5. 升级顺序为：更新候选锁 → 构建 Linux 工件 → 启动/退出 smoke → fresh canary → 训练与 reload 审计 → 提交锁和报告。

## 当前迁移提示

用户已指定 DSH 正式基线为 `0.1.3-alpha.2` / `c389f96bf3`。在该 revision 的 Linux runtime/SDK 工件完成 digest 核验并更新 `g1-deployment-lock.json` 前，当前锁中的旧 revision 只能用于历史候选 run，不得用于正式 G1 验收。
