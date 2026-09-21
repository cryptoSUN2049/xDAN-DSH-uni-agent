# 真实评分控制（2026-09-21）

## SWE-bench Verified

`astropy__astropy-12907`：nop=0、oracle=1，exception均空，控制完整通过。远端收据：`runs/cross-benchmark-20260921/verifier-controls/sweverified/validation.json`。这是单题验证环境/评分链路，不代表500题全部oracle通过。

## TB2.1

`build-cython-ext`：nop=0，oracle也为0。唯一一次独立诊断重跑只在复制题的assert中增加子进程stdout/stderr，未修改正式题和判分。两次均为外层10 passed/1 failed，内层17 passed/1 failed。

内层失败：`test_reconstructed_space_curve`调用`planarity.PGraph(...).embed_drawplanar()`后，`planarity.networkx_graph`生成的节点没有`pos`，pyknotid访问`data['pos']`触发KeyError。这是当前参考解依赖组合与任务代码的兼容问题；不是模型推理/GPU/超时，不能由此推断所有模型都无法解题。未证明具体历史版本何时改变。

正式集合保留89题及原始数据文件。不得静默删掉此题或修改测试使oracle过关。报告须列出该已知参考解问题；如额外做排除此题的敏感性分析，必须同时保留完整89题主结果。

另选预先选定探针内的`cancel-async-tasks`运行nop/oracle，得到nop=0、oracle=1，exception均空，控制通过。先前追加控制与SWE共享app内使用同名nop而触发AlreadyExistsError；没有模型评分。控制脚本已使用输出路径hash命名，新的有效收据放`verifier-controls-v2/tb21-cancel-async-tasks/validation.json`。

诊断安装日志确认planarity=1.0.0、networkx=3.6.1、pyknotid=0.5.3；仅记录出错组合，未测试降级解法。

异常原始证据保留：`verifier-controls/tb21/oracle`、`diagnostic-results/tb21-build-cython-stdout`。该参考解问题单独注记，不修改固定三模型探针题目，不根据模型分数挑题。
