# 固定版本一致性审计 · 2026-09-13

审计对象是当前 `worktree-harbor-modal-integration` HEAD `cb0cdc58b04f481dc0e73f586206b27b0c86db87`。结果：当前部署合同内部一致；仓库中的旧版本字符串只属于历史报告，不得作为当前安装依据。

| 组件 | 当前有效 pin | 权威来源 |
|---|---|---|
| DSH source | `b2369692ea530007075ebcd18d39fdba0bbd3982` | `deployment/versions/g1-deployment-lock.json` |
| DSH SDK/runtime | `0.1.3a2` | deployment lock 与 runtime SHA |
| VERL | `fefb080262e1c015a0ea05f958822a6a512dc795` | deployment lock + source overlay manifest |
| Student | Qwen3-4B revision `1cfa9a7208912126459214e8b04321603b3df60c` | deployment lock |
| Harbor image | `sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97` | deployment lock |
| Integration code | `cb0cdc58b04f481dc0e73f586206b27b0c86db87` | Git HEAD at audit time |

自动核验通过：DSH 版本/source、VERL revision、模型 revision 均与部署清单匹配；source lock 可解析；工作区无未提交文件。此前文档中出现的 DSH `0.1.2`、旧 source SHA 或旧 checkout 是历史运行证据，不能用于新的 GPU 作业。

本审计只检查声明与文件之间的一致性，不证明远程服务器上已安装这些版本，也不证明 CUDA、vLLM、DSH runtime 或训练更新成功。新服务器恢复后仍须运行 bootstrap 安装检查、实际 runtime identity probe、GPU canary、RL 消费/参数审计和独立 reload。
