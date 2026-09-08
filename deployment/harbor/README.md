# Minimal Harbor DSH task image

This image runs the existing DSH helper inside a Harbor-owned environment.
Harbor and its bridge stay on the Mac; VERL/model stay on the GPU host.
Build and run explicitly as `linux/amd64`. Mac ARM64 uses Docker Desktop
emulation, suitable for functional verification rather than throughput claims.

## External context

Prepare a separate directory without credentials containing:

- `wheelhouse/`: SDK and Linux x86_64 runtime wheels built from DSH
  `b2369692ea530007075ebcd18d39fdba0bbd3982`, both `0.1.3a2`; Pydantic `2.12.5`
  and all its transitive dependency wheels for Python 3.12 amd64.
- `wheelhouse/SHA256SUMS`: every wheel's SHA256, with filenames relative to that
  directory. Include exactly one approved version per dependency, no unrelated
  wheels. Archive this manifest with the build evidence.
- The eight `uni_agent/` files explicitly named by the Dockerfile, copied
  unchanged from a recorded Git commit. Record source hashes; host bridge and
  image must have identical `runner.py` bytes.
- `checks/keyless_sdk_smoke.py`, copied from the checkout's
  `deployment/checks/keyless_sdk_smoke.py`.

The Dockerfile validates checksums and installs offline, without installing the
training framework. The manifest must come from a trusted context producer;
checksums packaged alongside untrusted wheels do not establish provenance.
Distribution name is `deepseek-harness-runtime-bin`; import module name is
`deepseek_harness_runtime`.

## Build and keyless verification

From this worktree, replacing the context path:

```sh
docker buildx build --platform linux/amd64 --network=none --load \
  -f deployment/harbor/Dockerfile \
  -t uni-agent-dsh:b236969-amd64 /absolute/path/to/prepared-context
docker image inspect uni-agent-dsh:b236969-amd64 \
  --format '{{.Id}} {{.Os}}/{{.Architecture}}'
docker run --rm --platform linux/amd64 --network none \
  uni-agent-dsh:b236969-amd64 python /opt/checks/keyless_sdk_smoke.py
```

Base-image resolution may require registry access before offline build. Archive
the image ID and smoke JSON. The smoke imports real packages, resolves the
bundled executable, initializes `sdk-minimal`, and shuts down. It uses a dummy
key, unreachable loopback model endpoint, and no `session_prompt`/`harness.run`.
Docker `--network none` supplies the additional network boundary. Success proves
SDK boot only, not a rollout, terminal verifier, or training update.

This recipe now targets Session v2. The existing `harbor-execution-image.json`
and M2 task digest describe the previously verified 7840 image until the new
image is actually built and tested; do not replace those hashes with guessed
values. Promote the new image and regenerate the task release together after
verification. Historical results retain their original version identities.

## Harbor use

Set the task environment's `docker_image` to the built image; use an immutable
digest for shared execution. Harbor 0.16.1 supports an
`environment/docker-compose.yaml` or `extra_docker_compose_paths` override:

```yaml
services:
  main:
    platform: linux/amd64
```

Harbor owns environment start/stop. Its DSH bridge checks the preinstalled
SDK/helper and borrows the environment. Supply the model name and full Gateway
session URL explicitly. Real rollouts require the container-to-Mac SSH-forward
route; container localhost is not Mac localhost. Validate that route separately.

Real boot may expose missing dynamic libraries or emulation delays; bridge
setup currently has a 30-second timeout. Tasks requiring Git, compilers, or
test runners must declare them in their own reproducible images. This base
only supplies Python, SDK/runtime, and the DSH helper.

## Verified local execution (2026-09-08)

Inputs and image ID are frozen in `deployment/versions/harbor-execution-image.json`.
The actual amd64 image built offline; network-free SDK initialize/shutdown passed.
Harbor setup also passed using the real environment and matching runner SHA256:

```sh
PYTHONPATH=. /private/tmp/harbor-h0-20260908/bin/python \
  deployment/checks/harbor_dsh_setup_smoke.py \
  --image sha256:9ab3e43d3c3c35070668d1d0fca60e31516727df431f00aedfd875479855fb37 \
  --output /absolute/path/to/new-output
```

The setup check has a 180-second deadline, two CPUs, 2 GiB RAM and no network.
It deletes its own Harbor environment in `finally`. Reports are in
`docs/harbor-modal-integration/harbor-keyless-sdk-result.json` and
`harbor-dsh-setup-result.json`. No model rollout or training is claimed.
The image currently exists only in local Docker; no registry publication is claimed.

## Model-route transport probe

```sh
python3 deployment/checks/harbor_model_route_probe.py \
  --ssh-host root@216.243.220.244 --ssh-port 14682 \
  --ssh-key ~/.ssh/id_ed25519 \
  --image sha256:9ab3e43d3c3c35070668d1d0fca60e31516727df431f00aedfd875479855fb37 \
  --output /absolute/path/to/new-route-report.json
```

This starts a short-lived HTTP probe on the remote node and preserves the full
Gateway-shaped session path through a Mac loopback-only SSH forward. It does not
start Gateway or call the model. Actual transport passed; use a new output path.

## Independent verifier smoke

```sh
PYTHONPATH=. /private/tmp/harbor-h0-20260908/bin/python \
  deployment/checks/harbor_isolated_verifier_smoke.py \
  --task-dir examples/harbor/m2-file-write --output /absolute/path/to/new-trials
```

This uses the local execution image and builds a separate fixed Ubuntu verifier
image. Real oracle/nop/agent-score-forgery cases returned 1/0/0, with no agent
host mounts. The host verifier hash stayed unchanged. The overall deadline is
720 seconds, with 240 seconds per trial. It does not call a model.
