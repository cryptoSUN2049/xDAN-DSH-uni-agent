# Core r4 参数与 optimizer 终态审计

结论：**本次参数审计未通过有效更新门。** 原始失败报告完整保留，未放宽门槛。母训练exit0/16步为主线程已确认事实；本子审计不替代消费、全程梯度或reload审计。

执行固定 `/workspace/rebuild/uni-agent-core-511bd71`，HEAD `511bd71792c7a26af83cb0fe6362cd0f7d5aba96`，原venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5`。只读取本项目自产checkpoint，`torch.load(weights_only=True,map_location=cpu)`；最终model补充检查采用mmap。CUDA_VISIBLE_DEVICES为空，OMP/MKL/OpenBLAS及torch线程均为1，没有GPU推理或权重修改。

## 原工具结果

| 审计 | 结果 |
|---|---|
| checkpoint_delta，step8→16 | exit1，99.645秒，passed=false |
| 504个adapter tensor | 变化0 |
| 399个base tensor | 变化0 |
| optimizer_delta，step8→16 | exit1，5.578秒，passed=false；`All optimizer moments are zero` |

两个model文件SHA256完全相同：`20d8bcd59b631cd1de0e5179f978eef9eae97d23175811eb343c4eecdd074f19`。

optimizer文件SHA256：step8 `a39d66d3dd39264356485b486552faab6bf4ef2c6f357d1f08e52d48a55afdcb`；step16 `d34aebaa558ab06bd9de989c6a75a4be4a5ff6ad207b900d739307f8e3591c81`。文件变化不等于有效更新，下面的step计数已能解释至少一类内容变化。

## 保留原失败门后的只读补充

| checkpoint | optimizer内部step | active/empty状态 | moment tensor数 | finite | 非零moment数 |
|---|---:|---:|---:|---|---:|
| global_step_8 | 16 | 504 / 37 | 1008 | 全部是 | 0 |
| global_step_16 | 32 | 504 / 37 | 1008 | 全部是 | 0 |

VERL训练step与Adam内部step不是同一计数，本报告分别列出，不擅自将16/32解释为额外训练样本。

最终model：252个LoRA A tensor非零、全部finite（15,335,424元素）；252个LoRA B tensor全部零、全部finite（17,694,720元素）；399个base tensor全部finite。补充读取前后model size/mtime不变。

实际PEFT `tuners/lora/config.py:513` 的init_lora_weights默认True，文档与 `layer.py:274` 均明确B零初始化。对应源码SHA为config `a9f95e1a143b8320cf2e0a3139f29c807d937876591f5fc1ce24fc4fd7833b59`、layer `444bba0e5dbc5c55ed51a288a8366c18aa7ebe533d081312a19347eb48b215b6`；固定VERL transformer_impl创建LoraConfig时未覆盖init_lora_weights。

## 结论边界

- 8→16精确相等只证明后半程没有参数差异，不能单独推断初始→最终逐tensor相等；本审计没有加载初始checkpoint进行比较。
- 最终B全部零意味着这组LoRA的B×A增量为零；结合optimizer moments全零，没有证据支持“本次已发生有效学习”。应再结合主线程的全16步真实adv/grad证据，不靠训练exit0或optimizer计数宣称学习成功。
- base只验证了8→16冻结与最终finite，没有以此冒充初始base完整比较。能力提升还需要独立对照评估。

## 持久化证据

完整原件在 `/workspace/reports/core-train-r4-parameters/`：`checkpoint-8-to-16.json`（含903个tensor逐项）、`optimizer-8-to-16.json`、各工具log、`invocations.json` 与 `supplemental-state.json`。模型保留在 `/workspace/uni-agent-g1/checkpoint/core-train-r4/global_step_{8,16}/actor/`。

报告SHA：checkpoint报告 `ad63e8fd3d2fb16076a014b36113c5215507943ae6c96c4dfe504fc26c228466`；optimizer报告 `0d7b0be569c7d31fc22370c69397b6a55d77bfad31fc28f448a61e69126fd294`；invocations `6e1b3342b67e49752038e6d76dd6b8fd91c44218e092aa78f4c1574e12e56edf`；supplemental `c398023359dddc9bb26edc81841818c9a4136f795feb9a6469fc6b443a423354`。机器可读摘要、命令及路径见同名JSON；原始passed=false未覆盖。
