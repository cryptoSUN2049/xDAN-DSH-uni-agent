# 9B ← 27B OPD 深度验收结论

结论：对本地这两份模型、当前文本单轮关闭thinking的k1+PG配置，源码与补充实测未发现token错位、教师评分异常或loss梯度方向错误。支持继续开展受控扩量实验，不代表全模式完全兼容，也不代表必然有能力收益。

## 已完成的证据

1. 本地与服务器部署版losses.py、core_algos.py、distillation config SHA完全一致；源码链见deep-source-audit.md。学生原始token IDs直接送教师评分，没有套用教师原生聊天模板。
2. 直接调用服务器VERL的distillation_loss及padding函数。四组ratio控制的损失和梯度与独立公式误差均为0；不同长度、首末响应、EOS坐标、padding零梯度、teacher detach及正负更新方向通过。极端差值和PPO/dual clip均纳入控制。
3. 五域历史文本重编码重放，加一个显式EOS控制，共2736个响应token（包含控制样本重复前缀，并非2736个独立样本）。最长响应1024token。教师HF与vLLM平均绝对误差0.008197、P95=0.064773；各案例均通过预定mean<0.1、P95<0.5门禁。故意错一位的平均误差0.302–1.275，明显更差。
4. 实际调用VERL原生extract_prompt_logprobs，六案例全部teacher IDs与学生next-token IDs逐项一致，末尾dummy正确。混合padding和响应切片用真实函数验证。
5. 重放的真实学生T=0.8/HF评分与教师T=1/vLLM评分送入VERL损失；控制ratio=1下，独立loss误差2.78e-17、梯度最大误差4.34e-19，2736有效token，本批差值触发±10裁剪的token为0。它不是历史优化器状态回放。
6. 深度验收进程exit0，GPU已释放。未修改VERL生产代码、原模型或原训练结果。

## 必须准确描述的实现细节

- k1分支不使用log_prob_min_clamp，设置-10不会逐项裁剪teacher/student logprob；真实行为是对差值裁剪±10。这一点已由改变该参数而结果不变的实测证实。
- 学生logits按0.8温度归一化，教师prompt logprob是T=1。这是当前分布设定，不能拿双方T=1的公式错误对照。
- k1 loss本身只检查shape，不检查teacher_ids内容。本次额外检查通过，但生产链路仍缺少这个强断言。
- 初版验收脚本曾因DistillationConfig要求teacher配置、以及冻结字段禁止修改而失败；改为独立loss配置和重新构造配置后通过。远端run-attempt1.log保留冻结字段失败记录；两项均为验收脚本配置问题，不是OPD结果。

## 不能证明的部分

原训练没有保存逐token IDs、mask、teacher/student logprob的完整快照，只有解码文本。重编码可能丢失原始特殊token与结束状态，所以本次不能事后证明历史所有批次逐token无误。下一轮应记录抽样原始张量并检查teacher IDs，使验收成为训练内的固定检查。

thinking开启、多轮历史和工具模板存在已知差异；工具输出mask、长prompt、超出当前训练长度、其他模型revision都不在本次通过范围。受控小步训练效果仅支持一题数学预算内完成改善，不能推断全面性能。

## 扩量路线

用户允许考虑数据不足时扩大训练。优先扩大经过去重和答案审核的独立样本，而不是反复训练122条。先补科学知识、代码执行评分、聊天质量评分与封存测试；新一轮从原版固定起点建立可复现实验，预先冻结域配比、验证预算和止损规则，再逐级增加样本与训练步数。未在此次兼容性验收中启动扩量训练，也未额外调用付费沙箱。

## 证据入口

- deep-evidence/numeric.json：实际VERL合成边界控制。
- deep-evidence/samples.json：历史来源SHA、重编码token及样本范围。
- deep-evidence/hf-replay.json、vllm-replay.json：逐token评分。
- deep-evidence/native-parser-checks.json：原生解析器ID对齐。
- deep-evidence/replay-loss-check.json：真实概率批次loss/gradient。
- deep-evidence/replay-verdict.json：HF/vLLM误差与错位负控制。
- deep_numeric.py、deep_replay.py、deep_run.sh：可复现脚本。
