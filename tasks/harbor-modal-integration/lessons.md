
## 有价值任务持续推进

- 用户要求持续推动G1时，概念解释与任务分类是主线中的沟通，不能替代真实实现、运行与验收。
- 新奖励器必须区分可信任务失败（0奖励、可准入）和不可信证据（拒绝准入）；只保留成功样本会导致RL失去负例。
- Runtime工作目录HEAD不能证明已有构建产物的源码身份；按发布exe/wheel摘要复验。
- 新launcher环境变量必须对照底座实际读取名，LOW_VRAM不叫LOW_VRAM_MODE。

- 当前tokenizers词表大小查询并非廉价：GPU CPU实测1000次get_vocab_size耗时18.004秒。不要在逐token校验循环中调用len(tokenizer)；按sample取一次。修后84条真实tokenizer检查4.65秒通过，所有prefix/mask条件保持。
