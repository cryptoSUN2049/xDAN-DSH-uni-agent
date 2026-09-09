import ast
import contextlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deployment.checks import verl_source_overlay as overlay

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "verl"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(ROOT / "verl"), str(repo)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "sparse-checkout", "set", "--no-cone", overlay.TARGET, "uv.lock"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo), "checkout", "--detach", overlay.BASE], check=True, capture_output=True)
    return repo


def test_exact_patch_and_idempotent_source_identity(checkout):
    with pytest.raises(ValueError, match="not applied"):
        overlay.verify_verl_source(checkout)
    baseline = overlay.verify_verl_source(checkout, require_patched=False)
    assert baseline["state"] == "baseline"
    result = overlay.apply_verl_source(checkout)
    assert result["state"] == "patched"
    assert overlay.apply_verl_source(checkout) == overlay.verify_verl_source(checkout) == result
    assert str(checkout) not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["target", "uv", "untracked", "staged", "head", "patch-hash"])
def test_unknown_changes_rejected_without_overwriting(checkout, mutation, tmp_path, monkeypatch):
    if mutation == "target":
        (checkout / overlay.TARGET).write_text("changed")
    elif mutation == "uv":
        (checkout / "uv.lock").write_text("changed")
    elif mutation == "untracked":
        (checkout / "unexpected.py").write_text("changed")
    elif mutation == "staged":
        (checkout / overlay.TARGET).write_text("changed")
        subprocess.run(["git", "-C", str(checkout), "add", overlay.TARGET], check=True)
    elif mutation == "head":
        subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "HEAD^"], check=True, capture_output=True)
    else:
        spec = json.loads(overlay.MANIFEST.read_text())
        spec["patch_sha256"] = "sha256:" + "0" * 64
        manifest = tmp_path / "bad.json"
        manifest.write_text(json.dumps(spec))
        monkeypatch.setattr(overlay, "MANIFEST", manifest)
    before = (checkout / overlay.TARGET).read_bytes()
    with pytest.raises(ValueError):
        overlay.apply_verl_source(checkout)
    assert (checkout / overlay.TARGET).read_bytes() == before


async def execute_original_generate(source, reason):
    module = ast.parse(source)
    function = next(n for n in ast.walk(module) if isinstance(n, ast.AsyncFunctionDef) and n.name == "generate")
    function.decorator_list = []
    namespace = {
        "normalize_token_ids": lambda x: x,
        "SamplingParams": lambda **kw: SimpleNamespace(prompt_logprobs=None, **kw),
        "qwen2_5_vl_dedup_image_tokens": lambda ids, processor: ids,
        "TokensPrompt": dict,
        "RLInsightLogger": SimpleNamespace(trace_state=lambda *a, **kw: contextlib.nullcontext()),
        "extract_prompt_logprobs": lambda **kw: None,
        "TokenOutput": SimpleNamespace,
    }
    tree = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(tree), "fixed-verl-generate", "exec"), namespace)

    async def generate(**kwargs):
        yield SimpleNamespace(
            outputs=[
                SimpleNamespace(token_ids=[5], logprobs=[{5: SimpleNamespace(logprob=-0.2)}], finish_reason=reason)
            ]
        )

    config = SimpleNamespace(
        max_model_len=20,
        full_determinism=False,
        enable_rollout_routing_replay=False,
        mtp=None,
        get=lambda key, default: default,
    )
    server = SimpleNamespace(
        _disaggregation_role=None,
        config=config,
        model_config=SimpleNamespace(processor=None),
        lora_as_adapter=False,
        engine=SimpleNamespace(generate=generate),
        replica_rank=0,
        global_steps=6,
    )
    return await namespace["generate"](
        server, prompt_ids=[1], sampling_params={"max_tokens": 1, "logprobs": True}, request_id="cpu"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [("length", "length"), ("stop", "completed"), ("abort", "aborted")])
async def test_actual_pinned_server_generate_method_preserves_reason(checkout, reason, expected):
    before = (checkout / overlay.TARGET).read_text()
    old = await execute_original_generate(before, reason)
    if reason == "length":
        assert old.stop_reason == "completed"  # Original fixed source reproduces the loss.
    overlay.apply_verl_source(checkout)
    new = await execute_original_generate((checkout / overlay.TARGET).read_text(), reason)
    assert new.stop_reason == expected
    assert new.token_ids == old.token_ids == [5]
    assert new.log_probs == old.log_probs == [-0.2]
    assert new.extra_fields == old.extra_fields == {"global_steps": 6}
