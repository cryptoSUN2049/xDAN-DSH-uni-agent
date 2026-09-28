# MiMo DSH image deployment

The MiMo task image remains the base. The DSH layer installs standalone CPython
3.12 and the locked SDK/runtime under `/opt/dsh`; it does not install into the
task's Python, replace task dependencies, or prepend to the task's PATH.
The agent invokes `/opt/dsh/bin/python` explicitly. Release identity is fixed by
`deployment/harbor/mimo/dsh-release-lock.json`, including DSH 0.1.3a2,
revision `b2369692ea530007075ebcd18d39fdba0bbd3982`, wheel/binary hashes,
`sdk-minimal`, and an empty patch list.

## Remote-only workflow

Run the client on the remote CPU host. Do not build, download large assets, or
run these checks on the development Mac.

1. `prepare_context` validates fixed image/asset identities and reads source
   files from an exact Git commit. Its output is explicitly `prepared_not_built`.
2. `remote_builder probe` starts a bounded CPU Modal VM, runs Docker, pulls the
   original digest, saves inspect evidence, and terminates the VM.
3. `remote_builder build` uploads only manifest-listed files, builds with Docker
   networking disabled, runs keyless SDK initialize/shutdown, pushes to private
   GHCR, pulls the resulting digest, repeats the smoke check, and emits a binding.
4. `remote_builder verify --published-image <repo@sha256:...>` rechecks an already
   published digest in a fresh VM without rebuilding or pushing. `--task-cwd`
   additionally records the original task's Python, Git, repository HEAD/tree,
   and working directory. It does not run task tests or model completions.

Use a fresh context/evidence directory for each attempt. CPU, memory and lifetime
are explicit CLI inputs. The client saves per-stage stdout/stderr and status,
handles termination signals, and terminates its owned sandbox in `finally`.
Run long clients under `nohup` on the remote host so SSH interruptions do not
discard work. The server-side sandbox lifetime remains the hard billing limit.

Registry credentials come from a private file outside the context. They travel
only through HTTPS request headers and Docker login stdin. The builder rejects
an existing nonprivate GHCR package, verifies the authenticated owner, and checks
private visibility after push. Neither registry credentials nor Modal credentials
belong in task bundles, image layers, source control, or task runtime secrets.

Harbor 0.16.1 pulls private images with
`TrialConfig.environment.kwargs.registry_secret`, containing only a Modal Secret
name. The named secret holds `REGISTRY_USERNAME` and `REGISTRY_PASSWORD`.
The operator config owns this name; an agent job cannot choose registry secrets.

## Docker normalization and execution semantics

Docker inspect may omit the `docker.io/` prefix from a DockerHub RepoDigest.
The check accepts only that prefix normalization while retaining the exact
repository and SHA-256 digest. A different repository with the same digest is
rejected.

An imported original image can have `Config={}`. Docker supplies its standard
Linux PATH at container execution; BuildKit may materialize that same value in
the derived image's `Config.Env`:

```
/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

The publication check permits **only** absent/empty original Env to this single
exact PATH entry, and only with fresh Docker runtime evidence that both pinned
images actually receive that exact PATH. The evidence binds both image digests;
its hash and the normalization kind are included in the final image binding.
A nondefault PATH, an additional environment variable, missing evidence, or an
image-identity mismatch is rejected. WorkingDir, Entrypoint, Cmd, effective User,
and every original filesystem layer must remain preserved.

Image acceptance proves a private, retrievable image, fixed DSH runtime/source
identity, and offline SDK boot. `gateway_route_verified` remains false: real
Gateway reachability, a rewarded task rollout, and VERL optimizer updates require
their own subsequent acceptance evidence.

## Accepted image: task 001661, 2026-09-28

The [final binding](evidence/mimo-image/image-binding.json) pins the private GHCR
image to `sha256:15f588d627ce06e17d2904193c07100aa0b73c883269d70565ab59f36f6f2952`.
The [fresh-VM verification status](evidence/mimo-image/status.json) records
`image_published_and_verified` and `terminated=true`; that VM used one CPU,
4096 MiB and a 180-second lifetime. No GPU was allocated.

The [runtime PATH evidence](evidence/mimo-image/runtime-environment.json) proves
the single documented normalization. The
[keyless result](evidence/mimo-image/keyless-readback.json) confirms the fixed
runtime binary, sidecar, runner source hash and SDK/runtime versions.
The original image has Python 3.12.13 at `/usr/local/bin/python3`, Git at
`/usr/bin/git`, and repository `/workspace/repo` with HEAD
`125729aed4a777af6ceb6ace5744f53db9d7933c` and tree
`450112c0a9d66c5797e4758a4f5a592969aa9dba`.

The release lock is a reusable unbuilt-input template; the per-task image
binding is the artifact that claims successful publication. Remote deployment
unit/regression checks passed 50 tests, followed by targeted Ruff check and
format gates. These are image/deployment checks, not an RL acceptance claim.
