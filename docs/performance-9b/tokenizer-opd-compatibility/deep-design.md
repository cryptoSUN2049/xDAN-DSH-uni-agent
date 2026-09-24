# OPD 深度兼容验收

用户已批准进一步确认，并明确要求定位VERL源码。保留现有worktree改动，不修改已完成训练和VERL生产实现。

目标：源码、真实函数数值控制、历史文本重放三者交叉验证。源码按服务器文件SHA核对；CPU直接调用部署版distillation_loss，独立计算损失和梯度，覆盖混合长度、padding、EOS位置、裁剪和detach。GPU使用原训练step1的保存文本重新编码，依次计算HF学生T=0.8、HF教师T=1和vLLM教师评分；不能把重编码后的序列称为原始历史token张量。

文件：deep-source-audit.md、deep_numeric.py、deep_replay.py及对应JSON报告。接口为独立目录和JSON，不改变训练产物。使用既有uv环境，单卡串行，GPU空闲后运行，无外部沙箱费用。教师HF/vLLM误差沿用mean<0.1、p95<0.5阈值；负控制采用错一位对照。数值loss/gradient float64误差须小于1e-8，padding梯度为0。

边界：原训练只保存解码文本，没有逐token评分张量；历史精确批次重建未完成。thinking、多轮原生模板不同，继续视为独立验收范围；本轮不宣称全模式适配。
