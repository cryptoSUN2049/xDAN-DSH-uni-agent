"""Operator-owned provider selection must not weaken frozen Harbor task policy."""

import pytest

from uni_agent.tasks.harbor_dsh.environment_backend import validate_gateway_origin, validate_modal_task


@pytest.mark.parametrize("origin", ["https://gateway.example.com", "https://gateway.example.com:8443/"])
def test_modal_origin_accepts_explicit_https_host(origin):
    assert validate_gateway_origin(origin, backend="modal") == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    [
        "http://gateway.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.1.2.3",
        "https://host.docker.internal",
        "https://u:p@gateway.example.com",
        "https://gateway.example.com/v1",
        "https://gateway.example.com?token=x",
        "https://gateway.example.com#x",
    ],
)
def test_modal_origin_rejects_unreachable_or_ambiguous_routes(origin):
    with pytest.raises(ValueError):
        validate_gateway_origin(origin, backend="modal")


def test_docker_origin_contract_is_preserved():
    assert validate_gateway_origin("http://host.docker.internal:1234/", backend="docker") == (
        "http://host.docker.internal:1234"
    )
    with pytest.raises(ValueError):
        validate_gateway_origin("https://gateway.example.com", backend="docker")
    with pytest.raises(ValueError):
        validate_gateway_origin("https://gateway.example.com", backend="unknown")


def task():
    return {
        "environment": {
            "docker_image": "registry.example.com/dsh@sha256:" + "a" * 64,
            "network_mode": "allowlist",
            "allowed_hosts": ["gateway.example.com"],
        },
        "verifier": {"environment_mode": "separate", "environment": {"network_mode": "no-network"}},
    }


def check(tmp_path, value):
    validate_modal_task(
        tmp_path, value, gateway_origin="https://gateway.example.com", release_digest="sha256:" + "a" * 64
    )


def test_modal_frozen_registry_and_network_contract(tmp_path):
    check(tmp_path, task())


@pytest.mark.parametrize("mutation", ["image", "agent-network", "verifier-network", "artifact", "gpu", "phase"])
def test_modal_task_rejects_weaker_execution_contract(tmp_path, mutation):
    value = task()
    if mutation == "image":
        value["environment"]["docker_image"] = "registry.example.com/dsh:latest"
    elif mutation == "agent-network":
        value["environment"]["allowed_hosts"].append("*.example.com")
    elif mutation == "verifier-network":
        value["verifier"]["environment"]["network_mode"] = "public"
    elif mutation == "artifact":
        value["artifacts"] = ["/app/answer.txt"]
    elif mutation == "gpu":
        value["environment"]["gpus"] = 1
    else:
        value["agent"] = {"network_mode": "public"}
    with pytest.raises(ValueError):
        check(tmp_path, value)


@pytest.mark.parametrize("location", ["environment/docker-compose.yaml", "tests/docker-compose.yaml"])
def test_modal_rejects_compose_before_provider_allocation(tmp_path, location):
    path = tmp_path / location
    path.parent.mkdir(parents=True)
    path.write_text("services: {}")
    with pytest.raises(ValueError, match="Compose"):
        check(tmp_path, task())


@pytest.mark.parametrize("image", ["registry.example.com/dsh@sha256:" + "b" * 64, "sha256:" + "a" * 64])
def test_registry_digest_must_match_release(tmp_path, image):
    value = task()
    value["environment"]["docker_image"] = image
    with pytest.raises(ValueError, match="digest"):
        check(tmp_path, value)


def test_modal_origin_rejects_invalid_dns_hostname():
    with pytest.raises(ValueError):
        validate_gateway_origin("https://bad host.example.com", backend="modal")
