# 核心记忆课程扩量与有界训练

2026-09-10，落实用户已批准的核心记忆任务扩量与尽快训练。复用现有任务、评分和DSH唯一循环，不改旧数据或奖励。

## 范围

新增course_id=work-state-memory-core-v1：WS01交接、WS03索引、WS05事实更新各16个train seed1001..1016（variant0），WS06克制负例4个train seed1001..1004；合计52train。前三族各4个公开dev seed2001..2004（variant1），WS06 4个同范围dev，合计16dev。实例结构复用既有4族，不宣称新52种结构或封存集。不得将oracle/参考输出放入actor数据。

首轮16步、n4、固定sync，step8/16保存，初始/周期评估关闭，现有独立逐题reload。52是可用任务数，实际消费按task ID审计，不要求16步覆盖52题。基线使用现有val入口，同一新课程公开dev，预先固定每族首题，不根据结果挑题或修改提示。

## 实现合同与文件

prepare_memory_training.py仅新增课程白名单、确定性schedule和课程对应samples/steps/save配置；保持旧课程不变、母checkpoint严格同课程、源hash/manifest检查。测试覆盖数量、ID/split不重叠、确定性、oracle正负例、旧默认不变、任务计数与训练预算透传。若其他层硬编码课程，逐点显式添加身份而非放宽未知值。

不增加B-only/oracle记忆路径，不改reward、不新增trainer、不改DSH或VERL pin。任务contract仍采用原公开schema；事实矩阵提示B检索为主要瓶颈，但是否能RL学会须由实际分布验证。全同分则记录无信号，不继续盲目长跑。

## 执行与验收

CPU回归与Ruff→commit/push→新固定GPU checkout复用venv→真实runtime canary→四题base基线→新run16步训练→实际完整组、梯度、参数/optimizer→固定四题独立reload对照→归档。每run独立目录与监督上限，checkpoint在/workspace/uni-agent-g1/checkpoint/<run>。基线/训练/评估分别记录身份，不将失败任务吞掉或修改原回执。

## 用户要求10倍及生成检查

目标调整为520train/160公开dev：前三族各160train、WS06 40train，每族40dev。实际已生成680候选ID并完成680正例/680空配置负例评分检查，但仅256train/148dev可见内容不同，WS03 train只有4种。不得宣称680独立任务，不直接作为多样性扩充验收。下一步需版本化增强真实业务变量/候选组合，而非仅换种子或重命名。旧任务生成器不能静默修改。原16步仅诊断预算，不代表消费全部520题。
