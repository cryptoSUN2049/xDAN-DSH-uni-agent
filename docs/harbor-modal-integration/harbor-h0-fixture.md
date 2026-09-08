# H0 固定 CPU 任务

沿用已批准的 Docker oracle 验收范围，先验证 Harbor 0.16.1 的环境、文件、评分和清理，不调用模型，不代表 M2 训练通过。

架构：Harbor Trial → 专用 Docker 容器 → oracle 写文件 → verifier 严格比对 → reward.txt → TrialResult → 清理本 trial。

文件：examples/harbor/h0-file-write/{task.toml,instruction.md,environment/Dockerfile,solution/solve.sh,tests/test.sh}。
合同：/app/answer.txt 字节必须等于 `harbor-h0-ok\n`；成功1，否则0。环境固定 ubuntu 镜像摘要、1 CPU、512 MiB。
测试：oracle 正例；nop 无操作负例；核对 rewards、exception_info 和 trial 容器清理。不得将 oracle 结果算作 DSH 或参数更新证据。

实测：首次因Docker默认地址池耗尽失败。新增environment/docker-compose.yaml令main network_mode=none，不删除其他项目网络。第二次oracle=1、nop=0，均exception_info=null，证据见harbor-h0-results.json。Harbor CLI环境失败也可退出0，因此必须检查result.json。
