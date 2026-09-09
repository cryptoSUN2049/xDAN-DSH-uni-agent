# Work-state protocol revision 2

依据真实 `work-state-val-r1` 的第一条WS01记录：A读取正确来源后试图修改只读源schema值，之后循环查看缺失可选文件，75steps/74工具调用后正常completed，但unsafe使eligible=false。WS03亦被拒；WS05已有合法A0→B0，但整体基线尚未验收。

本次只澄清 `tasks.py` / `stage.py` 的角色与说明：A准备交接，B执行配置/计划；来源值是依据而非要求自行升级；只保存有用状态；可选文件无需逐个存在；写完交接即可结束；索引用相对路径，不能要求B访问A原绝对目录。任务增加protocol_revision=2，其source/verifier摘要随之变化。

权限、二值业务评分、原始输出快照、完整组准入、固定DSH/VERL、模型权重均不变。新说明不是标准答案，不填补学生文件，不回写旧回执。任务/stage/消费/recipe组合80项通过。新run先看四族真实初始评估，再看n4是否产生有效组与梯度；提示变化不作为训练效果。

为减少重复加载模型，后续修订run可使用原训练入口的initial validation完成真实基线，然后由同一训练作业进入8步RL；该initial validation仍必须严格通过。遇到拒绝保留失败并停止修复，不跳过验证。
