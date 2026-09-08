# DSH能力数据扩量：分工、操作入口与验收

## 当前决策

数据生产由用户安排的另一会话负责，优先复用DSH-Exp的feat-sft-campaign；Uni-Agent负责能力目标、训练输入契约、在线RL和学生评估。m3-nanogpt-sft-lora提供覆盖/溯源设计参考。不再在Uni-Agent复制第二套teacher生成器。

本指南依据当前本地scripts/generator.sh、scripts/data-generation/cli.ts和configs/data/memory-context-pilot.json读取结果整理；没有执行付费采集或批准扩量。数据会话须先完成原8个live实例的结果汇总、测试及commit固定。当前配置student=Qwen3.5-4B，本轮Uni-Agent训练是Qwen3-4B，模板/tokenizer不可直接混用。

## 扩量按三个门执行

| 批次 | 目标规模（建议起点） | 放行条件 |
| --- | --- | --- |
| pilot收尾 | 既有4 normal + 4 negative | 每个实例有完整Session、独立验收和来源，失败分类清晰；不把negative合理停止当成功SFT |
| 覆盖pilot | 先40个独立实例，优先已支持场景 | 增加场景结构/失败类型，不只是换字符串；冻结划分，CPU oracle/负例、去重和泄漏检查通过 |
| 效果实验 | 100–300 train、30–50 dev、50–100 test | 学生dev基线暴露真实能力缺口，再按缺口扩；数量不等于充分性 |

40例不是把旧8例循环五次；新family/template需相应fixture与verifier支持。family分组不跨split；test保持独立。若测试结果参与调参，将其改称dev/diagnostic并另建新test。

## 已存在的操作脚本

在数据会话工作目录执行，先查看帮助与计划，这两步不调用teacher：

```bash
cd /Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-sft-campaign
bash scripts/generator.sh --help
bash scripts/generator.sh plan --config configs/data/memory-context-pilot.json
```

已有campaign的检查入口（使用真实campaign目录替换变量）：

```bash
CAMPAIGN_DIR=/absolute/path/to/existing-campaign
bash scripts/generator.sh status --campaign "$CAMPAIGN_DIR"
bash scripts/generator.sh check --campaign "$CAMPAIGN_DIR"
```

只有在数据会话冻结新配置、确认预算及执行授权后，才运行真实teacher采集：

```bash
CONFIG_PATH=/absolute/path/to/reviewed-new-config.json
CAMPAIGN_DIR=/absolute/path/to/new-campaign
bash scripts/generator.sh plan --config "$CONFIG_PATH"
bash scripts/generator.sh run --config "$CONFIG_PATH" --campaign "$CAMPAIGN_DIR"
bash scripts/generator.sh check --campaign "$CAMPAIGN_DIR"
RELEASE_DIR=/absolute/path/to/new-release
bash scripts/generator.sh export --campaign "$CAMPAIGN_DIR" --out "$RELEASE_DIR"
```

run会调用teacher；不得从本指南推断新增付费预算已获批准。resume入口为`run --resume <existing-directory>`，先确认原进程退出、锁与中断状态；不是无条件重发。check/export必须读取退出码，任一步失败停止发布，不能直接串行忽略错误。导出后仍需backend-check的真实loader验证，不能把export成功称ready-for-training。

当前CLI退出码：0成功、2输入错误、3采集短缺、4结果未决、5检查失败。准确语义以数据会话固定提交源码及运行结果为准。

## 另会话需要补齐的执行能力

- 新campaign配置及人工可读计划：family、split、难度、normal/negative/恢复场景、seed、模型与runtime身份、各项预算。已有配置只8例，不手改正在运行campaign。
- 增量采集后按内容和模板去重，独立train/dev/test统计；报告task/trajectory/SFT row/target token四种数量，不互相替代。
- 新release manifest：文件sha256、生成代码commit、DSH版本、teacher provenance、模板/tokenizer身份、划分与验收报告。
- 一份可执行批次包装脚本（如果现CLI组合确有需要），遵守set -euo pipefail、显式新目录、plan-first、预算上限、退出码短路、resume不重发；不要另造采集框架。设计确认后由数据会话实现测试。
- README提供plan→run→check→export→backend-check实测命令，区分已验证和计划命令。

## SFT与RL双交付

SFT交付：通过独立业务与轨迹验收的teacher示范、canonical来源及训练投影。负例保留做评估/偏好候选，不能一概导入成功SFT。

RL交付：任务种子、fixture、初始环境、verifier和版本身份，由Uni-Agent当前学生经Gateway实时采样。teacher轨迹和离线VERL候选文件不自动成为on-policy训练轨迹。

Harbor需要同任务的环境/验证封装；不是新的学习算法，也不要求把每条SFT示范都转Harbor。DSH仍唯一执行循环。记忆任务必须明确A写入→B新会话检索与事实保真，不能以压缩token数评价成功。

## 主会话接收门

1. 审核新数据manifest/来源/划分和真实正反例报告。
2. 绑定本次学生准确模型、tokenizer、runtime/profile/patch；Qwen3与Qwen3.5输入分别适配。
3. 新实验目录先跑学生dev baseline；确定难度、奖励方差与主要失败类型。
4. 根据失败选择SFT补课或在线RL，少步训练→数值检查→独立reload→同预算dev复评。
5. 冻结候选后才使用隔离test；报告逐场景成功率、恢复率、事实准确率、任务成本及不确定性，不只报均值。

G1当前固定4/2工程课程保持不变；扩量数据用于下一独立效果实验，不影响Harbor M2工程验收。
