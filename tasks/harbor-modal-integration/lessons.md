
## 有价值任务持续推进

- 用户要求持续推动G1时，概念解释与任务分类是主线中的沟通，不能替代真实实现、运行与验收。
- 新奖励器必须区分可信任务失败（0奖励、可准入）和不可信证据（拒绝准入）；只保留成功样本会导致RL失去负例。
- Runtime工作目录HEAD不能证明已有构建产物的源码身份；按发布exe/wheel摘要复验。
- 新launcher环境变量必须对照底座实际读取名，LOW_VRAM不叫LOW_VRAM_MODE。

- 当前tokenizers词表大小查询并非廉价：GPU CPU实测1000次get_vocab_size耗时18.004秒。不要在逐token校验循环中调用len(tokenizer)；按sample取一次。修后84条真实tokenizer检查4.65秒通过，所有prefix/mask条件保持。

- SFT聚合loss不能代替关键动作成功率：batchsize1下native dev指标对decision等权平均，定义步骤只占每case的1/14。本轮mask/监督token分母正确，但低平均loss仍伴随非法JSON与错误注册API。后续单列关键动作与自主完整任务结果。
- PEFT加载已有adapter会将BF16 adapter升为FP32。比较checkpoint时记录dtype变化，先做无损规范再核数值delta；不能把cast本身计作学习，也不要放松通用比较器的严格dtype合同。
- Harbor可复部署必须固定agent与独立verifier两枚实际镜像；只固定verifier Dockerfile父镜像不等于运行固定发布物。
