# RSI 候选 → 固定 DSH 执行策略 canary

主线程已批准CPU实现，不改远端正在运行checkout；固定Linux runtime实测由commit后主线程执行。
新增examples/dsh/rsi_closed/{policy.mjs,policy.test.mjs,profile.py,probe.mjs}、deployment/checks/
dsh_rsi_policy_canary.py及对应pytest。复用现Registry和memory_closed受控工具策略思路。

候选执行支持子集：仅str_replace_editor（operator普通文件完整只读view）、cordis_inspect_list。
父允许view，候选允许view+inspect_list；拒绝其他Registry可表达工具。本轮不支持任意patch/code/
命令或学生提供路径。operator固定加载Cordis工具组件，禁用shell；policy源码hash固定，渲染器核验
Registry加载结果的candidate/content/active身份并把hash写入策略配置与报告。

固定DSH b236 tools.guard返回理由即单调deny，pre-execute也执行相同判断；无允许结果覆盖deny。
不使用需要agent.ctx的tools.restrict伪造global过滤。实际global inventory如实记录，预期三阶段相同；
调用权限需真实表现为inspect_list deny→allow→deny，固定文件view始终成功，写/shell/define始终失败。

canary每stage先新Python进程load registry active，再启动独立SDK/runtime，无模型，base_url仅
127.0.0.1:1、显式unused凭据。operator probe直接请求真实tools.execute；报告分开记录真实SDK动作
与synthetic registry选择比较。probe只用于canary，不加入真实学生profile。

允许synthetic选择合同仅为测试registry晋升/回滚与overlay接线：独立canary-run身份、独立synthetic
devset pins、synthetic-selection-only目录。报告training=false、model_evaluation=false，
synthetic_selection_comparison=true；该比较不代表DSH学生fresh receipt，不授权生产学生晋升。
真实学生晋升仍必须通过控制端认证的独立开发评估。

安全：本地私有目录0700/文件0600，不放宽MFS。工具策略是受控环境内限制，不是OS沙盒；
不允许不可信插件/同用户并发写者。结果记录isError/deny/期望文本/秘密泄漏布尔及hash，不输出秘密。
测试先覆盖真实JS策略正负例、子集拒绝、hash篡改、文件路径/链接/权限、probe不入学生profile。
Linux canary要求SDK/runtime0.1.3a2及指定固定exe SHA；Mac可显式--exe诊断但报告fixed_runtime_verified=false。

## 实现与验证结果

- 新增 renderer 从真实 Registry.load_active 取选择，不接收学生伪造的loaded对象。
  固定policy SHA，拒绝代码工具子集与文件软硬链接；读取文件摘要进入render与canary报告。
- Node真实ESM策略测试2组；pytest含renderer6项、Registry27项、memory37项，共70项通过。
- Mac真实SDK r1/r2均通过；最终r2三次独立Python加载+三次独立SDK/runtime，各6次工具请求，
  共18次真实调用，无模型请求。inspect_list明确deny→allow→deny；文件read始终成功，秘密read/
  文件write/cordis_define均显式RSI_POLICY_DENIED，shell未注册且请求失败。实际全局inventory相同。
- 公开证据：native-rsi-policy-mac-canary-r2.json。私有完整产物：
  /private/tmp/dsh-rsi-policy-canary-r2。秘密不写公开报告；报告保留布尔结果与摘要。
- synthetic registry比较在独立synthetic-selection-only目录、独立canary evolution_run_id/
  devset身份；只为测试选取与回滚，不是模型评估或生产fresh receipt。报告明确
  training=false、model_evaluation=false、synthetic_selection_comparison=true。
- Mac使用可变source wrapper /private/tmp/dsh-v2-built-cli-wrapper，fixed_runtime_verified=false；
  这不替代固定Linux轮子验收。未调用GPU，未修改远端checkout。

固定Linux checkout提交后，在已验收venv从repo根执行（不用--exe）：

```bash
PYTHONPATH=.:verl python -m deployment.checks.dsh_rsi_policy_canary \
  --output /tmp/dsh-rsi-policy-canary-NEW_UNIQUE_ID
```

使用真实本地私有目录；源码pin由Git checkout及报告source hash对应，runtime要求
SDK/runtime版本0.1.3a2和Linux二进制sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb。
三个probe必须都通过，最终result.json通过且fixed_runtime_verified=true才算固定发布物证明。
当前学生评估仍待：以真实Agent会话和独立开发cases代替synthetic选择合同，绑定真实overlay与
candidate hash；不能把本canary的18次工具调用当成学生rollout或训练数据。
