# 新双卡主机与五域启动前实查

新SSH为root@157.157.221.177:16160。2026-10-01 08:33UTC Runpod v2 GET按该SSH端点确认Pod digzlnvc92cntc / Harbor-RL-Testing / RUNNING，双RTX PRO6000，GPU分配价4.18美元/小时，挂原卷72jdno5cuk；平台startedAt为07:26:54.977UTC。没有停止、重启或修改该Pod。其他账户资源未操作。

Mac直连走VPN utun4，被SSH关闭；绑定en0后成功。首次只读实查双卡均97887MiB，显存0/利用率0，无计算进程。这个快照不表示已启动训练。

uv位于`/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1`。freeze SHA与原e9f87349一致，273个严格name==version项全部匹配，版本差异0；280个metadata记录中有verl/uni-agent重复项。另三个source/editable依赖不能用版本检查代替commit/import验证。默认VERL实际导入旧项目路径；当前环境没有SGLang/megatron-core/mbridge。不能只activate之后直接声称参考fork可启动。

本地MiMo模型config为Qwen3_5ForConditionalGeneration，含vision_config。实际云CPU加载Qwen3VLProcessor与Qwen2VLImageProcessor成功，输入支持pixel_values/image_grid_thw；CUDA不可见、未加载模型权重。此项不是vision policy生成/训练证明。原C5十五个文件的大小列表存在，当前没有重新全SHA或加载C5；新/root/mimo-private不存在。

另外四Parquet已云CPU真实读取：Cyber1000、General989、Webdev2093、Music1000，完整文件SHA已记录。General两支是terminal_bench64与general_agent925；925业务任务目录与固定revision的925资产前缀全部匹配，未下载执行41284个资产文件。固定mimoagent registry缺terminal_bench类型，Generic又没有verifier，必须显式补原tests_files协议，而非重标签跳过。

当前新五域训练入口、环境适配、grader预检、双卡参考后端、native W&B/Insight训练流尚未部署或启动。已有DSH Code PASS保留。设计已提交16fd195并push，精确提交完整Ruff check/format check693文件通过；本次新增数据/环境证据另行提交。五域架构设计及新运行期限已通过异步问题请求确认，未收到答案不能当作批准。

证据：[当前Pod端点](evidence/r22-current-pod-status-20261001.json)、[uv与processor预检](evidence/r22-uv-and-processor-preflight-20261001.json)、[数据与General资产盘点](evidence/r22-five-domain-data-preflight-20261001.json)。实施范围见[五域设计](mimo-five-domain-reproduction-design-20261001.md)；这里的CPU预检不能替代其训练完成门。
