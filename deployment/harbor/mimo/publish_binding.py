"""Bind an already-published image after independent inspect and keyless smoke.

No Docker or network calls are made. Supply docker inspect of a pulled immutable
image and stdout from its offline /opt/dsh/checks/smoke.py run. This proves the
image's runtime identity and SDK boot, not Gateway reachability or RL readiness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deployment.bootstrap.prepare_harbor_context import _wheel_hash
from deployment.harbor.mimo.prepare_context import IMAGE, _json, _sha

DOCKER_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def finalize_binding(
    *,
    context: Path,
    derived_image: str,
    derived_inspect: dict,
    smoke: dict,
    output: Path,
    runtime_environment: dict | None = None,
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Image binding output must be new")
    manifest = json.loads((context / "context-manifest.json").read_text())
    if manifest.get("schema") != "dsh.mimo-image-context.v1" or manifest.get("status") != "prepared_not_built":
        raise ValueError("Expected an unmodified prepared MiMo context")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid context path")
        path = context / relative
        if path.is_symlink() or not path.is_file() or _wheel_hash(path) != expected:
            raise ValueError(f"Prepared context has changed: {name}")
    if (
        not IMAGE.fullmatch(derived_image)
        or derived_image not in derived_inspect.get("RepoDigests", [])
        or derived_inspect.get("Os") != "linux"
        or derived_inspect.get("Architecture") != "amd64"
    ):
        raise ValueError("Published image must have a matching amd64 registry digest")
    base = json.loads((context / "base-inspect.json").read_text())
    original_layers = (base.get("RootFS") or {}).get("Layers", [])
    derived_layers = (derived_inspect.get("RootFS") or {}).get("Layers", [])
    if (
        not original_layers
        or len(derived_layers) <= len(original_layers)
        or (derived_layers[: len(original_layers)] != original_layers)
    ):
        raise ValueError("Derived image does not preserve the original image layers")
    original_config = base.get("Config") or {}
    derived_config = derived_inspect.get("Config") or {}
    normalizations = []
    if original_config.get("Env") != derived_config.get("Env"):
        expected = {
            "schema": "dsh.mimo-runtime-environment.v1",
            "original_image": manifest["image_binding"]["original_image"],
            "dsh_image": derived_image,
            "original_path": DOCKER_DEFAULT_PATH,
            "derived_path": DOCKER_DEFAULT_PATH,
        }
        if (
            original_config.get("Env") not in (None, [])
            or derived_config.get("Env") != ["PATH=" + DOCKER_DEFAULT_PATH]
            or runtime_environment != expected
        ):
            raise ValueError("Derived image changes original Env without exact Docker default PATH evidence")
        normalizations.append(
            {"kind": "docker_default_path_materialized", "runtime_evidence_sha256": _sha(_json(expected))}
        )
    for field in ("WorkingDir", "Entrypoint", "Cmd"):
        if original_config.get(field) != derived_config.get(field):
            raise ValueError(f"Derived image changes original {field}")
    if (original_config.get("User") or "root") != (derived_config.get("User") or "root"):
        raise ValueError("Derived image changes original User")
    lock = json.loads((context / "build-inputs.json").read_text())["lock"]
    expected = {
        "runtime_binary_sha256": lock["runtime_binary_sha256"],
        "runtime_rg_sha256": lock["runtime_rg_sha256"],
        "runner_sha256": manifest["files"]["source/uni_agent/agents/dsh/runner.py"],
    }
    if (
        smoke.get("schema") != "dsh.mimo-image-smoke.v1"
        or smoke.get("status") != "passed"
        or smoke.get("scope") != "initialize-shutdown-only"
        or smoke.get("versions")
        != {
            "deepseek-harness-sdk": "0.1.3a2",
            "deepseek-harness-runtime-bin": "0.1.3a2",
            "pydantic": "2.12.5",
        }
        or any(smoke.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("Keyless boot and fixed runtime/source identities must pass")
    result = {
        "schema": "dsh.mimo-image-binding.v1",
        **manifest["image_binding"],
        "dsh_image": derived_image,
        "runner_python": manifest["runner_python"],
        "profile": manifest["profile"],
        "patches": manifest["patches"],
        "source_commit": manifest["source_commit"],
        "dsh_revision": lock["dsh_revision"],
        "python_distribution_version": lock["python_distribution_version"],
        **expected,
        "gateway_origin": manifest["gateway_origin"],
        "gateway_route_verified": False,
        "config_normalizations": normalizations,
        "verification_scope": (
            "original layers/config execution semantics preserved; fixed DSH identity and offline SDK boot"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(_json(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("context", "derived-inspect", "smoke", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--derived-image", required=True)
    parser.add_argument("--runtime-environment", type=Path)
    args = vars(parser.parse_args())
    inspected = json.loads(args["derived_inspect"].read_text())
    args["derived_inspect"] = inspected[0] if isinstance(inspected, list) and len(inspected) == 1 else inspected
    args["smoke"] = json.loads(args["smoke"].read_text())
    if args["runtime_environment"]:
        args["runtime_environment"] = json.loads(args["runtime_environment"].read_text())
    print(json.dumps(finalize_binding(**args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
