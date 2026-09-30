"""Transport operator boundaries; all authorization files are isolated temp files."""

import hashlib
import importlib.util
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.uni_agent.deployment.test_harbor_run_controller import make_spec
from tests.uni_agent.tasks.test_mimo_binding import binding_value


@pytest.fixture
def operator(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r20_transport.py"
    spec = importlib.util.spec_from_file_location("transport_r20", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PRIVATE", tmp_path)
    monkeypatch.setattr(module.time, "time", lambda: module.DEADLINE - 3600)
    monkeypatch.setattr(module, "occupied", lambda: [])
    return module


@pytest.fixture
def authorization(operator, tmp_path, monkeypatch):
    known = tmp_path / "cohost-r19/known_hosts"
    known.parent.mkdir()
    known.write_text("[127.0.0.1]:22 ssh-ed25519 test-host-key\n")
    real_sha = operator.sha
    monkeypatch.setattr(
        operator,
        "sha",
        lambda path: (
            "1713b5f13a0eee60d07fad9de5cd1ac099855fadcada95dc29e812099ba7d793" if path == known else real_sha(path)
        ),
    )
    keys = tmp_path / "authorized_keys"
    keys.write_bytes(b"ssh-ed25519 unrelated-key unrelated-session\n# preserved comment\n")
    monkeypatch.setattr(operator, "Path", lambda value: keys if value == "/root/.ssh/authorized_keys" else Path(value))
    return keys


def test_authorize_appends_only_scoped_entry_preserving_exact_other_bytes(operator, authorization):
    before = authorization.read_bytes()
    result = operator.authorize()
    after = authorization.read_bytes()
    assert after.startswith(before)
    entry = after[len(before) :]
    assert entry.count(b"\n") == 1
    assert b'from="127.0.0.1"' in entry
    assert b'command="/bin/false"' in entry
    assert b'permitlisten="127.0.0.1:38780"' in entry
    assert b'permitlisten="127.0.0.1:38781"' in entry
    assert result["authorized_entry_sha256"] == hashlib.sha256(entry).hexdigest()
    assert result["other_bytes_preserved"] is True
    assert "PRIVATE KEY" not in json.dumps(result)


@pytest.mark.parametrize("before", [b"existing key without newline", b"ssh-ed25519 x mimo-r20-loopback-only\n"])
def test_ambiguous_or_existing_authorization_rejected_without_modification(operator, authorization, before):
    authorization.write_bytes(before)
    with pytest.raises(ValueError, match="existing R20 entry or non-newline"):
        operator.authorize()
    assert authorization.read_bytes() == before


def test_authorized_keys_symlink_rejected_without_touching_target(operator, authorization):
    target = authorization.with_name("other-session")
    target.write_bytes(authorization.read_bytes())
    before = target.read_bytes()
    authorization.unlink()
    authorization.symlink_to(target)
    with pytest.raises(OSError):
        operator.authorize()
    assert target.read_bytes() == before


@pytest.mark.parametrize("remaining", [0, 1800, 14401])
def test_authorization_outside_window_never_creates_key(operator, tmp_path, monkeypatch, remaining):
    monkeypatch.setattr(operator.time, "time", lambda: operator.DEADLINE - remaining)
    with pytest.raises(ValueError, match="window"):
        operator.authorize()
    assert not (tmp_path / "cohost-r20").exists()


def test_occupied_port_rejects_before_key_creation(operator, tmp_path, monkeypatch):
    monkeypatch.setattr(operator, "occupied", lambda: [38880])
    with pytest.raises(ValueError):
        operator.authorize()
    assert not (tmp_path / "cohost-r20").exists()


def test_write_new_never_overwrites_file_or_symlink(operator, tmp_path):
    path = tmp_path / "owned"
    operator.write_new(path, b"original")
    with pytest.raises(FileExistsError):
        operator.write_new(path, b"replacement")
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(FileExistsError):
        operator.write_new(link, b"replacement")
    assert path.read_bytes() == b"original"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.fixture
def prepared(operator, tmp_path, monkeypatch):
    value = make_spec(tmp_path).model_dump(mode="json")
    value["modal_ingress"] = {
        "origin": "https://example.invalid",
        "tunnel_id": "12345678-1234-1234-1234-123456789abc",
        "credentials_file": str(tmp_path / "unused.json"),
        "listen_port": 39999,
    }
    raw = json.dumps(value).encode()
    (tmp_path / "run-spec-r19.json").write_bytes(raw)
    real_hash = hashlib.sha256
    monkeypatch.setattr(
        operator,
        "hashlib",
        SimpleNamespace(
            sha256=lambda value: (
                SimpleNamespace(hexdigest=lambda: "5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33")
                if value == raw
                else real_hash(value)
            )
        ),
    )
    task = tmp_path / "new-task"
    task.mkdir()
    (task / "instruction.md").write_text("Independent new task\n")
    (task / "task.toml").write_text('[environment]\ndocker_image="registry.example/dsh@sha256:' + "b" * 64 + '"\n')
    binding = binding_value()
    binding["task_id"] = "format-code-task-002857"
    (task / "mimo-binding.json").write_text(json.dumps(binding))
    return task


def test_new_spec_has_distinct_identity_and_exact_task_image(operator, prepared, tmp_path):
    from examples.harbor.prepare_m2_training import task_digest

    report = operator.prepare_spec("r20-a", prepared, "sha256:" + "b" * 64)
    value = json.loads(Path(report["spec_path"]).read_text())
    assert value["run_id"] == "mimo9b-002857-r20-a"
    assert value["task_dir"] == str(prepared)
    assert value["policy_template"]["task_refs"] == [
        {"id": "mimo-code-format-code-task-002857", "version": "v1", "sha256": task_digest(prepared)}
    ]
    assert value["policy_template"]["dsh_release"]["image_digest"] == "sha256:" + "b" * 64
    assert value["max_concurrent_jobs"] == 2
    before = Path(report["spec_path"]).read_bytes()
    token = (tmp_path / "worker-token-r20-a").read_bytes()
    with pytest.raises(FileExistsError):
        operator.prepare_spec("r20-a", prepared, "sha256:" + "b" * 64)
    assert Path(report["spec_path"]).read_bytes() == before
    assert (tmp_path / "worker-token-r20-a").read_bytes() == token


def test_wrong_immutable_image_rejected_without_tokens(operator, prepared, tmp_path):
    with pytest.raises(ValueError, match="image mismatch"):
        operator.prepare_spec("r20-a", prepared, "sha256:" + "c" * 64)
    assert not (tmp_path / "registration-token-r20-a").exists()
    assert not (tmp_path / "run-spec-r20-a.json").exists()


@pytest.mark.parametrize("stage", ["r19-a", "r20/escape", "r20..", "r20 a"])
def test_invalid_stage_rejected_before_output(operator, prepared, stage):
    with pytest.raises(ValueError, match="stage/window"):
        operator.prepare_spec(stage, prepared, "sha256:" + "b" * 64)


def test_changed_base_spec_rejected(operator, prepared, tmp_path):
    path = tmp_path / "run-spec-r19.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Base spec"):
        operator.prepare_spec("r20-a", prepared, "sha256:" + "b" * 64)


@pytest.mark.parametrize("remaining", [0, 1800, 14401])
def test_spec_window_rejects_before_token_creation(operator, prepared, tmp_path, monkeypatch, remaining):
    monkeypatch.setattr(operator.time, "time", lambda: operator.DEADLINE - remaining)
    with pytest.raises(ValueError, match="stage/window"):
        operator.prepare_spec("r20-a", prepared, "sha256:" + "b" * 64)
    assert not (tmp_path / "registration-token-r20-a").exists()


def test_existing_controller_root_rejected_before_tokens(operator, prepared, tmp_path):
    (tmp_path / "controller-r20-a").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        operator.prepare_spec("r20-a", prepared, "sha256:" + "b" * 64)
    assert not (tmp_path / "registration-token-r20-a").exists()


def test_explicit_new_base_spec_is_not_misrepresented_as_old_sha(operator, prepared, tmp_path, monkeypatch):
    original = json.loads((tmp_path / "run-spec-r19.json").read_bytes())
    original["policy_template"]["gateway_host"] = "172.25.0.2"
    helper = runpy.run_path(str(Path(operator.__file__).with_name("mimo_r20_operator.py")))
    original["policy_template"]["dsh_release"].update(
        source_sha=helper["DSH_SOURCE"],
        sdk_sha256=helper["SDK_SHA"],
        runtime_sha256=helper["RUNTIME_SHA"],
        patch_sha256s=[],
        platform="linux/amd64",
        profile="sdk-minimal",
    )
    base = tmp_path / "recovered-base.json"
    base.write_text(json.dumps(original))
    auth = dict(
        deadline_unix=1790813073,
        allocated_at_unix=1790791473,
        max_run_seconds=21600,
        cleanup_reserve_seconds=180,
        stage="r20f",
        gateway_host="172.25.0.2",
    )
    monkeypatch.setattr(operator.time, "time", lambda: auth["allocated_at_unix"] + 60)
    result = operator.prepare_spec(
        "r20f",
        prepared,
        "sha256:" + "b" * 64,
        authorization=auth,
        base_spec_path=base,
        base_spec_sha256=operator.sha(base),
    )
    value = json.loads(Path(result["spec_path"]).read_bytes())
    assert value["deadline_unix"] == auth["deadline_unix"]
    assert value["policy_template"]["gateway_host"] == auth["gateway_host"]
    assert value["ssh_key"].endswith("cohost-r21/loopback-key")
    assert result["base_spec_sha256"] == operator.sha(base)
    assert value["run_id"] == "mimo9b-002857-r20f"
    original["policy_template"]["dsh_release"]["source_sha"] = "0" * 40
    base.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="pinned DSH provenance"):
        operator.prepare_spec(
            "r20f",
            prepared,
            "sha256:" + "b" * 64,
            authorization=auth,
            base_spec_path=base,
            base_spec_sha256=operator.sha(base),
        )


def test_changed_new_base_rejected_before_token_write(operator, prepared, tmp_path):
    with pytest.raises(ValueError, match="base spec|Base spec"):
        operator.prepare_spec(
            "r20f",
            prepared,
            "sha256:" + "b" * 64,
            authorization={"stage": "r20f"},
            base_spec_path=tmp_path / "run-spec-r19.json",
            base_spec_sha256="0" * 64,
        )
    assert not (tmp_path / "registration-token-r20f").exists()


def test_new_host_identity_rejects_wrong_known_key_before_authorization(operator, tmp_path):
    known = tmp_path / "fresh-known-hosts"
    known.write_text("127.0.0.1 ssh-ed25519 copied-old-host\n")
    key = tmp_path / "actual-host.pub"
    key.write_text("ssh-ed25519 current-host\n")
    with pytest.raises(ValueError, match="host key"):
        operator.validate_local_host(
            {"known_hosts_path": str(known), "known_hosts_sha256": operator.sha(known), "gateway_host": "172.25.0.2"},
            host_public_key=key,
        )


def test_current_host_key_and_local_gateway_are_both_required(operator, tmp_path):
    known = tmp_path / "verified-hosts"
    known.write_text("127.0.0.1 ssh-ed25519 current-key\n")
    key = tmp_path / "host.pub"
    key.write_text("ssh-ed25519 current-key host-comment\n")
    auth = dict(known_hosts_path=str(known), known_hosts_sha256=operator.sha(known), gateway_host="127.0.0.1")
    operator.validate_local_host(auth, host_public_key=key)
    auth["gateway_host"] = "192.0.2.199"
    with pytest.raises(OSError):
        operator.validate_local_host(auth, host_public_key=key)
    auth["known_hosts_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="host key SHA"):
        operator.validate_local_host(auth, host_public_key=key)
