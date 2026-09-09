# RSI 学生真实提议 P r1

固定源码b1c568b，父基线rsi-student-h0-r1。新作业rsi-student-p-r1于2026-09-09 21:48:36(SGT)发起，监督exit0，265.645秒；实际生成任务49.7秒，42个模型token。原NPZ/trace/SDK最终文本/回执与TQ唯一消费审计通过，registration_ready=true。

学生实际输出：

```json
{"schema":"dsh.rsi-profile.v1","profile":"sdk-minimal","allowed_tools":["cordis_inspect_list","str_replace_editor"]}
```

这是学生在固定父配置与审计白名单诊断下真实生成的声明，不是控制器手填候选。父仅允许str_replace_editor，学生增加了预先批准搜索空间内的cordis_inspect_list。任务禁止调用工具，本次只生成候选JSON。

格式诊断reward=1，仅表示合法且有变化，不表示开发收益、已晋升或RL更新。报告时尚未注册；随后必须由register_verified_proposal重审全链原始证据再登记，不接受本报告布尔值替代审计。

[原始摘要与hash](rsi-student-p-r1-result.json)。准备manifest位于/root/runs/rsi-student-p-r1-data/preparation-manifest.json，SHA256=8c510da59bcb681cded5cb91e884b65f7d020fcef8c00457610b0f37fb5ee4da。母active保持不变；GPU退出后释放至0MiB。下一步H1两题隔离评估，比较结果决定是否晋升，不能拿格式奖励代替收益。

## 后续登记（保留上文提议完成时的历史状态）

现有 `register_verified_proposal` 已重新审核H0/P原始证据并登记学生候选 `438ad34856e6169fb0cdc92a219ea2b4c7f5c4f6440114879652f4ce3b2942a8`。父active仍为 `fd91e253ae098b002f4fab62fcdf6ddf345ad421263f2d9ee47bc2e202a1dfc6`，未晋升。见[原注册回执](rsi-student-p-r1-registration.json)。

P原始运行证据另已归档[云盘归档](rsi-student-p-r1-archive.md)，24文件逐项回读通过；该归档固定提议阶段，不包含后续注册。H1准备清单SHA256=ad62faa9c4c14d7a76da069a0d737fef1f71833d81188bf91712d3d7ed02bb3f，尚不表示H1执行完成。
