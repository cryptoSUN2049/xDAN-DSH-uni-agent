import hashlib
import json

import pytest

from uni_agent.tasks.harbor_dsh.mimo import MimoBinding, load_mimo_binding

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def binding_value():
    return {
        "schema": "dsh.mimo-code-binding.v1",
        "task_id": "code-1",
        "cwd": "/testbed",
        "runner_python": "/opt/dsh/bin/python",
        "image_binding": {
            "original_image": "registry.example/task@sha256:" + "a" * 64,
            "dsh_image": "registry.example/dsh@sha256:" + "b" * 64,
        },
        "artifact_contract": "mimo-code-workspace-v1",
        "base_ref_capture": "before_agent",
    }


def test_mimo_binding_requires_immutable_images_and_safe_repository():
    value = binding_value()
    assert MimoBinding.model_validate(value).cwd == "/testbed"
    for cwd in ["/", "/tmp/../testbed", "relative", "/opt/dsh"]:
        with pytest.raises(ValueError):
            MimoBinding.model_validate({**value, "cwd": cwd})
    value["image_binding"]["dsh_image"] = "registry.example/dsh:latest"
    with pytest.raises(ValueError):
        MimoBinding.model_validate(value)


def test_binding_loader_rejects_changed_operator_bytes(tmp_path):
    path = tmp_path / "mimo-binding.json"
    raw = json.dumps(binding_value()).encode()
    path.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert load_mimo_binding(path, expected_sha256=digest).task_id == "code-1"
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="hash"):
        load_mimo_binding(path, expected_sha256=digest)
