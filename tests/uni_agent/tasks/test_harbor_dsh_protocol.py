import copy
import hashlib

import pytest

from uni_agent.tasks.harbor_dsh.protocol import (
    JobManifest,
    JobRequest,
    RequestPolicy,
    check_replay,
    request_sha256,
    validate_artifact,
    validate_manifest,
    validate_request,
)

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
HASH = "sha256:" + "a" * 64


def payload():
    data = {
        "schema": "dsh.harbor-job-request.v1",
        "job_id": "job-1",
        "idempotency_key": "idem-1",
        "run_id": "run-1",
        "group_uid": "group-1",
        "sample_index": 0,
        "partition_id": "train",
        "gateway_session_id": "session-1",
        "nonce": "ab" * 16,
        "task_ref": {"id": "file-write", "version": "v1", "sha256": HASH},
        "dsh_release": {
            "source_sha": "b" * 40,
            "sdk_sha256": HASH,
            "runtime_sha256": HASH,
            "image_digest": HASH,
            "platform": "linux/amd64",
            "profile": "sdk-minimal",
            "patch_sha256s": [],
        },
        "model_route": {
            "gateway_host": "10.0.0.2",
            "gateway_port": 45678,
            "session_path": "/sessions/session-1/v1",
            "model_name": "student-4b",
            "tunnel_alias": "gateway-1",
        },
        "budgets": {
            "deadline_unix": 1100.0,
            "wall_time_seconds": 100.0,
            "cpus": 1.0,
            "memory_mb": 512,
            "max_tokens": 4096,
            "max_artifact_bytes": 10000,
        },
    }
    data["request_sha256"] = request_sha256(data)
    return data


def policy(data):
    return RequestPolicy(
        task_refs=[data["task_ref"]],
        dsh_release=data["dsh_release"],
        gateway_host="10.0.0.2",
        gateway_port=45678,
        model_name="student-4b",
        tunnel_alias="gateway-1",
        max_wall_time_seconds=100.0,
        max_cpus=1.0,
        max_memory_mb=512,
        max_tokens=4096,
        max_artifact_bytes=10000,
    )


def manifest(request):
    return {
        "schema": "dsh.harbor-job-manifest.v1",
        "job_id": request.job_id,
        "request_sha256": request.request_sha256,
        "gateway_session_id": request.gateway_session_id,
        "nonce": request.nonce,
        "worker_id": "worker-1",
        "trial_id": "trial-1",
        "status": "succeeded",
        "sealed_at_unix": 1090.0,
        "artifacts": [
            {"id": f"obj-{index}", "kind": kind, "size_bytes": 3, "sha256": HASH}
            for index, kind in enumerate(("dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward"))
        ],
    }


def test_valid_request_and_canonical_hash_are_stable():
    data = payload()
    request = validate_request(data, policy=policy(data), now_unix=1000.0)
    assert isinstance(request, JobRequest)
    assert request_sha256(dict(reversed(list(data.items())))) == request.request_sha256
    assert request_sha256(request) == request.request_sha256
    assert check_replay(request, [request]) is True
    assert check_replay(request, []) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_id", "../escape"),
        ("run_id", "a/b"),
        ("nonce", "short"),
        ("partition_id", "eval"),
        ("sample_index", True),
        ("sample_index", -1),
        ("gateway_session_id", "session%2F1"),
        ("schema", "v2"),
        ("unexpected", "shell"),
    ],
)
def test_request_rejects_invalid_fields(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, "100"])
def test_budget_is_finite_positive_and_not_coerced(value):
    data = payload()
    data["budgets"]["wall_time_seconds"] = value
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


@pytest.mark.parametrize("path", ["/v1", "/sessions/other/v1", "/sessions/session-1/v1?key=x"])
def test_gateway_path_must_match_session_exactly(path):
    data = payload()
    data["model_route"]["session_path"] = path
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


def test_tampering_fails_even_when_structurally_valid():
    data = payload()
    data["sample_index"] = 1
    with pytest.raises(ValueError, match="hash"):
        JobRequest.model_validate(data)


@pytest.mark.parametrize("change", ["task", "release", "host", "port", "model", "tunnel", "budget", "expired"])
def test_operator_policy_rejects_unapproved_requests(change):
    data = payload()
    approved = policy(data)
    if change == "task":
        data["task_ref"]["sha256"] = "sha256:" + "c" * 64
    elif change == "release":
        data["dsh_release"]["profile"] = "sdk"
    elif change in {"host", "port", "model", "tunnel"}:
        key, value = {
            "host": ("gateway_host", "8.8.8.8"),
            "port": ("gateway_port", 443),
            "model": ("model_name", "teacher"),
            "tunnel": ("tunnel_alias", "other"),
        }[change]
        data["model_route"][key] = value
    elif change == "budget":
        data["budgets"]["max_tokens"] = 4097
    else:
        data["budgets"]["deadline_unix"] = 999.0
    data["request_sha256"] = request_sha256(data)
    with pytest.raises(ValueError):
        validate_request(data, policy=approved, now_unix=1000.0)


@pytest.mark.parametrize("collision", ["idempotency_key", "job_id", "nonce", "gateway_session_id"])
def test_replay_rejects_identity_reuse(collision):
    original = JobRequest.model_validate(payload())
    changed = payload()
    changed.update(job_id="job-2", idempotency_key="idem-2", nonce="cd" * 16, gateway_session_id="session-2")
    changed[collision] = getattr(original, collision)
    changed["model_route"]["session_path"] = f"/sessions/{changed['gateway_session_id']}/v1"
    changed["request_sha256"] = request_sha256(changed)
    request = JobRequest.model_validate(changed)
    with pytest.raises(ValueError, match="reused"):
        check_replay(request, [original])


def test_manifest_accepts_sealed_execution_without_interpreting_reward():
    request = JobRequest.model_validate(payload())
    result = validate_manifest(manifest(request), request=request, worker_id="worker-1")
    assert isinstance(result, JobManifest)
    assert not hasattr(result, "eligible")


@pytest.mark.parametrize("field", ["job_id", "gateway_session_id", "nonce", "request_sha256", "worker_id"])
def test_manifest_is_bound_to_controller_identity(field):
    request = JobRequest.model_validate(payload())
    data = manifest(request)
    data[field] = {"nonce": "cd" * 16, "request_sha256": "sha256:" + "c" * 64}.get(field, "other")
    with pytest.raises(ValueError):
        validate_manifest(data, request=request, worker_id="worker-1")


@pytest.mark.parametrize(
    "case", ["path", "id_path", "duplicate", "oversize", "missing", "unsealed", "bad_hash", "negative_size"]
)
def test_manifest_rejects_unsafe_or_incomplete_artifacts(case):
    request = JobRequest.model_validate(payload())
    data = manifest(request)
    artifact = data["artifacts"][0]
    if case == "path":
        artifact["path"] = "/tmp/agent/receipt"
    elif case == "id_path":
        artifact["id"] = "../receipt"
    elif case == "duplicate":
        data["artifacts"].append(copy.deepcopy(artifact))
    elif case == "oversize":
        artifact["size_bytes"] = 10000
    elif case == "missing":
        data["artifacts"].pop()
    elif case == "unsealed":
        data["status"] = "running"
    elif case == "bad_hash":
        artifact["sha256"] = "a" * 64
    else:
        artifact["size_bytes"] = -1
    with pytest.raises(ValueError):
        validate_manifest(data, request=request, worker_id="worker-1")


def test_failed_manifest_must_have_classified_error_but_may_keep_partial_logs():
    request = JobRequest.model_validate(payload())
    data = manifest(request)
    data.update(status="failed", artifacts=[])
    with pytest.raises(ValueError):
        validate_manifest(data, request=request, worker_id="worker-1")
    data["error_code"] = "runtime-timeout"
    assert validate_manifest(data, request=request, worker_id="worker-1").status == "failed"


def test_artifact_verification_checks_raw_bytes_and_exact_length():
    request = JobRequest.model_validate(payload())
    data = manifest(request)
    raw = b"\x00\xff\n"
    data["artifacts"][0]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    result = validate_manifest(data, request=request, worker_id="worker-1")
    validate_artifact(result.artifacts[0], raw)
    for wrong in (b"abc", b"", raw + b"\n"):
        with pytest.raises(ValueError):
            validate_artifact(result.artifacts[0], wrong)


def test_cancel_before_trial_exists_is_a_valid_sealed_failure():
    request = JobRequest.model_validate(payload())
    data = manifest(request)
    data.update(status="cancelled", trial_id=None, artifacts=[], error_code="cancel-before-start")
    assert validate_manifest(data, request=request, worker_id="worker-1").trial_id is None
    data.update(status="succeeded", error_code=None)
    with pytest.raises(ValueError):
        validate_manifest(data, request=request, worker_id="worker-1")


@pytest.mark.parametrize("budget", ["wall_time_seconds", "cpus", "memory_mb", "max_tokens", "max_artifact_bytes"])
def test_every_budget_has_an_operator_cap(budget):
    data = payload()
    approved = policy(data)
    data["budgets"][budget] += 1
    data["request_sha256"] = request_sha256(data)
    with pytest.raises(ValueError, match="Budget"):
        validate_request(data, policy=approved, now_unix=1000.0)


@pytest.mark.parametrize("clock", [True, 0, -1, float("nan"), float("inf")])
def test_controller_time_must_be_finite_positive(clock):
    data = payload()
    with pytest.raises(ValueError, match="time"):
        validate_request(data, policy=policy(data), now_unix=clock)


@pytest.mark.parametrize("host", ["https://example.com", "example.com", "0.0.0.0", "224.0.0.1", "fe80::1%eth0"])
def test_gateway_destination_is_a_specific_ip(host):
    data = payload()
    data["model_route"]["gateway_host"] = host
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


def test_nested_models_are_immutable_and_arrays_are_not_arbitrary_iterables():
    data = payload()
    request = JobRequest.model_validate(data)
    with pytest.raises(ValueError):
        request.budgets.max_tokens = 1
    assert isinstance(request.dsh_release.patch_sha256s, tuple)
    data["dsh_release"]["patch_sha256s"] = {"unexpected": HASH}
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


@pytest.mark.parametrize("model_name", [" ", "student\n", "\tstudent"])
def test_model_name_cannot_smuggle_whitespace_or_control_chars(model_name):
    data = payload()
    data["model_route"]["model_name"] = model_name
    with pytest.raises(ValueError):
        JobRequest.model_validate(data)


def test_duplicate_does_not_mask_a_conflicting_later_ledger_entry():
    request = JobRequest.model_validate(payload())
    changed = payload()
    changed["sample_index"] = 1
    changed["request_sha256"] = request_sha256(changed)
    with pytest.raises(ValueError, match="reused"):
        check_replay(request, [request, JobRequest.model_validate(changed)])
