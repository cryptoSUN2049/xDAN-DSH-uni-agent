# T2 真实 runtime 工具生命周期 smoke

性质：scripted-policy integration smoke；本地脚本充当 OpenAI SSE 响应端，真实 DSH SDK/runtime 执行全部工具。不是模型 rollout、训练轨迹、模型能力或 RL 完成证据。

固定合同来源为 DSH b2369692ea530007075ebcd18d39fdba0bbd3982：python/sdk/api.py 的 DeepSeekHarness；scripts/smoke-python-runtime.py 的 SSE tool_calls；tool-cordis/src/index.ts 的工具参数与渲染文本。使用 sdk-minimal 与本项目 evolution.patch.yml。自定义 --exe 明确标 source-built runtime，不能当发行 wheel 证明。

流程：公开 fixture → 空 Plugin/Tool inventory → define 独立 JavaScript 业务工具 → 从真实 define 返回解析 P/Q → run → inspect_self 确认 running → Tool inventory → 全部不同输入 → stop → Tool inventory → undefine → 空 Plugin inventory → completed。Python oracle 与严格生命周期 verifier 独立评判真实 SDK events；脚本不产生或修改这些 events。

新增 deployment/checks/dsh_log_tool_smoke.py、针对测试；不修改 verifier、训练代码或数据。CLI 输入 fixture、输出新目录、可选 exe；输出 requests.json、events.jsonl、report.json，保留 home 持久记录。输出目录必须不存在；loopback HTTP 端口随机且只存在本次运行，SDK 超时有界、context manager 关闭 runtime，finally 关闭 HTTP server。失败不写 passed=true；脚本请求和原始 SDK 事件分别保存，避免混淆。

测试先验证 SSE 调用格式、真实返回 ID 解析、缺失/失败返回拒绝、请求上限；再本机固定 built CLI 执行真实 smoke，结果由独立 verifier 确认。付费模型、云端与 GPU 不在范围。

## 本机实跑结果与身份边界

train-01 真实工具生命周期通过，3组业务输入全部oracle匹配，finish_reason=completed；P=log-1/Q=pkg-1/R=run-1。摘要见 t2-runtime-smoke-result.json；原始 events.jsonl、requests.json、home 在 `/private/tmp/t2-scripted-runtime-first`。源构建CLI的artifact source commit **unknown**，不能用当前checkout HEAD作为构建来源。SDK也从源码导入，无安装distribution metadata。固定release wheel/image复验仍待主代理在GPU执行。

在新增identity记录后dev-02再次执行，真实events已保存，但报告生成发现源码SDK没有distribution metadata，CLI退出1；已添加负测试并修正为sdk_version=null，不将该失败包装成完整通过，也未重复启动runtime。最终脚本5项CPU测试通过；此次记录只将首轮完整成功作为smoke结果。

可复查调用（从worktree根执行；无 --exe 时使用安装SDK的runtime）：

```sh
PYTHONPATH=. python -m deployment.checks.dsh_log_tool_smoke \
  --fixture examples/dsh/capability_tasks/log_tool/fixtures/train-01.json \
  --output /workspace/artifacts/t2-scripted-new-run
```

本机源码路径另加 `--exe /private/tmp/dsh-v2-built-cli-wrapper`，且PYTHONPATH指定SDK源码；这仅是本地调试入口，固定交付应使用private Release wheel/image，不依赖临时wrapper。

## 显式业务 prompt（示范候选入口）

新增可选 `--prompt-file PATH`：严格UTF-8解码原始字节，不strip、不做换行转换，拒绝全空白。读取一次后，将相同字符串传入首次 harness.run，并在新report记录 `initial_prompt`、`initial_prompt_sha256`（原始UTF-8字节SHA256）、`prompt_source`（file/default-diagnostic）。不提供参数时保留原诊断文本。模型请求由真实SDK自然生成和采集，禁止后写或修改历史requests。

这为真实工具示范→后续独立SFT候选审核提供明确任务条件，scope仍是scripted-policy integration smoke，policy_origin=scripted，不属于学生on-policy轨迹。文件读错/编码错/空白在启动SDK、创建输出之前失败。新增测试覆盖UTF-8与CRLF原样保留、默认值、空白拒绝、SDK入口/报告/请求采集使用同一prompt；不调用GPU或模型。
