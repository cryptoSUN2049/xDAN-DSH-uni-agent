# DSH 0.1.3-alpha.2 Linux 发布物验收

2026-09-08，RTX Pro 6000 所在 Linux x86_64 主机。此处只声明发布物可运行；不声明新版本训练已经验收。

## 固定输入

- DSH 源码：`b2369692ea530007075ebcd18d39fdba0bbd3982`，来自已发布的私有 `cryptoSUN2049/xDAN-DSH-Exp`。
- 集成构建/打包脚本：`1263ff59bfd06a36bf99122694de0df5869370ba`，经 GitHub 获取。
- Node `24.20.0`、pnpm `11.7.0`；目标 `node24-linux-x64`。
- 使用官方 `scripts/build-python-release.py` 生成版本化 wheel；没有直接发布带占位版本的源码包。

## 结果

| 节点 | 结果 | 证据位置（GPU 主机） |
| --- | --- | --- |
| 首轮编译前依赖安装 | 失败：网络盘 node-gyp headers 解压 fchown EPERM | `/workspace/reports/dsh-g1-v2-build.log` |
| 使用固定 Node 自带 headers 后完整构建 | exit 0 | `/workspace/reports/dsh-g1-v2-build-r2.log` 和 `.exit` |
| 官方 SDK/runtime wheel 打包 | exit 0 | `/workspace/reports/dsh-g1-v2-package.log` |
| 独立 wheel 安装 | SDK/runtime 均 0.1.3a2 | `/workspace/venvs/dsh-g1-v2-b236969-sdk` |
| 官方 sdk-minimal installed-wheel | passed | `/workspace/reports/dsh-g1-v2-b236969-sdk/minimal.log` |
| 官方 sdk-restart installed-wheel | passed | `/workspace/reports/dsh-g1-v2-b236969-sdk/restart.log` |

运行测试时离开源码 checkout，清除 PYTHONPATH、DSH_RUNTIME_MODE 及代理变量。解释器 Python 3.12.3，Pydantic 2.12.5。模型为官方测试中的本地模拟服务；没有 GPU 参数更新。

产物目录 `/workspace/artifacts/dsh-g1-v2-b236969` 含两只 wheel、`build-info.json` 和 `SHA256SUMS`。固定摘要见 `deployment/versions/dsh-session-v2-candidate.json`；runtime binary SHA256 为 `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。

## 继续验收

1. Harbor 使用这些实际 wheel 重建镜像，记录真实 image ID 并运行 boot/setup。
2. 将任务版本与镜像摘要一起更新；旧实验记录保留旧摘要。
3. 经真实 Gateway 学生采样，独立 verifier 回执与 token 对齐后进入 VERL。
4. 非零数值更新、独立 reload、留出评估，以及从固定源码和发布物重复部署。

源代码已发布、安装包已构建、Harbor 已升级、训练已验收是四个不同状态，不能互相替代。
