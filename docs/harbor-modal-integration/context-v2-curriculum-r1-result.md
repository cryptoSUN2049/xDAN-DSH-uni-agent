# Context v2 课程：训练终态与 step12 reload 准备

训练remote固定 `d3084f2a771804f011c4e641ecf0986c7166bc86`，旧验收venv；supervisor exit0，1000.024秒。已结束后使用 CUDA_VISIBLE_DEVICES=''、OMP/MKL各2线程完成CPU审计，未修改checkout或启动GPU。

## 实际结果

- trainer完成12个有效batch，48个唯一训练消费key；**只覆盖11个唯一train任务**。D3在step5有一个失败sibling（该组只3个trajectory dump），strict整组拒绝；有界refill后D2共消费两组/8条。不能写成“12题均成功消费”。
- 共64个session目录：52次train尝试、12次dev尝试；63个trajectory dump，缺的一个是step5 rollout3。实际train dump51，消费48；拒绝组3个已生成轨迹未消费。此计数依据session目录与dump/消费key交叉，不把不存在的失败轨迹补造出来。
- 原生audit：24/25组eligible、1 rejected；eligible=false原样保留。unexpected_consumed=0、legacy_unjoinable=0。因正常strict拒绝和refill补齐12有效batch，过程可完成；仍不满足“全组无失败/全部唯一题覆盖”的验收。
- step3/4/5/7/10/12存在非零advantage和非零grad，共6步。其余6步同分组adv/grad=0。
- dev step0/6/12各4题、严格成功均0/4，平均reward均0.3979687579。没有开发集效果提升证据，更没有封存泛化结论。
- CPU step6→12：504/504 LoRA张量变化，399/399 base张量不变，全部有限，delta passed。它证明这两checkpoint之间真实更新，不代表起始→最终效果提升。

证据：`context-v2-curriculum-r1-result.json`、`context-v2-curriculum-r1-consumption-audit.json`；完整张量delta在remote run/checkpoint-delta-6-12.json。失败sibling尚未从独立日志定位具体异常，不能把group_size_mismatch本身当底层根因。

## 独立 reload 启动与预检副作用

- data `/root/runs/context-v2-curriculum-r1-reload-data`，由同一个v2准备器新生成；4dev身份，新run绑定。
- run `/root/runs/context-v2-curriculum-r1-reload-step12`，PRINT_COMMAND随后创建了该目录中的command.txt/run-manifest.json，导致首次正式启动被新目录检查拦截。
- plan `/root/runs/context-v2-curriculum-r1-reload-plan`：preparation-audit.json、launch-environment.json、training.argv.json、supervisor.argv.json、print-command.txt。
- checkpoint `/workspace/uni-agent-g1/checkpoint/context-v2-curriculum-r1/global_step_12`；VAL_ONLY=True、resume_path、n1、4dev，wall3600秒/grace30，独占短Ray目录 `/tmp/dsh-cv2r12`。
- 源码/数据hash、跨cwd verifier import、checkpoint目录、PRINT_COMMAND通过；清除RAY_ADDRESS/PYTHONHOME/旧CUDA alloc设置。源pin/SDK/runtime模型同原run，未更新checkout。准备清单副本为 `context-v2-curriculum-r1-reload-preparation.json`。

以下为首次启动命令记录，不可重复执行。首次PID178761在预检退出；root确认只有两份打印证据后，将目录原样重命名为同级 `context-v2-curriculum-r1-reload-step12-print-command-evidence`，重试使用supervisor-retry1.log/PID178933。已确认重试监督存活并生成真实supervision/train.log，模型加载/结果待核实。

```python
import json, pathlib, subprocess
plan = pathlib.Path('/root/runs/context-v2-curriculum-r1-reload-plan')
argv = json.loads((plan / 'supervisor.argv.json').read_text())
with (plan / 'supervisor.log').open('xb') as log:
    child = subprocess.Popen(
        argv, cwd='/workspace/rebuild/uni-agent-native-n0-r1',
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root',
             'CUDA_VISIBLE_DEVICES': '', 'PYTHONUNBUFFERED': '1'},
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
(plan / 'supervisor.pid').write_text(str(child.pid) + '\n')
print(child.pid)
```

此命令在GPU主机用旧venv Python执行。supervisor入口重新检查git/model/runtime/input哈希、短目录与run不可复用，然后给子进程明确CUDA0；父进程CUDA空不等于子进程未使用GPU。reload需确认没有训练loss/optimizer step或新checkpoint，4组fresh dev消费与回执合格，结果另记录；本报告不预先宣称reload通过。
