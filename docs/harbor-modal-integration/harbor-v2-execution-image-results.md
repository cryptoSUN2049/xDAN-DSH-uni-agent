# DSH Session v2 Harbor 镜像验证

2026-09-08：新版 Linux amd64 镜像离线构建、真实 SDK 启停、真实 Harbor setup 均以退出码 `0` 完成。SDK 与 runtime 实测均为 `0.1.3a2`。这批验证没有发出模型请求，没有运行任务 rollout、verifier 或训练。

## 版本与输入来源

- DSH：`b2369692ea530007075ebcd18d39fdba0bbd3982`，源码版本 `0.1.3-alpha.2`，Python 分发版本 `0.1.3a2`。
- 8 个 Uni-Agent helper、Dockerfile、keyless 检查脚本：固定 Git `1263ff59bfd06a36bf99122694de0df5869370ba`。逐文件与 `git show` 比较一致；容器和当前宿主 runner 均为 `sha256:a122de903b1775231f6ff6f70762b78500819d6c9ce8a3323b729dac64468732`。
- 远端来源：`/workspace/artifacts/dsh-g1-v2-b236969`。SSH 仅传回两个 wheel，未传回 DSH 源码；runtime executable 和 rg 随 runtime wheel 携带，解包读取后分别校验 SHA256。
- 新外部 context：`/private/tmp/dsh-harbor-image-v2-1263ff5`，新建私有目录。五个第三方 wheel 复用 `/private/tmp/dsh-harbor-image-eb536fb/wheelhouse`，逐个与旧 manifest 校验一致。
- Python base：`python@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`；Docker client/server `29.2.0`；Harbor `0.16.1`。
- 本机 Docker Desktop 的 ARM64 宿主以 amd64 仿真运行。这里证明功能可启动，不提供性能结论。

| 输入 | 版本 | SHA256 |
| --- | --- | --- |
| deepseek-harness-runtime-bin wheel | 0.1.3a2 | `59cc8ec59946afa572bfd0b9e6268d7380a4d00d1157d7dce6d2b2df86cf51ad` |
| deepseek-harness-sdk wheel | 0.1.3a2 | `6c6a1a8f26b9030326447a8ed41c3ae6261a6b78e7fe61d72c7bf3ae21f03d6e` |
| runtime executable | b236969 | `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb` |
| runtime rg | wheel 内附带 | `193906679498de4d939345b937fa24e0e69a03c244bd70c859f5e41232713f21` |
| annotated-types | 0.7.0 | `1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53` |
| pydantic | 2.12.5 | `e561593fccf61e8a20fc46dfc2dfe075b8be7d0188df33f221ad1f0139180f9d` |
| pydantic-core | 2.41.5 | `eceb81a8d74f9267ef4081e246ffd6d129da5d87e37a77c9bde550cb04870c1c` |
| typing-extensions | 4.15.0 | `f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548` |
| typing-inspection | 0.4.2 | `4ed1cacbdc298c220f1bd249ed5287caa16f34d44ef4e9c3d0cbad5b521545e7` |

19 个 context 文件的 SHA256、镜像 ID 和证据文件 SHA256 记录在 [当前镜像 manifest](../../deployment/versions/harbor-execution-image.json)。旧 manifest 可从 `1263ff5:deployment/versions/harbor-execution-image.json` 读取；旧 context、旧镜像与原 keyless/setup 报告均保留。

## 实际执行

```sh
docker buildx build --platform linux/amd64 --network=none --load \
  -f /private/tmp/dsh-harbor-image-v2-1263ff5/Dockerfile \
  -t uni-agent-dsh:0.1.3a2-1263ff5-amd64 \
  /private/tmp/dsh-harbor-image-v2-1263ff5

docker image inspect uni-agent-dsh:0.1.3a2-1263ff5-amd64 \
  --format '{{.Id}} {{.Os}}/{{.Architecture}}'

docker run --rm --name dsh-harbor-v2-keyless-1263ff5 \
  --platform linux/amd64 --network none \
  sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97 \
  python /opt/checks/keyless_sdk_smoke.py

PYTHONPATH=. /private/tmp/harbor-h0-20260908/bin/python \
  deployment/checks/harbor_dsh_setup_smoke.py \
  --image sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97 \
  --output /private/tmp/dsh-harbor-v2-setup-1263ff5
```

复跑使用新的输出目录与容器名。构建命令的 `--network=none` 限制 RUN 阶段；base image 的解析仍经过 Docker/BuildKit。本次依赖安装使用 `--no-index` 和已经验证的七个 wheel，`pip check` 通过。

| 检查 | 结果 | 原始证据 |
| --- | --- | --- |
| amd64 build + 离线安装 + pip check | exit 0 | [build log](harbor-v2-image-build-log.txt) |
| image inspect | `linux/amd64`，ID 见下方 | 当前镜像 manifest |
| 真 SDK initialize/shutdown | exit 0；两分发 `0.1.3a2`；runner hash 匹配 | [keyless JSON](harbor-v2-keyless-sdk-result.json) |
| Harbor DockerEnvironment + DshHarborAgent setup | exit 0；`patches=[]`；`model_called=false`；`cleanup_completed=true` | [setup JSON](harbor-v2-dsh-setup-result.json) |
| 宿主 Docker 独立清理核查 | 4 条查询均 exit 0、返回空 | [cleanup JSON](harbor-v2-image-cleanup-result.json) |

当前本地镜像 ID：`sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97`。

Harbor setup 使用 `network_mode: none`、2 CPUs、2 GiB RAM、180 秒总超时；使用真实 SDK 启动流程，无 session prompt。专用 Compose project 为 `dsh-setup-cbb47266b7ab`。测试 finally 清理完成后，又按该 project label 查询容器、网络和卷；keyless 容器按固定名字单独查询，全部无残留。

## 推进边界

镜像已能用于下一批新版任务验证，当前仅存在本机 Docker，没有推送 registry。本批未修改 task manifest；任务的 image 引用与内容摘要应作为同一批任务 release 更新，然后运行新版独立 verifier 和真实学生 rollout。旧版成功记录不能作为新版的 reward 或训练证据。远端 installed-wheel minimal/restart 的既有成功记录属于另一批验证，本报告没有重跑或扩大其范围。
