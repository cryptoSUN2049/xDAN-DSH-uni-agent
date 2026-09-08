# 原生 memory A→freeze→B 最小评估链手册

状态：CPU实现完成，真实学生A/B尚未执行。两族constraints/updates；单次一族一chain，先constraints。无SFT/RL更新，无新checkpoint，credit_assignment=none。

## 固定与预算

- DSH SDK/runtime0.1.3a2，运行模式exe；已验收runtime SHA `sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- Python `/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python`；从即将提交的新源码checkout运行。准备清单记录所有相关代码/部署锁文件hash，执行前后拒绝变化。
- checkpoint_identity为operator提供的模型身份引用；脚本固定model_path，实际权重来源/hash由主线model/launch锁证明，不能把任意标签称为已验证权重摘要。
- 1 GPU，TP1，1 Gateway，并发1，n=1；vLLM，hermes parser（本recipe针对Qwen3 4B），max_model_len16384，GPU memory utilization0.6。
- temperature0、top_p1；max_total_tokens8192、max_tokens_per_turn4096，reasoning_effort=off。
- 每stage墙钟1800秒，现有owned process-group supervisor TERM宽限30秒，必要KILL/最终wait5秒。成功/失败均产生真实supervisor结果，process-exit绑定chain/role/run目录/manifest/argv/supervisor hash。禁止全局Ray清理。两stage一次chain最大约61分钟，实际诊断预计远低于上限；任何A失败不启动B。
- 监督复用既有harbor_training_supervisor的通用进程组函数，health为本地no-op，不连接Harbor；日志名train.log是旧监督器命名，本次命令明确运行inference模块。

## 命令（先由主线程确认GPU空闲与当前源码commit）

所有命令在选定checkout根目录，环境`DSH_RUNTIME_MODE=exe`、`PYTHONPATH=.:verl`。以下MODEL_PATH与CHECKPOINT_ID必须替换为当前已固定模型；新目录不可复用。CLI不自动购买/启动GPU。

```sh
python -m examples.dsh.capabilities.memory_chain prepare-writer \
  --output-dir /root/runs/dsh-memory-constraints-r1 \
  --chain-id memory-constraints-r1 --family constraints \
  --runtime-executable /workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64 \
  --environment-digest sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb \
  --runner-python /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  --model-path MODEL_PATH --checkpoint-identity CHECKPOINT_ID

python -m examples.dsh.capabilities.memory_chain run-stage \
  --manifest /root/runs/dsh-memory-constraints-r1/chain.json --role writer

python -m examples.dsh.capabilities.memory_chain freeze-and-prepare-reader \
  --manifest /root/runs/dsh-memory-constraints-r1/chain.json

python -m examples.dsh.capabilities.memory_chain run-stage \
  --manifest /root/runs/dsh-memory-constraints-r1/chain.json --role reader

python -m examples.dsh.capabilities.memory_chain finalize \
  --manifest /root/runs/dsh-memory-constraints-r1/chain.json
```

首条prepare为CPU操作；run-stage真实调用模型。分步确认返回码，不盲目跳过失败继续。每stage生成`inference.argv.json`可review完整参数；不要自行改参数/配置后绕过hash门。run-stage会校验实际SDK/runtime package与binary路径；变量不匹配即拒绝启动。

## 验收与查看

- `writer/run/supervision/{train.log,supervisor-result.json}`：模型推理日志与owned进程终态。
- `writer/run/process-exit.json` + `inference-evidence.json` + `artifacts/results/*/verifier-receipt.json`：A完整运行、fresh/hash/身份及评分依据。reader对应路径相同。
- A必须完成、eligible且reward1，确实成功读取来源并用工具写入合格普通memory文件；之后控制端冻结`frozen/{memory.bin,manifest.json}`，生成B任务。
- B必须新Gateway/DSH session，真正读交接与问题、答案事实正确，且没有越界动作。B只读白名单，不见A对话/来源/回执。输出合格`chain-result.json`才算这一条评估链完成。
- 单session原Task回执原样保留；chain回执引用A/B，不拼接token、不把B reward赋给A。
- 合法答错为零分；unfinished/身份或文件篡改拒绝。失败产物不删除、不自动重试、不复用旧目录。

## 本轮验证范围

CPU测试覆盖两个任务族的完整合成回执链、独立verifier环境接口、A失败不freeze、B身份/manifest/content篡改、合法零分/未完成/越界、配置/运行时改动拒绝、同目录重跑拒绝，以及实际CPU owned子进程墙钟终止。合成回执仅用于tests，绝不记为学生运行证据。

固定Linux无模型policy canary已独立通过；本轮未操作GPU或远程checkout。下一门为真实学生writer→freeze→reader。no-memory对照后续扩展，当前不能宣称记忆效果提升或跨会话RL训练成功。
