# MiMo 9B 名称残留测试结论

固定revision 2367e865d009c13ac81713a2878291d33ab28177，原版权重和模板，未新增token。88次身份请求，87完整、1截断；另2次真实加法工具闭环通过。请求和响应见 results-v1/，统计见 name-contamination-observations.json。

用户关注“训练是否混入MiMo名字”。所有提示（含system和历史）均未出现MiMo/小米的54次请求中，最终回答与可返回reasoning均0次出现MiMo/小米，且无截断。其余带名称暗示或来源提示的回答不能算自发身份证据。此结果仅说明本次小样本未观察到自发名称残留，不能证明训练数据不含该名称，也不保证未来微调后不出现。

原版常自称Qwen/Qwen3.5，也出现Claude等身份幻觉；模型自述不是权重来源取证。可通过配置、tokenizer、模板及参数相似性识别派生关系，因此不能保证改造后来源不可识别。

完整tokenizer关键消息/think/tool标记均单token；added-vocab没有MiMo/Xiaomi/APUS品牌项。模板多模态分支含mimo_audio字符串，不是默认文本系统身份；未测试音频分支。

APUS接口约定：对外标准messages/tools/tool_calls/tool_call_id，内部仍使用原生模板。协议标记apus-chat-v1放deployment.json，不加入模型序列。身份测试已结束，测试服务已停止释放GPU，模型权重留在Runpod。后续回归数据处理主线。
