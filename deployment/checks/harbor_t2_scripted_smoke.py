"""Real Harbor/DSH scripted integration only: no student model or training."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from deployment.checks import dsh_log_tool_smoke

MODES = ("positive", "wrongoutput", "noop", "tamper")
MODEL = "deepseek-v4-pro"
KEY = "sk-scripted-no-model"


class Policy:
    def __init__(self, mode, calls):
        if mode not in MODES:
            raise ValueError("Unknown mode")
        self.mode = mode
        self.inner = dsh_log_tool_smoke.ScriptedPolicy(calls)

    def respond(self, body):
        if self.mode == "noop":
            return [{"choices": [{"delta": {"role": "assistant", "content": "No action."}, "finish_reason": "stop"}]}]
        chunks = self.inner.respond(body)
        if self.mode == "wrongoutput":
            for chunk in chunks:
                for call in chunk["choices"][0]["delta"].get("tool_calls", []):
                    fn = call["function"]
                    if fn["name"] == "cordis_define":
                        args = json.loads(fn["arguments"])
                        original = args["code"]["host"]
                        if "execute(a){" not in original:
                            raise ValueError("Scripted policy definition contract changed")
                        args["code"]["host"] = original.replace("execute(a){", "execute(a){return [];", 1)
                        fn["arguments"] = json.dumps(args)
        return chunks


def private_output(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
        raise ValueError("Output requires owned private permissions")


def check_result(mode, result):
    if mode == "tamper":
        if (
            "Bridge trace/status/session identity mismatch" not in str(result.exception_info)
            or result.verifier_result is not None
        ):
            raise RuntimeError("Expected exact tamper rejection without reward")
    elif (
        result.exception_info is not None
        or result.verifier_result is None
        or result.verifier_result.rewards != {"reward": float(mode == "positive")}
    ):
        raise RuntimeError("Unexpected trial exception or reward")


def start_server(policy, session):
    errors = []
    requests = []
    route = f"/sessions/{session}/v1/chat/completions"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(15)
            if self.path != route or self.headers.get("Authorization") != f"Bearer {KEY}":
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8_000_000:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(size))
                if body.get("model") != MODEL or body.get("stream") is not True:
                    raise ValueError("Unexpected model or nonstream request")
                chunks = policy.respond(body)
                requests.append({"model": body["model"], "session": session})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    chunk.update(
                        id=f"chatcmpl-{session}-{len(requests)}",
                        object="chat.completion.chunk",
                        model=body["model"],
                        created=0,
                    )
                    for choice in chunk["choices"]:
                        choice["index"] = 0
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception as exc:
                errors.append(str(exc))
                self.send_error(500)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests, errors


async def run(task_dir, fixture, output, *, modes=MODES, timeout=600):
    from harbor.models.trial.config import TrialConfig
    from harbor.trial.hooks import TrialEvent

    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_STRATEGY
    from uni_agent.tasks.harbor_dsh.executor import _confirm_cleanup
    from uni_agent.tasks.harbor_dsh.isolated_trial import create_isolated_trial

    if not math.isfinite(timeout) or timeout <= 0 or not modes or any(mode not in MODES for mode in modes):
        raise ValueError("Explicit modes and finite positive timeout required")
    calls = json.loads(fixture.read_bytes())["calls"]
    private_output(output)
    sources = [Path(__file__), Path(dsh_log_tool_smoke.__file__), fixture]
    sources.extend(path for path in task_dir.rglob("*") if path.is_file())
    report = dict(
        passed=False,
        scope="scripted Harbor/DSH integration; no model, Gateway tokens or training",
        cases=[],
        source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    )
    try:
        for mode in modes:
            session = "t2-" + uuid.uuid4().hex
            server, thread, requests, errors = start_server(Policy(mode, calls), session)
            evidence = dict(mode=mode, gateway_session_id=session, cleanup_confirmed=False)
            report["cases"].append(evidence)
            trial = None
            try:
                config = TrialConfig.model_validate(
                    dict(
                        task={"path": str(task_dir)},
                        trials_dir=str(output),
                        trial_name=session,
                        environment={"type": "docker", "delete": True},
                        agent={
                            "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                            "model_name": MODEL,
                            "kwargs": {
                                "gateway_base_url": f"http://host.docker.internal:{server.server_port}/sessions/{session}/v1",
                                "gateway_api_key": KEY,
                                "patches": [T2_PATCH_PATH],
                                "run_timeout": timeout - min(30, timeout / 2),
                            },
                        },
                    )
                )
                trial = create_isolated_trial(
                    config,
                    allowed_task_dir=task_dir,
                    strategy=T2_STRATEGY,
                    gateway_session_id=session,
                    max_trace_bytes=16 * 1024 * 1024,
                )
                if mode == "tamper":

                    async def tamper(_event, trial=trial):
                        path = trial.paths.agent_dir / "dsh/session.jsonl"
                        # Valid JSON and unchanged event semantics, different bytes/hash.
                        raw = path.read_bytes()
                        path.write_bytes(b" " + raw)

                    trial.add_hook(TrialEvent.VERIFICATION_START, tamper)
                result = await asyncio.wait_for(trial.run(), timeout=timeout)
                evidence.update(
                    exception=None if result.exception_info is None else result.exception_info.model_dump(mode="json"),
                    rewards=None if result.verifier_result is None else result.verifier_result.rewards,
                )
                if errors or not requests:
                    raise RuntimeError(f"Scripted server failed: {errors}")
                check_result(mode, result)
                evidence["passed"] = True
            finally:
                await asyncio.to_thread(server.shutdown)
                server.server_close()
                await asyncio.to_thread(thread.join, 5)
                evidence["request_count"] = len(requests)
                evidence["server_errors"] = errors
                if trial is not None:
                    await _confirm_cleanup(trial)
                    evidence["cleanup_confirmed"] = True
        report["passed"] = True
    finally:
        (output / "scripted-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=MODES, action="append")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run(
                    args.task_dir.resolve(),
                    args.fixture.resolve(),
                    args.output.absolute(),
                    modes=args.mode or MODES,
                    timeout=args.timeout,
                )
            )
        )
    )


if __name__ == "__main__":
    main()
