# 固定 Linux DSH RSI 策略 canary：通过

本轮只运行 CPU SDK/tool runtime，没有模型请求、训练或GPU操作。
公开完整报告：`native-rsi-policy-linux-c5acd30-r1.json`。
远程产物：`/root/runs/dsh-rsi-policy-linux-c5acd30-r1`。

## 固定身份与隔离

- 独立detached checkout `/workspace/rebuild/uni-agent-rsi-canary-c5acd30`，
  `c5acd309509f1e763f5b955e203815727166f370`。
- 独立VERL worktree位于上述checkout/verl，
  `fefb080262e1c015a0ea05f958822a6a512dc795`。
- 两者复用现有Git对象；旧验收venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5`，没有新建或修改环境。
- SDK/runtime版本均 `0.1.3a2`，固定二进制SHA：
  `sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- writer checkout仍为 `22265e16e7e816100e884dfbf2bb9dd97c5544b1`，事后tracked diff为空。
  只更新Git fetch引用并添加独立worktree，没有checkout/reset/pull writer工作文件。

## 实际执行

cwd为独立checkout。命令等价如下（r1已存在，复跑必须换新输出目录）：

```bash
CUDA_VISIBLE_DEVICES='' \
DSH_RUNTIME_MODE=exe \
PYTHONPATH=/workspace/rebuild/uni-agent-rsi-canary-c5acd30:/workspace/rebuild/uni-agent-rsi-canary-c5acd30/verl \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m deployment.checks.dsh_rsi_policy_canary \
  --output /root/runs/dsh-rsi-policy-linux-c5acd30-r1
```

未使用--exe绕过固定发布物检查。进程级CUDA_VISIBLE_DEVICES为空，不改持久环境。
实际4.664秒、exit0；passed=true、fixed_runtime_verified=true。

## 真实证据与边界

三次独立Python读取持久选择，三个独立SDK/runtime阶段，每阶段6次真实工具请求，共18次。

| 行为 | 父候选 | 新候选 | 回滚父候选 |
|---|---|---|---|
| 固定公开文件view | 成功 | 成功 | 成功 |
| cordis_inspect_list | 策略拒绝 | 成功，返回provider信息 | 策略拒绝 |
| 私有文件view/公开文件write/cordis_define | 明确策略拒绝 | 明确策略拒绝 | 明确策略拒绝 |
| shell | 未注册，请求失败 | 未注册，请求失败 | 未注册，请求失败 |

实际全局inventory三阶段相同；这是执行权限变化，不伪称工具目录过滤。固定公开内容未被改写，
秘密泄漏检测全为false。报告绑定candidate/active/policy/patch/probe/read-file摘要与真实结果摘要。

Registry晋升比较使用独立canary身份的synthetic选择合同；它用于验证晋升/回滚持久选择与overlay
接线，不是学生开发集评估，不生成生产训练fresh receipt。报告明确：
`training=false`、`model_evaluation=false`、`synthetic_selection_comparison=true`。

因此本轮新增的验收是“固定Linux发布物上，候选选择确实改变工具执行策略且回滚恢复”。
真实学生提出候选、独立开发评估、生产晋升和RL训练仍须后续独立完成。
