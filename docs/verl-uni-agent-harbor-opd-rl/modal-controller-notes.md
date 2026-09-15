# Modal controller integration notes

Read-only audit of the existing controller/worker path, 2026-09-15. This document distinguishes current code from proposed transport extension. No remote resources were created.

## Current complete call path

1. `deployment/services/harbor_run_controller.py:RunSpec` freezes run/task/policy paths, worker and registration credentials, SSH host/key/known-hosts, and five local/remote ports. It forbids unknown fields. Its canonical digest becomes `run_spec_sha256`.
2. `RunController.start` opens the control SSH tunnel. GPU-side registration and worker HTTP requests reach controller-side loopback services through `-R 127.0.0.1:<remote-control/worker>:127.0.0.1:<local-control/worker>`.
3. Registration binds the runtime Gateway port to the frozen Gateway IP. `register` opens `-L 127.0.0.1:<model_port>:<policy.gateway_host>:<registered_port>`, saves effective policy, starts the worker, then emits the registration receipt.
4. `start_worker` constructs `HarborWorker` in the controller process. **It does not invoke `deployment/services/harbor_worker.py`**; that file is a separate standalone CLI using the same worker class. Both entrypoints therefore need transport-option parity.
5. Controller currently hardcodes `gateway_base_url=http://host.docker.internal:<model_port>`. `HarborWorker.__init__` also explicitly rejects every other origin.
6. `HarborWorker._run` appends the immutable `request.model_route.session_path` and calls its executor. `execute_job` already accepts HTTP or HTTPS mapped URLs, requiring the exact session path and forbidding credentials/query/fragment.
7. The executor still constructs `environment.type=docker`. `isolated_trial` admits Docker only; independent cleanup inventories Docker containers, networks and volumes for both agent and verifier sessions.

## Can logical policy stay unchanged?

Yes. The policy's `gateway_host`, dynamically registered `gateway_port`, `model_name`, `tunnel_alias`, and exact session path describe the trusted logical model route. They need not become the externally reachable URL. Note the hostname constraint is a **specific IP**, not inherently localhost; registration/worker control HTTP listeners and SSH forwarded listeners are loopback.

An operator-owned HTTPS origin can map to the same registered Gateway while retaining the same request/receipt route contract. However, changing only the origin string is not enough: **a functioning HTTPS reverse proxy/tunnel must forward to that exact registered Gateway port and preserve the complete session path**. An arbitrary Modal endpoint is not evidence that this mapping exists. Today the model SSH listener is loopback on the controller host and is unreachable from a remote sandbox.

Keep controller/worker control traffic on the existing private SSH path initially. Add a separate model-ingress transport for sandbox-to-Gateway requests; bind its configuration and lifecycle to the run. The existing controller assumes `self.model.start/alive/close`; an operator-owned model transport implementation can satisfy that interface while the default stays `SshTunnel`.

## Minimal operator fields and forwarding boundary

Proposed names, not existing API:

- `RunSpec.environment_type`: explicit `docker` default or `modal`; never supplied by Student task kwargs.
- `RunSpec.gateway_origin`: explicit approved HTTPS origin for Modal, no path/query/fragment/userinfo. Docker retains its fixed host-mapping origin.
- A frozen ingress mapping descriptor/identity: origin, registered logical Gateway target, transport ownership and readiness. If provided by a separately operated service, require its pinned target and test it after registration. Do not label an unrelated `SshTunnel.alive` check as HTTPS ingress readiness.
- `RunSpec.registry_image_ref` or equivalent environment image identity: immutable registry repository reference plus digest, kept separate from runtime binary SHA.

Forward through **both** `start_worker` and standalone `harbor_worker.py` into `HarborWorker`, then explicitly into the executor. Default Docker options must remain unchanged. The canonical RunSpec digest naturally changes when these fields change; regenerate trainer registration config rather than reuse old registration receipts.

Credentials for Modal/registry belong to the operator environment or secret provider, not dataset rows or the frozen task's source files. Existing code has no API for authenticating a new HTTPS ingress: authentication support must be explicit if required; URL userinfo/query credentials are already forbidden.

## Frozen image/task changes that are unavoidable

`DshRelease.image_digest` currently accepts only `sha256:<64 hex>`, and executor plus `prepare_m2_training` require literal equality with `task.toml [environment].docker_image`. Existing artifact `deployment/versions/harbor-execution-image.json` records a local Docker image ID and `registry_published=false`. That artifact must not be reinterpreted as a registry manifest digest.

A registry-aware implementation must choose and enforce one clear identity contract:

1. Store an immutable `repository@sha256:<manifest>` reference in the frozen task and introduce a matching release reference field while retaining the actual digest separately; or
2. Keep the existing release digest field but define it explicitly as the registry manifest digest for the new release, carry the repository reference in operator config, and verify the task reference against that exact pair instead of the current string equality.

Either approach requires a new frozen release/task manifest, updated TaskRef content digest, policy template, canonical RunSpec digest, and regenerated prepared trainer inputs. Preserve `source_sha`, SDK SHA, **runtime binary SHA**, profile and patch byte/path identities as independently verified values. Do not substitute image digest for runtime/environment binary digest in existing verifier metadata.

Verifier image and task Dockerfile must also be remotely reproducible. `prepare_t2_task.py` currently writes a Dockerfile based on a local-only parent tag and a comment explicitly forbidding pulling it; that local build source cannot be assumed available in Modal. Freeze a registry-accessible parent/verifier image or prebuilt final image and recalculate task hashes. Preserve separate verifier isolation and answer-transfer checks.

## Reusable prepare sources

- `examples/harbor/prepare_t2_task.py`: packages the public dev-01 task, patch, verifier code and sidecar manifest. Its local-image assumptions above require extension for Modal.
- `examples/harbor/prepare_evolution_task.py`: packages frozen evolution source data and bindings; preserves original runtime digest separately from image identity.
- `examples/harbor/prepare_m2_training.py`: authoritative conversion from RunSpec plus frozen task into private task YAML, training/heldout rows, registration and postprocessor inputs. Extend its release/image check consistently; do not create a parallel permissive preparer.
- `deployment/bootstrap/prepare_harbor_context.py`: builds the image context from an explicit source closure. Pair with a new versioned image manifest after actual registry publication/verification.
- `deployment/versions/harbor-execution-image.json` and `docs/harbor-modal-integration/harbor-v2-execution-image-results.md`: historical image/build evidence; not Modal or registry-pull evidence.

## Remaining executor responsibilities

Backend choice must reach both agent and independent verifier environments. Replace Docker-specific answer extraction/cleanup inventory only for Modal, with real resource identity and independent termination verification; do not skip checks based on backend. Preserve budgets/deadline, fixed local task admission, bounded artifacts, verifier authenticity, and original request session/receipt binding.

The shortest complete integration therefore retains Uni-Agent/Teacher/TQ/VERL and the existing controller/registration/worker contract, adding a backend-specific environment plus owned external Gateway mapping and a new frozen registry image release. It does not require moving the trainer or controller into Modal.
