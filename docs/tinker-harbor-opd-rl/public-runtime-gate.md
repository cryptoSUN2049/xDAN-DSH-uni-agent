# 公开任务运行验收：实施细化

目标：落实已批准的数据接入方案，先消除工作目录/公开文件错配，再运行有界环境验收。不是扩量训练许可或能力提升结论。

```mermaid
flowchart LR
  A[固定原始候选] --> B[审计后的运行配置]
  B --> C[独立沙箱初始化]
  C --> D[工具执行与 verifier]
  D --> E[负例和参考解验证]
  E --> F[小批 Student / Teacher 筛查]
  F --> G[新鲜 rollout 联合更新]
```

## 文件与接口

- 新增 `harbor_runtime.py`：从 task.config 顶层 `harbor_runtime` 显式读取 `workdir` 和 `public_setup_files`。默认 `/`、false，旧题行为不变。
- workdir 必须为规范绝对路径；公开上传仅允许 task/setup_files 中常规文件，无链接、路径越界，单文件24MiB、合计80MiB。仅显式 true 上传，禁止整任务目录上传。
- `harbor_env.py` 与 `harbor_smoke.audit_task` 共享初始化函数；工具实际 cwd、oracle cwd 与配置一致。初始化失败不得启动模型 rollout，沙箱仍清理。
- `HarborBashTool` 增加默认 `/` 的 workdir 参数；资源日志记录同一配置，避免记录与执行不同。
- 原始六题不覆盖；适配配置/参考解放独立派生目录，并保留原始哈希和新增文件来源。

## 验证计划与停机条件

- 单元/回归覆盖默认旧行为、显式 /app、公开文件允许列表、链接拒绝、上传失败、实际工具 cwd、audit 初始化及清理。
- 公开题原始测试不修改以迁就解法。依赖安装失败、pytest internal/usage/no-tests 错误不能当作普通 reward=0。collection 错误须按来源判断：缺少 Student 应实现的 /app 模块或其语法错误可为模型失败；承诺依赖缺失、测试自身错误或中断须隔离。先证明该题 verifier 可诊断再准入。
- 先做 nop/参考解环境验收，无 Tinker 请求；失败保留证据并停止依赖的训练阶段。
- 云端运行与本地 fake 测试分别记账。当前仍未取得真实非零 RL+OPD 联合更新证据。
