"""Owned local inference process and real DSH Gateway stages, without training IO.

Heavy dependencies are imported only when the executor is opened. Importing this
module (including CLI --help) neither loads a tokenizer nor initializes CUDA.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def _wait_ready(process, base_url, model_name, *, timeout):
    import httpx

    deadline = asyncio.get_running_loop().time() + timeout
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned vLLM exited before readiness; inspect backend.log")
            try:
                health = await client.get(base_url + "/health")
                health.raise_for_status()
                models = await client.get(base_url + "/v1/models")
                models.raise_for_status()
                if model_name not in {row.get("id") for row in models.json().get("data", [])}:
                    raise RuntimeError("Owned vLLM serves an unexpected model identity")
                return
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
    raise TimeoutError("Owned vLLM readiness deadline exceeded; inspect backend.log")


def _create_actor(manifest, base_url):
    from transformers import AutoTokenizer

    from examples.gateway.debug_launcher import OpenAICompletionsBackend, TemplateResultTokenIdsWrapper
    from uni_agent.gateway.config import GatewayActorConfig
    from uni_agent.gateway.gateway import _GatewayActor

    tokenizer = AutoTokenizer.from_pretrained(
        str(manifest["model_path"]), local_files_only=True, trust_remote_code=False
    )
    return _GatewayActor(
        GatewayActorConfig(
            tokenizer=TemplateResultTokenIdsWrapper(tokenizer),
            tool_parser_name="hermes",
            rollout_backend="vllm",
            apply_chat_template_kwargs={"enable_thinking": False},
            prompt_length=8192,
            response_length=8192,
        ),
        OpenAICompletionsBackend(
            backend_base_url=base_url + "/v1",
            backend_model=manifest["model_name"],
            timeout=manifest.get("stage_timeout_seconds", 1800),
        ),
    )


async def _stop_process(process):
    # start_new_session=True made this exact child PID the process-group ID.
    # Never discover or signal any pre-existing backend by port, name, or GPU.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.to_thread(process.wait, timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await asyncio.to_thread(process.wait, timeout=10)


@asynccontextmanager
async def open_executor(manifest):
    """Yield ``async execute(StageSpec)``; teardown only resources created here."""
    from uni_agent.framework.framework import GatewayAgentFramework, _RunnerConfig

    manifest = dict(manifest)
    for key in ("root", "model_path", "model_name", "runner_python", "cuda_visible_devices"):
        if not isinstance(manifest.get(key), str | Path) or not str(manifest[key]).strip():
            raise ValueError(f"Missing executor manifest field: {key}")
    if not Path(manifest["model_path"]).is_dir():
        raise ValueError("Executor requires a local model directory")
    timeout = manifest.get("stage_timeout_seconds", 1800)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 0 < timeout <= 1800:
        raise ValueError("stage_timeout_seconds must be positive and at most 1800")
    root = Path(manifest["root"])
    root.mkdir(parents=True, exist_ok=True)
    port = _port()
    base_url = f"http://127.0.0.1:{port}"
    command = [
        str(manifest["runner_python"]),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(manifest["model_path"]),
        "--served-model-name",
        str(manifest["model_name"]),
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "16384",
        "--gpu-memory-utilization",
        "0.5",
        "--enforce-eager",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    environment = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": str(manifest["cuda_visible_devices"]),
        "DSH_RUNTIME_MODE": "exe",
    }
    process = actor = None
    with (root / "backend.log").open("xb") as logfile:
        try:
            process = subprocess.Popen(
                command, env=environment, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True
            )
            await _wait_ready(process, base_url, manifest["model_name"], timeout=timeout)
            actor = _create_actor(manifest, base_url)
            await actor.start()

            async def execute(spec):
                config = _RunnerConfig(
                    "uni_agent.framework.task_runner.run_task",
                    {
                        "task_config_path": str(spec.task_config_path),
                        "model_name": manifest["model_name"],
                        "require_result": True,
                    },
                    "inline_async",
                    1,
                    session_timeout_seconds=timeout,
                )
                framework = GatewayAgentFramework(
                    actor,
                    runner_registry={"diagnostic": config},
                    log_dir=str(root / "gateway"),
                    fail_on_rollout_error=True,
                    require_finished_episode=False,
                    require_verifier_reward=True,
                    require_trajectory_dump=True,
                )
                return await asyncio.wait_for(
                    framework._execute_gateway_stage(
                        sample_fields={
                            "uid": spec.context.group_uid,
                            "raw_prompt": spec.raw_prompt,
                            "tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": spec.metadata}},
                        },
                        sample_index=0,
                        session_index=spec.context.sibling,
                        global_steps=spec.context.global_steps,
                        partition_id=spec.context.partition,
                        group_size=1,
                        runner_name="diagnostic",
                        runner_config=config,
                        sampling_params={"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096},
                        stage_session_id=spec.gateway_session_id,
                        dump_consumption_crosswalk=False,
                        max_generated_tokens=8192,
                    ),
                    timeout=timeout,
                )

            yield execute
        finally:

            async def cleanup():
                try:
                    if actor is not None:
                        await asyncio.wait_for(actor.shutdown(), timeout=10)
                finally:
                    if process is not None:
                        await _stop_process(process)

            task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
