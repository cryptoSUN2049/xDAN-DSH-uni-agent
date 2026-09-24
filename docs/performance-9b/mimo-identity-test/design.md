# MiMo 9B 身份与 APUS 接口验收

用户已要求部署并测试；固定上游 XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B @2367e865d009c13ac81713a2878291d33ab28177。官方卡片 MIT、base_model Qwen/Qwen3.5-9B、SFT；保留卡片和权重来源，不改写原版权重。

流程：固定版本下载 → 完整tokenizer/配置核查 → 空闲单GPU本机回环服务 → 原版无身份提示与APUS产品身份对照 → 中英文/追问/工具闭环 → JSON原始响应和报告。Mac不下载权重。

接口采用OpenAI/Qwen风格 messages、tools.function、assistant.tool_calls、tool.tool_call_id；内部保留MiMo原生模板。没有新增token。`apus-chat-v1`仅作为服务协议标记写在独立deployment.json，不插入工具参数或生成内容，不修改词表。接口model别名与实际权重来源分列。

验收区分：原生模板是否硬编码身份、模型自然自称、系统提示能否稳定设置助手产品身份、模型是否错误宣称APUS从零训练权重、工具参数是否可解析且结果能正确回传。工具仅执行本地确定性的加法示例，不执行模型生成shell。请求和响应原样记录；截断/异常不得算身份通过。此测试不证明任何隐藏水印不存在。

文件：examples/performance_9b/mimo_identity_probe.py、远端部署脚本、deployment.json、responses.jsonl、report.md。测试基线与APUS提示使用相同推理配置。四组system：none、neutral、apus_product_only、apus（真实来源），每组20单轮+1两轮，共最多88身份请求、组间3并发；开放/结构化/诱导/多轮标签分开。仅监听127.0.0.1，必要时SSH隧道访问。
