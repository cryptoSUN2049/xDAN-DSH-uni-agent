# Harbor Session v2 镜像：固定源码与发布物复建

## 本批最小设计

新增纯 Python 标准库入口 `deployment/bootstrap/prepare_harbor_context.py`。输入固定完整 Git commit、可信 execution-image manifest、明确 artifact/cache 目录与全新输出目录；从 Git 对象读取白名单源码，按 manifest 验证指定 wheels，生成 `source-revision` 和 `wheelhouse/SHA256SUMS`。整个 context 的相对路径与文件 hash 必须精确匹配 manifest。脚本不联网、不运行 Docker，不读取工作树源码，不复制整个 checkout/cache。

契约：`prepare_context(repo, source_commit, manifest, artifact_dir, output) -> verification dict`。验证失败不宣称context完成；拒绝错误commit、错hash、symlink输入、未知路径、覆盖既有输出。测试用临时真实Git仓验证固定commit取值与dirty working tree隔离，再用现有真实wheel cache核验实际manifest。

本批复建的是 0.1.3a2 的镜像输入；不等于发布物已经上架，也不保证不同Docker版本生成完全相同image ID。镜像必须另行build、keyless boot与Harbor setup验收。

## 三个身份分别固定

- **交付 commit**：包含本脚本、使用文档及 `deployment/versions/harbor-execution-image.json` 的最终 GitHub commit，由发布会话记录。本批尚未提交，不能假装远端已有这些文件。
- **镜像 Python 源码 commit**：`1263ff59bfd06a36bf99122694de0df5869370ba`，对应 manifest.integration_revision。脚本通过 `git show` 读取该commit，因此交付checkout上的其他修改不会混进context。
- **DSH 源码 / Python wheels**：`b2369692ea530007075ebcd18d39fdba0bbd3982` / `0.1.3a2`。版本名相同不足以验收，两个wheel的bytes必须与固定manifest完全一致。

## 从固定 GitHub 交付恢复

将 `UNI_AGENT_DELIVERY_COMMIT` 设为发布记录中的完整40位commit，不使用浮动main代替。

```sh
UNI_AGENT_DELIVERY_COMMIT='<发布记录中的40位commit>'
UNI_AGENT_DELIVERY_ROOT=/srv/checkouts/uni-agent-delivery
git clone --no-checkout https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent.git "$UNI_AGENT_DELIVERY_ROOT"
git -C "$UNI_AGENT_DELIVERY_ROOT" checkout --detach "$UNI_AGENT_DELIVERY_COMMIT"
git -C "$UNI_AGENT_DELIVERY_ROOT" rev-parse HEAD
```

准备context只需要Git和Python标准库，不需要安装训练依赖或初始化VERL。执行训练的完整checkout则继续使用既有 `deployment/bootstrap/checkout.sh`。

## 发布物输入：Release 或明确本地 cache

本入口不自动下载。`--artifact-dir` 是平铺wheel目录，可由已验证cache或最终Release下载填充。脚本仅读取manifest指名的wheel，其他文件不会进入context；指定wheel缺失/损坏则拒绝。

**已发布到私有仓库的 prerelease：** [dsh-sdk-0.1.3a2-b236969-linux-x64](https://github.com/cryptoSUN2049/xDAN-DSH-Exp/releases/tag/dsh-sdk-0.1.3a2-b236969-linux-x64)。完整tag目标是上述b236969源码，5项asset已重新下载核验；访问需要该私有仓库权限。发布回执见 [dsh-v2-private-release-result.json](dsh-v2-private-release-result.json)。

```sh
DSH_RELEASE_TAG=dsh-sdk-0.1.3a2-b236969-linux-x64
DSH_ARTIFACT_CACHE=/srv/artifacts/dsh-0.1.3a2
mkdir -p "$DSH_ARTIFACT_CACHE"
gh release download "$DSH_RELEASE_TAG" --repo cryptoSUN2049/xDAN-DSH-Exp \
  --pattern 'deepseek_harness_sdk-0.1.3a2-py3-none-any.whl' \
  --pattern 'deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl' \
  --dir "$DSH_ARTIFACT_CACHE"
```

身份校验依赖独立固定的Git manifest，而非下载物旁边自行提供的SHA256SUMS。下载不需要将PAT写到URL、源码或Docker context；让gh使用已有认证。

其余5个wheel可来自已有cache，或显式下载固定版本（不安装）：

```sh
python3 -m pip download --only-binary=:all: --no-deps \
  --implementation cp --python-version 3.12 --abi cp312 \
  --platform manylinux2014_x86_64 --dest "$DSH_ARTIFACT_CACHE" \
  annotated-types==0.7.0 pydantic==2.12.5 pydantic-core==2.41.5 \
  typing-extensions==4.15.0 typing-inspection==0.4.2
```

无论何种来源，下一步会检查全部7个文件的准确名字与SHA256。重新构建wheel若产生不同bytes，应作为另一份新release验收，不能修改已有manifest以绕过失败。

## 生成 context，再离线构建

```sh
HARBOR_CONTEXT=/srv/builds/harbor-0.1.3a2-context
python3 "$UNI_AGENT_DELIVERY_ROOT/deployment/bootstrap/prepare_harbor_context.py" \
  --repo "$UNI_AGENT_DELIVERY_ROOT" \
  --source-commit 1263ff59bfd06a36bf99122694de0df5869370ba \
  --manifest "$UNI_AGENT_DELIVERY_ROOT/deployment/versions/harbor-execution-image.json" \
  --artifact-dir "$DSH_ARTIFACT_CACHE" \
  --output "$HARBOR_CONTEXT" > /srv/builds/harbor-context-verification.json

docker buildx build --platform linux/amd64 --network=none --load \
  -f "$HARBOR_CONTEXT/Dockerfile" \
  -t uni-agent-dsh:0.1.3a2-1263ff5-amd64 "$HARBOR_CONTEXT"
docker run --rm --platform linux/amd64 --network none \
  uni-agent-dsh:0.1.3a2-1263ff5-amd64 python /opt/checks/keyless_sdk_smoke.py
```

`/srv/builds`需预先建立；context必须是全新目录。基础镜像摘要固定在Dockerfile；首次取基础镜像仍需要registry或已有cache，`--network=none`限制build步骤网络而非基础镜像解析。主机架构为ARM时显式使用amd64仿真。

源码、Dockerfile、检查脚本、source-revision、SHA256SUMS和所有wheels共19个文件都逐字节匹配manifest，成功才打印 `verified=true`。最终image ID、Harbor setup和资源清理仍须保存独立结果，不能仅凭context通过就宣称训练完成。

## 本批核验记录

7项CPU测试通过，包括dirty working tree不影响固定源码、错wheel/commit/hash、symlink、未知路径和已有输出拒绝。另以当前真实7-wheel cache运行新脚本，生成全新context，19个文件准确匹配Session v2 execution-image manifest。本次复用了已存在的wheel cache，没有联网下载、重新build镜像或调用模型；最终入口不依赖该临时cache位置，可接受任意明确artifact目录。

## 私有发布验收（2026-09-08）

GitHub确认repository visibility为private，发布为prerelease且非latest，tag目标完整匹配b236969。上传SDK/runtime双wheel、原始build-info.json、独立release-manifest.json与相对文件名SHA256SUMS。先draft上传，再将5个asset全部下载到新目录逐字节校验，通过后发布；发布后的GitHub asset digest再次与本地SHA256一致。原始build-info保留打包时的status，后续安装/Harbor验证范围写在release-manifest和说明中。未上传秘密，未覆盖已有Release，未修改运行中的模型/任务manifest。
