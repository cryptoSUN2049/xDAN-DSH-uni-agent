# N1 封闭记忆工具策略（实施小设计）

目标：在固定 DSH sdk-minimal 的 tools/pre-execute 扩展点拒绝非白名单工具/命令/路径，不新增 Agent Loop、不改 DSH 发布版本。一次进程一个 writer/reader 角色。仅用于控制端独占文件树、无不可信插件/并发写者的封闭任务；不是 OS 沙盒。

文件：examples/dsh/memory_closed/{policy.mjs,probe.mjs}；deployment/checks/dsh_memory_policy_canary.py；Node 原生单元测试。补丁由控制端生成，禁用 persistent-bash/pwsh，不加载 evolution.patch，插入 file: ESM policy。路径限定单个普通文件；拒绝软/硬链接、目录、非规范路径及越界命令。reader 只读 handoff/question；writer 只能编辑指定 output。控制端策略/报告不在白名单中。

接口：role/chainId/sessionId/sourceVersion/readFiles/writeFile 构成策略配置。policy 在注册时验证配置、每次执行再次验证路径；deny 返回固定理由，避免泄漏文件内容或存在性。可写输出只支持 create/str_replace/insert，view 需显式列入 readFiles。配置错误启动失败。固定可信工具集合须实测为 str_replace_editor；其他任意工具即使注册也拒绝。

验证：先 Node 红测试后实现；SDK canary 不运行模型，可信 probe 直接调用真实 ctx.tools.execute。独立 A/B home/cwd，A 写 memory，controller 冻结到 B handoff，B 显式读取 A secret 必拒且结果不含秘密；正常读取交接成功，修改交接/目录/链接/相对路径/工具旁路拒绝。报告仅存布尔检查与版本/文件摘要，不存秘密内容。Mac 可变源码 wrapper 仅开发证据；固定 b236 Linux wheel 由主线程另跑确认。

边界：pre-execute 检查与 fs-local 打开间不是原子句柄操作；不允许不可信并发写者或任意代码工具。一旦开放这些能力，需 fd 绑定 backend 或 OS 隔离，不能复用此验收声明。

## 2026-09-09 实测与复跑

- 已实现源码与overlay生成器：`examples/dsh/memory_closed/policy.mjs` / `profile.py`；operator-only `probe.mjs` 仅用于canary，不放入训练profile。
- Node首次红测试为模块缺失；实现后两组策略测试通过。pytest合并原freeze/load回归共39项通过。全repo Ruff check/format-check通过（284 Python文件）。
- Mac真实SDK r4通过：独立writer/reader runtime、home与cwd；14次真实tool runtime调用（A3+B11），非mock。A创建/读回memory成功且修改输入拒绝；controller freeze+load摘要/新身份验证成功；B读取handoff成功，10个负例全部isError且MEMORY_POLICY_DENIED，无A秘密回显。两边工具目录均只有str_replace_editor。
- 证据：`native-memory-policy-mac-canary-r4.json`；原始私有输出 `/private/tmp/dsh-memory-policy-canary-r4`。r1/r2遇到脚本关键字参数/SDK distribution名称错误，均已修复；r3/r4完整通过，未复用旧输出目录。
- Mac入口是可变source-built wrapper `/private/tmp/dsh-v2-built-cli-wrapper`（指向DSH-Exp apps/cli/lib），不能认作固定b236 Linux发布物证明。报告明确runtime_source_verified_by_this_script=false；Linux wheel身份由部署锁与包哈希门独立验证。
- 本canary controller stage identity用于freeze/load，**没有创建模型Agent会话**，也没有调用模型/训练。后续A/B学生任务仍需SDK session身份与奖励接线。

固定Linux环境复跑（在本仓checkout根目录，激活已验收venv；不加`--exe`）：

```sh
PYTHONPATH=. python -m deployment.checks.dsh_memory_policy_canary --output /tmp/dsh-memory-policy-canary-NEW_UNIQUE_ID
```

目录必须全新、canonical，且文件系统兑现0700/0600；Mac用/private/tmp。网络共享/workspace若权限语义不满足freeze合同，应在独立本地临时目录做CPU canary后归档结果，不能放宽合同。脚本仅SDK启动/直接工具请求/关闭，不访问模型端点。节点stdout只输出最终报告路径。完整runtime版本证据需部署端同时记录锁文件、安装wheel哈希与代码commit。

下一步：Linux固定runtime复验 → 训练入口使用closed overlay且不混入evolution.patch → 真正两个SDK会话A写入/B检索 → controlled/no-memory对照与奖励合同。当前policy拒绝模型工具越界，但不保护同Unix用户运行的恶意插件或并发主机代码。
