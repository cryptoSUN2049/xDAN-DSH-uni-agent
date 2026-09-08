# 最新 DSH 与真实 Uni-Agent runner 接线验证

2026-09-08。**本仓实际 `uni_agent.agents.dsh.runner.run` 已通过最新真实 Python SDK + 本地 built CLI 完整执行一次任务，进程 exit 0。** 模型响应来自 DSH 官方 smoke 脚本的本机 MockModel；没有替换 DeepSeekHarness、返回事件或工具执行，没有付费模型调用与 GPU 训练。

## 本次结果

| 检查 | 实际结果 |
| --- | --- |
| SDK/模型往返 | 4 次官方 MockModel 请求 |
| SDK 事件 | 26 条；4 条 `assistant/message` 均携带 embedded `stream` |
| 实际工具 | 3 组 `tool/call` / `tool/result`；两次持久 shell 和一次编辑器 |
| shell 状态 | 官方 MockModel 分别检查 `COUNT=1`、`COUNT=2 CWD=/tmp` 后才继续 |
| 文件产物 | `created.txt` 原始内容精确为 `created by packaged editor\n` |
| Session 身份 | `dsh-v2-unia-runner-smoke`；本仓 `_require_result` 验证身份与 trace path |
| 完成状态 | `finish_reason=completed`；末事件 `turn/end` |
| 最终文本 | 精确为 `minimal agent smoke ok` |
| 原始 trace | 13,870 字节；重新计算 SHA256 与 runner 返回一致；JSONL 行数与 event_count 一致 |
| 落盘合同 | 返回结果与原始 result.json 一致；trace/result 权限均 0600；输入文件已删除 |

原始事件类型计数：`agent/inbox/spliced=2`、`turn/start=1`、`step/start=4`、`user/message=1`、`session/title=1`、`request/header=1`、`request/context=1`、`assistant/message=4`、`tool/call=3`、`tool/result=3`、`step/end=4`、`turn/end=1`。本成功任务没有触发失败 `assistant/attempt`；该分支的源码测试见 `dsh-session-v2-test-results.md`。

## 执行方式与版本时点

实际命令（在 Uni-Agent worktree 执行，首次即通过，无诊断重跑）：

```sh
/private/tmp/uni-agent-cpu-20260907/bin/python \
  /private/tmp/dsh-v2-unia-runner-smoke.py \
  > /private/tmp/dsh-v2-unia-runner-smoke.log 2>&1
```

临时脚本通过绝对路径导入 DSH `python/sdk/src`、`python/sdk-runtime/src`、本仓真实 runner，以及官方 `scripts/smoke-python-runtime.py` 的 `MockModel` / `MINIMAL_PROMPT`。仅在当前 Python 进程替换 runtime 的启动选择：

```python
deepseek_harness_runtime.resolve_bundled_launch_args = lambda: (
    "/Users/gumpm5/.nvm/versions/node/v22.22.0/bin/node",
    "/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/apps/cli/lib/bin.js",
)
```

其余 SDK 初始化、JSON-RPC、Session 通知、agent loop、shell/editor 和 `RunResult.events` 均为真实实现。脚本使用 `sdk-minimal`、无 patch、每请求 max_tokens=4096、临时 DSH home/cwd、假 key 和 loopback URL，并设置 90 秒总超时；通过后恢复 resolver。未设置真实 Gateway，因此这个 URL 不构成 Gateway session 路由验证。

读取开始时 DSH HEAD 为 `b2369692ea530007075ebcd18d39fdba0bbd3982` 且工作区 clean；执行期间另一会话格式化 Python 文件，收尾先观察到 dirty，再观察到已提交的 `7405a7cc9dbc3f60845918de514eb36d92719e16` 且 clean。本次没有修改这些 DSH 源码。之后直接比对：SDK 的五个 Python 模块、runtime resolver 与官方 smoke 脚本，当前源码与固定 `b236969...` 的 Python AST 均相等。**此证据对应实际本地构建/源码快照，不宣称整个工作区字节始终冻结为 b236969，也未重建或逐文件证明 built JS 与 HEAD 的一致性。** 后续 Linux 构建继续固定已验收候选 `b236969...`，不追逐同仓并行文档/格式提交。

## 可复查原始证据

- 临时执行脚本：`/private/tmp/dsh-v2-unia-runner-smoke.py`，SHA256 `2c687a45ac91d70a455071507210871566b42ab5e055f79ecc45db71a44e0652`。
- 机器结果：`/private/tmp/dsh-v2-unia-runner-smoke-result.json`，SHA256 `93d66e930864539a67a9e35971e255d7419821b2db4cd48d26667d58d54f433a`；stdout 日志与它逐字节相同。
- 原始目录：`/private/tmp/dsh-v2-unia-runner-_m7m_suy`，含 trace、result、工具文件及本次临时 DSH home。
- `session.jsonl` SHA256：`15184dd0f94977e96e9b1f4865e5c01d2918c9421524a80f557c53ae9e6537bf`。
- `result.json` SHA256：`8e28e631a1145b2956e3577f4069d9161b067bfad1c0dcc71c997ce6a39cab5a`。
- `created.txt` SHA256：`2d6fa1c23cd7916059326ba2f38f799bffc9cfa3ae0279cdb4ad4e315a9903a2`。

## 默认构建目标更新

按用户随后明确要求，`deployment/bootstrap/build-dsh-runtime.sh` 的默认 `DSH_BUILD_REVISION` 已改为新版 `b236969...`。旧 `7840bced...` 只接受显式选择，供历史回退；构建来源仍须匹配完整 SHA、tracked clean、Linux x86_64，并使用固定 Node 24.20.0 / pnpm 11.7.0。

对应输入测试先得到预期的 1 failed / 17 passed，再修改默认值后 **18 passed（7.49 秒）**；`bash -n`、Ruff check 和 format check 均 exit 0。测试通过替身 Git/平台和首次目录创建屏障验证输入，未执行下载、安装或构建。

`deployment/versions/dsh-session-v2-candidate.json` 的新版候选仍为 `not-deployed`；未知 runtime、wheel、image 摘要保持 `null`。默认构建目标变更不能代替已部署版本确认。

## 升级证据边界

本轮将证据从 SDK 自身 smoke 推进到**本仓真实 runner 的配置、事件采集、trace/hash 与 helper 结果合同**。尚未验证 Linux 发行 wheel、真实模型、Uni-Agent Gateway token/mask/logprob、Harbor worker 回传、严格 reward receipt 或 RL 更新/reload；本机 mock 成功也不证明能力提升。
