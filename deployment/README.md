# 系统安装与部署入口

本目录负责可复建的环境安装、服务管理与部署前检查。
当前只落地目录约定；安装器、镜像和组合启动器尚未实现，不能据此认为服务已经部署。
设计及验收：[部署设计](../docs/harbor-modal-integration/deployment-design.md)。

## 目录规划（待逐项实现）

| 路径 | 职责 |
| --- | --- |
| `versions/` | Uni-Agent / VERL 配对 revision、Harbor 版本、DSH release 与镜像 digest；区分候选和已验证组合 |
| `bootstrap/` | Linux CPU/GPU 环境安装与安装结果检查；支持重复执行 |
| `docker/` | 经验证的镜像、Compose 与 Harbor 任务环境配置 |
| `services/` | 必要服务的启动、健康检查、状态和限定范围的停止 |
| `checks/` | CPU 预检、服务连通性与最小集成检查 |
| `runpod/` | 复用 Linux 安装流程的 RunPod 配置；付费资源创建另行明确授权 |
| `modal/` | 第三阶段按需增加的环境配置，不是第一阶段依赖 |

不是每个组件都要部署成常驻服务。VERL 执行训练作业，Uni-Agent 组织 Agent loop；
Gateway / 推理端点按运行模式启动；DSH 提供执行能力；Harbor 管理任务环境和验证。
具体进程归属以集成设计和源码为准，避免重复启动框架已经管理的服务。

## 复用已有实验入口

训练与实验生命周期继续由 [examples/dsh/ops](../examples/dsh/ops/README.md) 管理：

- `prepare_qwen3_4b_data.sh`：实验数据准备。
- `launch_qwen3_4b_online_rl.sh`：启动训练。
- `status_qwen3_4b_online_rl.sh`：作业状态。
- `audit_qwen3_4b_online_rl.py`：轨迹及训练消费证据审计。
- `reload_qwen3_4b_checkpoint.sh`：独立加载检查点。
- `teardown_qwen3_4b_online_rl.sh`：实验进程清理。

不复制或搬迁这些入口；部署流程在环境验收后引用它们。停止作业不等于停止云资源计费。
密钥不入库；模型、数据、日志与检查点保存在配置的外部路径。DSH 本体由 DSH-Exp 维护，
这里仅固定并安装其发布物，不维护第二份实现。
