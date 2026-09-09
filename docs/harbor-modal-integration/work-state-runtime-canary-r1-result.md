# Work-state Linux runtime canary r1

2026-09-09，真实服务器 `/root/runs/work-state-runtime-canary-r1/result.json`，**passed=true**。源码 `/workspace/rebuild/uni-agent-work-state-canary-r1`，提交 `6085a13`；固定VERL fefb080、DSH SDK/runtime 0.1.3a2，未安装新环境。

- 四族WS01/03/05/06，各variant0/1，共8种结构变体、106次真实DSH工具请求。
- 每种结构实际A文件写入→原字节bundle冻结→B新runtime读取→实际config/plan文件业务评分均为1。
- 实测允许尚不存在目标的view进入正常工具错误，拒绝修改只读来源/索引与读取A私有路径；拒绝不泄露secret文本。
- 冻结工件与B展开后再次pack字节一致；缺失索引保持缺失（WS06），不由控制器补写。
- runtime SHA256：`d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- 原始result.json SHA256：`800b297cb3334bf39b3a4bc5d2c8a08eeb84e148022abe15d4a2fd1c851f4f58`。

范围：控制器oracle脚本、真实SDK工具、文件与业务检查；无模型推理，无在线token，不产生学生RL回执，不证明模型能力。GPU学生另用 `801083579318ed5268cc92caf45c3ce04ef6d099` 的独立checkout和run；两提交间相关任务/runtime canary代码未变，仅新增recipe/消费审计/指南。

本地核心回归229项Python+6项Node通过；recipe与新消费audit主线程组合31项通过。旧Ray弃用警告保留，不算业务失败。详见 [人工复跑指南](work-state-rl-runbook.md)。
