"""Explicit cloud CPU probe; synthetic backend, real tokenizer/Ray/Gateway HTTP."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
import ray
import torch
from transformers import AutoTokenizer

from deployment.checks.token_journal_audit import replay
from uni_agent.gateway.config import GatewayActorConfig
from uni_agent.gateway.gateway import GatewayActor
from verl.workers.rollout.replica import TokenOutput


class ProbeBackend:
    def __init__(self, ids):
        self.ids = ids

    async def generate(self, **kwargs):
        assert not torch.cuda.is_initialized()
        return TokenOutput(
            token_ids=self.ids,
            log_probs=[-0.25] * len(self.ids),
            stop_reason="completed",
            extra_fields={"min_global_steps": 3, "max_global_steps": 3},
        )


@pytest.mark.skipif(not os.environ.get("TOKEN_JOURNAL_PROBE_TOKENIZER"), reason="explicit cloud CPU integration probe")
def test_native_gateway_ray_environment_and_real_tokenizer(tmp_path):
    journal_dir = tmp_path / "private"
    tokenizer_path = os.environ["TOKEN_JOURNAL_PROBE_TOKENIZER"]
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    session_id = "synthetic-token-journal-preflight"
    actor = None
    runtime = {
        "env_vars": {
            "UNI_AGENT_TOKEN_JOURNAL_DIR": str(journal_dir),
            "CUDA_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "PYTHONPATH": os.environ["PYTHONPATH"] + os.pathsep + str(Path(__file__).parent),
        }
    }
    assert not torch.cuda.is_initialized()
    ray.init(
        address="local",
        num_cpus=2,
        num_gpus=0,
        include_dashboard=False,
        namespace="token-journal-preflight",
        _temp_dir=tempfile.mkdtemp(prefix="r18-tj-"),
        object_store_memory=128 * 1024 * 1024,
        runtime_env=runtime,
    )
    try:
        actor = GatewayActor.remote(
            GatewayActorConfig(tokenizer=tokenizer, hf_model_type="qwen3"),
            ProbeBackend(tokenizer.encode("done", add_special_tokens=False)),
        )
        ray.get(actor.start.remote(), timeout=120)
        session = ray.get(actor.create_session.remote(session_id, sampling_params={"logprobs": True}), timeout=30)
        messages = [{"role": "user", "content": "synthetic preflight; reply done"}]
        with httpx.Client(timeout=30, trust_env=False) as client:
            for index in range(2):
                response = client.post(
                    session.base_url + "/chat/completions", json={"model": "synthetic-preflight", "messages": messages}
                )
                response.raise_for_status()
                messages += [
                    response.json()["choices"][0]["message"],
                    {"role": "user", "content": f"synthetic observation {index}"},
                ]
        trajectories = ray.get(actor.finalize_session.remote(session_id), timeout=30)
        path = journal_dir / (hashlib.sha256(session_id.encode()).hexdigest() + ".jsonl")
        events = [json.loads(line) for line in path.read_text().splitlines()]
        final, _, summary = replay(events)
        assert len(trajectories) == len(final) == 1
        assert summary["commits"] == 2 and summary["context_tokens"] > 0
        assert not torch.cuda.is_initialized()
        report = {
            "passed": True,
            "synthetic_preflight_only": True,
            "actual_training_verified": False,
            "actual_gateway_actor": True,
            "ray_job_env_propagated": True,
            "tokenizer_path": tokenizer_path,
            "cuda_initialized": False,
            **summary,
            "journal_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        output = os.environ.get("TOKEN_JOURNAL_PROBE_REPORT")
        if output:
            Path(output).write_text(json.dumps(report, indent=2) + "\n")
    finally:
        try:
            if actor is not None:
                try:
                    ray.get(actor.shutdown.remote(), timeout=30)
                except ray.exceptions.ActorDiedError:
                    pass
                ray.kill(actor, no_restart=True)
        finally:
            ray.shutdown()
