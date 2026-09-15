# HTML 验证记录

2026-09-15。目标文件：system-plan.html。

## 最新验证：P0 工程闭环完成后

本节为当前状态；后文保留最初 HTML 和 HTTP 402 的历史检查，不能将其当作现在的阻塞。

- 数据依据：部署代码 b06728a；run `hybrid-p0-20260915-02` 的 `training_evidence.json`、`parameter_update_report.json`、`reload_report.json`、资源 journal 与 `verification-status.json`。新增 [闭环报告](p0-cloud-closed-loop.md)、[下一里程碑](next-milestone.md) 和 [机器可读摘要](p0-live-status.json) 入口。
- 内容核对：286 项相关测试；10 个核心模块综合覆盖率 90.67%、分支覆盖率 83.23%。真实更新 1,179 个动作 token / 3,595 个屏蔽位置；loss 181.8892098665；53,520,850 个 LoRA 元素变化；新容器、新进程推理 reload 完成。
- 结果边界：训练奖励 [1,1]，RL advantage=0；有效学习来自 OPD。验证前 2/2、后 1/2，`passed=true` 仅工程有效；实际任务 scores=[1,0]。没有宣称能力提升、非零 RL 学习或正式 Terminal-Bench 验收。
- 失败分析：已写入 service-config 重写遗漏字段与轮数上限；明确缺 grader 原始输出和后评估实际 SamplingParams，前后并发不一致，不能因果宣称更新造成退化。
- 使用 gstack browse 重新加载本地页：桌面 1440×1000 时 `scrollWidth=1440`；手机 390×844 时 `scrollWidth=390`，无正文横向溢出。已查看桌面、手机和架构图截图。
- OPD、RL、hybrid 三种模式实际逐一点击；文案随之变化，`aria-pressed=true` 始终仅 1 个。展开步骤 7/7；beforeprint 展开 8/8 details，afterprint 恢复至原 1 个。
- Node JS 语法检查通过；22 个唯一 ID，36 个链接，内部锚点与所有本地文件均有效；console 无错误，无外部脚本/图片/字体依赖。
- 临时截图 `/tmp/tinker-plan-final-{desktop,mobile,architecture}.png`，不当作持久训练证据。此次文档验证未调用模型、未提交云任务。

## 以下为历史记录


## 内容依据
- 读取官方 skills/research/SKILL.md、references/sdk.md、references/distillation.md。
- 源码：上游 Cookbook 485726f，本地实现 f96cc38；安装 SDK tinker 0.29.0、modal 1.5.5。
- Context7：先 library 解析，再两次 docs；SamplingClient 官方页面通过 browse 打开，HTTP 200。
- 交叉发现：Context7 旧自动文档部分声称 compute_logprobs 返回 SampleResponse；安装 SDK 与当前 API 页面是 token logprob 列表，HTML 采用后者。

## 已完成的文档验证
- HTML 结构扫描：22 个唯一 ID、34 个链接，内部锚点和本地文件链接全部有效。
- 无外部脚本/图片/字体依赖，无 credential-like 字符串。
- browse 桌面 1440x1000：document.scrollWidth=1440，无正文横向溢出。
- browse 手机 390x844：document.scrollWidth=390，无正文横向溢出；长表格/架构图在容器内滚动。
- 三种模式 OPD/RL/hybrid 逐一点击，文案与 aria-pressed 正常且仅一个选中。
- 展开全部：7/7 阶段展开。beforeprint：8/8 details 展开，afterprint 恢复。
- 清空此前官网错误后重新加载本地页，console 无错误。
- 查看桌面、手机、架构截图；修复手机标题碎行与 SVG 箭头。
- 临时截图位于 /tmp/tinker-plan-*.png，不作为持久实验数据。

## 证据边界
这是文档与交互验证，不是训练系统测试。本地42项训练测试来自已有 runbook；本轮未重跑。
用户本轮提供 Tinker key 后，启动了现有 preflight；仅在子进程环境内注入，未保存凭据。
云端探针结果另记，不将已发起请求表述为成功。

## 独立只读审查
已采纳2处边界修正：批次级评分/全零 mask 拒绝是待补目标，不是已有防护；SDK示例说明移除辅助mask字段并复用官方train_step。

## 本轮真实 API 诊断结果
Tinker SDK preflight 与独立只读 capabilities 请求均返回 HTTP 402，服务明确要求处理账户 billing。
探针停在 get_server_capabilities，随后主动中断计费等待进程；没有模型采样、评分、训练、Modal资源创建。
诊断附加发现：未带密钥的服务根路径HTTP404只证明网络到达，urllib默认请求曾返回网关403/1010，标准curl复核到达API并返回402。最终依据为SDK和API一致的402。
见 scoring-probe-status.json（不含key或账户名）。付款/额度处理完成后需重新验证两个模型；不能将其 availability 标为 false。

最终回归：Node JS语法检查通过；手机文档无溢出；HTTP402状态已显示，console无错误。

## 充值后新证据
用户报告充值10美元；GET capabilities HTTP200，共35模型，两目标均在列表。
SDK原探针返回scoring_probe_passed，31 prompt/111 action tokens；sampled KL均值0.5617713852，Student sample/rescore最大差0.2730098963。
探针不设该差值阈值，因此仅验收单文本评分可用，不宣告数值一致性或完整OPD通过。
HTML同步结果并以macOS open成功交给默认浏览器；无训练或Modal sandbox运行，未取实际费用。
