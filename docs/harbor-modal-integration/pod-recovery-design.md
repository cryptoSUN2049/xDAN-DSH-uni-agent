# RunPod 容器替换后的最小恢复设计

2026-09-10。本文件为只读代码/新Pod审计与主线程恢复实测汇总；子任务未安装软件、未改GPU配置。新端点216.243.220.120:13918，/workspace保留。

## 根因与已知环境

旧venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5` 的包仍在，但 `bin/python -> /usr/local/bin/python` 指向旧容器层；pyvenv.cfg也写 `home=/usr/local/bin`、CPython3.12.3、uv0.9.0。新容器Ubuntu22.04、系统Python3.11.10不能直接代替旧CPython3.12。

本次只读确认x86_64、glibc2.35；驱动580.126.16。`nvidia-smi -L`显示RTX PRO6000上的 **MIG 2g.48gb**，不是旧97GB完整GPU。GPU级memory.total查询返回Insufficient Permissions；/dev/nvidia0缺失但nvidiactl/nvidia-uvm存在，这不单独证明CUDA不可用，最终必须以旧venv内CUDA实际可见device和分配/计算为准。

主线程已实际恢复固定uv0.9.0至 `/workspace/tools/uv-0.9.0`，设置 `UV_PYTHON_INSTALL_DIR=/workspace/tools/uv-python`安装CPython3.12.3。**只修解释器symlink仍报标准库encodings缺失**，原因是pyvenv.cfg旧home导致base_prefix/stdlib解析错误。主线程已保留 `pyvenv.cfg.before-pod-20260910` 并将home指向持久解释器bin；后续主线程已完成实际CUDA探针，结果见下文。

## 现有部署缺口

- `deployment/bootstrap/install-verl.sh`会直接uv sync --frozen，缺固定uv版本、持久Python与损坏venv诊断；不适合将本次完整旧venv当新环境立即重装。
- `native-work-state-end-to-end-runbook.md`新环境示例使用 `/usr/bin/python3.12`，仍位于容器层。
- g1-deployment-lock记录Python3.12.3，但解释器构建来源/归档SHA与uv二进制未形成独立恢复锁。相同Python版本不等于完全相同解释器构建物。

## 幂等恢复顺序

1. 只读盘点：挂载、目标venv/pyvenv.cfg/symlink、持久解释器与uv、源码锁、原包metadata、运行进程、GPU可见资源。先检查目标路径可写和权限，不递归chmod/chown整个卷。
2. 已有uv能运行且版本为0.9.0则复用；否则只补固定工具到专用持久目录。已有CPython3.12.3可运行则复用，否则只补解释器。记录完整下载来源/构建标识/摘要；不升级到浮动3.12最新版本。
3. 旧venv只做必要解释器恢复：先备份配置/链接，再将venv解释器直接指向持久解释器，并同步pyvenv.cfg的home；运行探针核sys.executable、sys.prefix、sys.base_prefix、sys.version、sysconfig标准库路径与encodings导入。不要只检查symlink存在。已有兼容可用配置保持不动，避免影响其他venv或共享容器全局python。
4. 隔离导入检查：清理旧PYTHONHOME/PYTHONPATH影响，核numpy/torch/vllm/verl/uni-agent及DSH SDK/runtime版本与实际来源；复用时用明确当前固定checkout的PYTHONPATH，记录editable仍可能指旧checkout。先uv pip check，不自动uv sync覆盖所有现存依赖。
5. 动态库检查：按失败模块/二进制执行ldd，定位实际missing soname，再安装最小缺包；glibc2.35满足DSH manylinux2_28下限，但不能替代逐模块导入。驱动libcuda来自宿主注入，不在容器里重装宿主驱动；torch自带CUDA用户态库也不等于需要先安装整套CUDA toolkit。
6. CUDA准入探针（主线程执行）：实际device_count、设备名、capability、total_memory、CUDA版本，最小张量分配与计算后释放；记录MIG UUID和约48GB可用资源。nvidia-smi权限警告不能直接当CUDA失败；也不能把母卡名称当97GB资源承诺。
7. 源码/runtime/canary复核后才恢复任务。原97GB配置在48GB MIG上的可行性重新验收，必要资源参数变更另存新run配置并记录，不改旧实验manifest。绝不更改MIG分区或宿主权限来强占另一slice。
8. 仅当证据证明旧venv缺包/不兼容且无法最小恢复时，创建新专用venv，使用固定持久Python与现有uv.lock/overlay安装；保留旧venv供回溯，不先删除重建。

## 后续最小脚本改动（本轮未实现）

拟新增 `deployment/bootstrap/recover-persistent-python.sh`：检查优先、精确工具/解释器版本、只补缺失、配置备份、prefix/stdlib探针、记录恢复报告；默认不全量安装训练依赖，不覆盖任意现存解释器。

拟扩 `deployment/checks/preflight.py`：输出解释器实际解析路径/base_prefix、GPU或MIG真实CUDA可见容量、精确缺库信息；GPU信息读取失败与CUDA计算失败分开。

拟修部署runbook：持久解释器路径、旧环境恢复/新环境安装互斥、MIG预算独立验收。install-verl.sh后续增加uv/Python版本门，但保留原锁和overlay，不以恢复为由更新依赖。

## 验收

同Pod再次执行恢复检查无额外改动；Python/标准库与固定包能正常导入；原model/checkpoint/runtime摘要保持；实际CUDA设备探针通过；DSH canary与新任务预检通过。以上每项需实际报告，不能由包文件存在或nvidia-smi列表替代。当前本文仅确认根因、只读设备事实和主线程已报告的解释器修复边界。

## 本次恢复命令与实际验收补录

以下对应本次已执行的恢复动作。**下次必须先检查存在且可用，只有缺失才安装或修复；不是每次启动都重跑安装。**

```bash
python3 -m pip install --target /workspace/tools/uv-0.9.0 'uv==0.9.0'
/workspace/tools/uv-0.9.0/bin/uv --version
UV_PYTHON_INSTALL_DIR=/workspace/tools/uv-python \
UV_CACHE_DIR=/workspace/cache/uv \
/workspace/tools/uv-0.9.0/bin/uv python install 3.12.3
```

实际持久解释器：`/workspace/tools/uv-python/cpython-3.12.3-linux-x86_64-gnu/bin/python3.12`。本次仅在`/usr/local/bin/python`缺失时创建了指向该解释器的链接，没有覆盖已有全局Python。随后备份并修正旧venv配置（只改原home行，其他字段不变）：

```python
from pathlib import Path
venv = Path('/workspace/venvs/uni-agent-rebuild-cf2d3f5')
config = venv / 'pyvenv.cfg'
backup = venv / 'pyvenv.cfg.before-pod-20260910'
old = config.read_text()
old_home = 'home = /usr/local/bin'
new_home = 'home = /workspace/tools/uv-python/cpython-3.12.3-linux-x86_64-gnu/bin'
if old_home in old.splitlines():
    if not backup.exists():
        with backup.open('x') as stream:
            stream.write(old)
    config.write_text(old.replace(old_home, new_home, 1))
else:
    assert new_home in old.splitlines(), 'Unexpected home; inspect instead of replacing blindly'
```

这段是可复操作逻辑，不替代解释器/bin链接和sys.base_prefix验证。恢复成功后不要再次修改或覆盖备份。

本次主线程实际通过：Python3.12.3且prefix仍旧venv；torch2.11cu130、CUDA available=true；DSH SDK/runtime0.1.3a2；真实32×32张量前向/反向finite。CUDA实际设备为MIG2g48gb，total_memory=50,868,518,912 bytes，不能继续按97GB预算解释。私有Git fetch通过，认证无需重配。

新checkout `/workspace/rebuild/uni-agent-core-242dcf0`。新Pod初次canary因`/root/runs`父目录不存在报FileNotFoundError；先`mkdir -p -m 700 /root/runs`后，`/root/runs/core-canary-newpod-r1`的8个真实runtime场景通过。创建父目录是恢复缺失目录，不重用已有正式run目录。

主线程随后进行core-train-r1准备/check/launch；训练结果不在本恢复报告范围，本子任务未启动GPU或修改环境。恢复证明原持久包环境可再次运行，不等于原97GB设备性能或新核心课程训练已经验收。
