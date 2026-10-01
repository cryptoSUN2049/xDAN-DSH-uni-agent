"""Prepare native Webdev tools, Modal execution and shared group-grader assets.

Run on cloud CPU. Source/config/render readiness is never training acceptance.
The optional renderer smoke uses one ordinary frontend, not a policy solution.
"""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

SOURCE_HASHES = {
    "config/agent/design/webdev.yaml": "463329d096e0f6f117ab91624a36ec0267be99e8b9cb8afcc4ec6b28dc9fe787",
    "recipes/design/config/webdev_agent_loop.yaml": "3a7912521c4e78fce75193d310f79c5312fa006c919000bd555f485e1517b044",
    "recipes/design/agent_loop.py": "b2cb2c0e94b9efb55764bac224823ea9a8c1736ee191ef68a448864f37d13de8",
    "recipes/design/webdev/design_mode.py": "5a211cad01fd5236f5ecc095d671d04d297d68d054c5c24e369a0bd61348fa4d",
    "recipes/design/webdev/group_reward.py": "f42cc7461be88d1eef1b7e999e44442658681fdae81c0d21c592b3aedf9d929f",
    "recipes/design/webdev/shot.py": "52e838ccb2d29174184fb2dc1ae838e6fdec07cfc99e51642a401cdf315de757",
    "verl/trainer/ppo/v1/trainer_base.py": "7d36aec878a5086b55a5b425b08951d5c3cacd3d050ad922fe2277dad95b9a77",
}
TOOLS = ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_group_hook_before_advantage(source: str) -> None:
    tree = ast.parse(source)
    method = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_compute_advantage"),
        None,
    )
    if method is None:
        raise ValueError("Native advantage method is missing")
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
    hook = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_rewrite_webdev_group_rewards"
    ]
    advantage = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "compute_advantage_for_multi_trajectories"
    ]
    if (
        not hook
        or not advantage
        or min(hook) >= min(advantage)
        or "WEBDEV_GRADE_MODE" not in ast.get_source_segment(source, method)
    ):
        raise ValueError("Native Webdev group rewrite must run before GRPO advantages")


def modal_harness(original: dict, *, run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("Invalid owned Webdev run_id")
    if [tool["tool"] for tool in original["agent"]["tools"]] != TOOLS:
        raise ValueError("Original Webdev tool catalogue changed")
    if original["traj_grader"]["correctness_mode"] != "design_group_v1":
        raise ValueError("Webdev training requires native group grading")
    result = copy.deepcopy(original)
    result["environment"] = {
        "environment_class": "mimo_reference_modal.ModalEnvironment",
        "cwd": "/workspace",
        "timeout": 300,
        "raise_on_transport_error": True,
        "app_name": "mimo-reference-webdev",
        "run_id": run_id,
        "sandbox_timeout": 1800,
        "cpu": 2,
        "memory": 2048,
        "env": copy.deepcopy(original["environment"].get("env", {})),
    }
    return result


def dockerhub_digest(image: str) -> str:
    """Resolve only a public DockerHub manifest; never download image layers."""
    image = image.removeprefix("docker.io/")
    if "@sha256:" in image:
        if not re.fullmatch(r"[a-z0-9][a-z0-9/._-]*@sha256:[0-9a-f]{64}", image):
            raise ValueError("Invalid immutable DockerHub image")
        return "docker.io/" + image
    repository, separator, tag = image.rpartition(":")
    if (
        not separator
        or not re.fullmatch(r"[a-z0-9][a-z0-9/._-]*", repository)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag)
    ):
        raise ValueError("Expected an explicit public DockerHub repository:tag")
    query = urllib.parse.urlencode({"service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    with urllib.request.urlopen("https://auth.docker.io/token?" + query, timeout=30) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}",
        method="HEAD",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        digest = response.headers.get("Docker-Content-Digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Registry did not return an immutable manifest digest")
    return f"docker.io/{repository}@{digest}"


def materialize_rows(rows: list[dict], mapping: dict, *, resolver=dockerhub_digest) -> tuple[list[dict], list[dict]]:
    runtime, receipts = [], []
    for row in rows:
        item = copy.deepcopy(row)
        instance = json.loads(item["extra_info"]["instance_json"])
        if (
            instance.get("dataset_type") != "webdev"
            or instance.get("cwd") != "/workspace"
            or not instance.get("problem_statement")
        ):
            raise ValueError("Unexpected original Webdev instance contract")
        if item.get("agent_name") != "mimo_swe_agent":
            raise ValueError("Unexpected original Webdev agent_name")
        original = instance["docker_image"]
        mapped = mapping.get(original)
        if not mapped:
            raise ValueError("Original Webdev image has no public mapping")
        image = resolver(mapped)
        instance["docker_image"] = image
        item["extra_info"]["instance_json"] = json.dumps(instance, ensure_ascii=False)
        runtime.append(item)
        receipts.append(
            {
                "task_id": instance["instance_id"],
                "source_image": original,
                "mapped_image": mapped,
                "runtime_image": image,
                "changed_instance_fields": ["docker_image"],
            }
        )
    return runtime, receipts


def loop_registry(original: list[dict], harness_path: Path) -> list[dict]:
    """Preserve the source dispatch field via an explicit native-loop alias."""
    if len(original) != 1 or original[0]["name"] != "webdev":
        raise ValueError("Unexpected original Webdev loop registry")
    result = copy.deepcopy(original)
    result[0].update(config_path=str(harness_path), per_turn_max_tokens=4096, fail_on_env_setup_error=True)
    alias = copy.deepcopy(result[0])
    alias["name"] = "mimo_swe_agent"
    return result + [alias]


def grader_capabilities(url: str) -> dict:
    if not url:
        return {"state": "pending", "reason": "DESIGN_GRADER_URL is missing"}
    route = urllib.parse.urlsplit(url)
    if (
        route.scheme not in ("http", "https")
        or not route.hostname
        or route.username
        or route.password
        or route.path not in ("", "/")
        or route.query
        or route.fragment
    ):
        raise ValueError("Grader URL must be an origin without credentials")
    client = importlib.import_module("recipes.design.webdev.grader_client")
    info = client.check_capabilities(url, need_group=True, timeout_s=30)
    return {
        "state": "capabilities-passed-not-grade-acceptance",
        "url": url,
        **{key: info.get(key) for key in ("grader_version", "model", "reward_semantics", "endpoints", "runtime_gate")},
    }


def renderer_smoke(image: str, run_id: str, output: Path) -> dict:
    """One owned CPU sandbox, original screenshot code, no fake judge or reward."""
    module = importlib.import_module("mimo_reference_modal")
    shot = importlib.import_module("recipes.design.webdev.shot")
    env = module.ModalEnvironment(
        image=image,
        cwd="/",
        run_id=run_id,
        app_name="mimo-reference-webdev-smoke",
        sandbox_timeout=180,
        idle_timeout=90,
        cpu=2,
        memory=2048,
        timeout=60,
        block_network=True,
        raise_on_transport_error=True,
    )
    result = {
        "scope": "ordinary-frontend-render-infrastructure-only",
        "policy_generated": False,
        "task_pass": False,
        "judge_called": False,
        "reward": None,
    }
    try:
        env.start()
        with tempfile.TemporaryDirectory(prefix="mimo-webdev-build-") as directory:
            page = Path(directory) / "template.html"
            page.write_text(
                "<!DOCTYPE html><html><head><style>body{background:#edf2f5;color:#203245;font:24px sans-serif}</style>"
                '</head><body><h1>Ordinary frontend build</h1><p id="ready">Rendered by native browser</p>'
                "</body></html>"
            )
            env.copy_to(str(page), "/workspace/template.html", max_retries=1)
        build = env.execute(
            "node -e \"const f=require('fs');f.mkdirSync('/workspace/dist',{recursive:true});"
            "f.copyFileSync('/workspace/template.html','/workspace/dist/index.html');\"",
            cwd="/",
        )
        if build["reason"] != "ok" or build["returncode"] != 0:
            raise RuntimeError("Ordinary frontend build failed")
        os.environ["WEBDEV_GRADE_HTTP"] = "1"
        capture = env.execute(shot._build_shot_cmd("file:///workspace/dist/index.html"), cwd="/", timeout=90)
        blob, console = shot._parse_shot_b64(capture)
        if capture["reason"] != "ok" or capture["returncode"] != 0 or not blob:
            raise RuntimeError("Native browser screenshot failed")
        raw = base64.b64decode(blob, validate=True)
        path = output / "ordinary-render.jpg"
        path.write_bytes(raw)
        result.update(
            render_state="passed",
            screenshot_sha256=sha(path),
            screenshot_bytes=len(raw),
            console_errors=json.loads(console),
        )
    except Exception as error:
        result.update(render_state="failed", failure_type=type(error).__name__)
    finally:
        try:
            env.cleanup()
        except Exception as error:
            result["cleanup_failure_type"] = type(error).__name__
        result["resource"] = env.evidence
    return result


def preflight(args: argparse.Namespace) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import yaml

    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    hashes = {name: sha(source / name) for name in SOURCE_HASHES}
    if hashes != SOURCE_HASHES:
        raise ValueError("Pinned Webdev source/hook byte identity changed")
    assert_group_hook_before_advantage((source / "verl/trainer/ppo/v1/trainer_base.py").read_text())
    sys.path[:0] = [str(source), str(source / "third_party/mimoagent-osr/src"), str(output)]
    original = yaml.safe_load((source / "config/agent/design/webdev.yaml").read_text())
    harness = modal_harness(original, run_id=args.run_id)
    harness_path = output / "webdev-modal-harness.yaml"
    harness_path.write_text(yaml.safe_dump(harness, sort_keys=False))
    registry = loop_registry(
        yaml.safe_load((source / "recipes/design/config/webdev_agent_loop.yaml").read_text()), harness_path
    )
    registry_path = output / "webdev-agent-loop.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False))
    adapter = Path(__file__).resolve().parents[2] / "uni_agent/tasks/mimo_reference/modal_environment.py"
    shutil.copyfile(adapter, output / "mimo_reference_modal.py")
    mapping = {}
    for line in args.image_mapping.read_text().splitlines():
        pair = json.loads(line)
        mapping[pair["dataset_image"]] = pair["dockerhub_image"]
    images, paths, data_receipts = [], {}, {}
    for split in ("train", "heldout"):
        table = pq.read_table(args.data / f"{split}.parquet")
        rows, receipt = materialize_rows(table.to_pylist(), mapping)
        target = output / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), target)
        paths[split] = str(target)
        data_receipts[split] = {
            "source_sha256": sha(args.data / f"{split}.parquet"),
            "runtime_sha256": sha(target),
            "rows": len(rows),
            "task_ids": [item["task_id"] for item in receipt],
        }
        images.extend(receipt)
    args.shared_shots.mkdir(parents=True, exist_ok=True)
    probe = args.shared_shots / f".readability-{args.run_id}"
    probe.write_text(args.run_id)
    if probe.read_text() != args.run_id:
        raise RuntimeError("Shared screenshot filesystem is unreadable")
    probe.unlink()
    environment = {
        "MIMO_WEBDEV_AGENT_LOOP_CONFIG": str(registry_path),
        "WEBDEV_DEBUG_DIR": str(args.shared_shots.resolve()),
        "DESIGN_GRADER_URL": args.grader_url,
        "WEBDEV_GRADE_MODE": "train",
        "WEBDEV_GRADE_HTTP": "1",
        "MIMO_EXTRA_PYTHONPATH": os.pathsep.join([str(source / "third_party/mimoagent-osr/src"), str(output)]),
    }
    os.environ.update(environment)
    command = [
        sys.executable,
        "-m",
        "verl.trainer.main_ppo",
        "--config-path",
        str(args.profile.resolve().parent),
        "--config-name",
        args.profile.stem,
        f"actor_rollout_ref.model.path={json.dumps(str(args.model))}",
        f"data.train_files={json.dumps([paths['train']])}",
        f"data.val_files={json.dumps([paths['heldout']])}",
        "--cfg",
        "job",
        "--resolve",
    ]
    child_env = os.environ.copy()
    child_env.update(
        CUDA_VISIBLE_DEVICES="", PYTHONPATH=os.pathsep.join([str(source), environment["MIMO_EXTRA_PYTHONPATH"]])
    )
    composed = subprocess.run(command, env=child_env, capture_output=True, text=True, timeout=300)
    if composed.returncode:
        (output / "composition-error.log").write_text(composed.stderr[-12000:])
        raise RuntimeError("Webdev Hydra composition failed")
    (output / "resolved-webdev.yaml").write_text(composed.stdout)
    from omegaconf import OmegaConf

    config = OmegaConf.create(composed.stdout)
    required = {
        "actor_rollout_ref.actor.loss_agg_mode": "prompt-mean",
        "actor_rollout_ref.actor.fsdp_config.model_dtype": "fp32",
        "actor_rollout_ref.rollout.n": 8,
        "actor_rollout_ref.rollout.disable_log_stats": False,
        "algorithm.norm_adv_by_std_in_grpo": True,
        "algorithm.filter_groups.enable": False,
        "ray_kwargs.ray_init.runtime_env.env_vars.WEBDEV_GRADE_MODE": "train",
    }
    for key, expected in required.items():
        if OmegaConf.select(config, key) != expected:
            raise ValueError(f"Required Webdev semantic changed: {key}")
    importlib.import_module("recipes.design.agent_loop")
    grader = grader_capabilities(args.grader_url)
    result = {
        "schema": "mimo.reference-webdev-cpu-preflight.v1",
        "status": "prepared-not-training-acceptance",
        "source_hashes": hashes,
        "profile_sha256": sha(args.profile),
        "adapter_sha256": sha(adapter),
        "required_semantics": required,
        "runtime_environment": environment,
        "runtime_parquets": paths,
        "agent_dispatch": {"source_agent_name": "mimo_swe_agent", "native_loop_alias": "WebdevAgentLoop"},
        "data_receipts": data_receipts,
        "image_receipts": images,
        "grader": grader,
        "controller_started": False,
        "gpu_used": False,
        "task_pass": False,
        "runtime_admitted": False,
        "remaining_gates": [
            "Native query+eight-sibling group judge must produce real rewards",
            "Ray workers and driver must independently read the same screenshots",
            "Actual policy tokens, valid advantages, optimizer and checkpoint verification",
        ],
    }
    if args.renderer_smoke:
        result["renderer_smoke"] = renderer_smoke(images[0]["runtime_image"], args.run_id + "-render", output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "data", "model", "image-mapping", "shared-shots", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--grader-url", default=os.getenv("DESIGN_GRADER_URL", ""))
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("recipes") / "webdev.yaml")
    parser.add_argument("--renderer-smoke", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = preflight(args)
    except Exception as error:
        report = {
            "status": "failed-not-runtime-admitted",
            "failure_type": type(error).__name__,
            "failure": str(error),
            "gpu_used": False,
            "task_pass": False,
        }
    (args.output / "webdev-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if report["status"] == "failed-not-runtime-admitted":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
