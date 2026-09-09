"""Fixed DSH runtime + loopback scripted HTTP; no GPU/model/training receipts."""

import argparse
import hashlib
import json
import os
import signal
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

from uni_agent.agents.dsh.runner import _canonical_event_bytes

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "b2369692ea530007075ebcd18d39fdba0bbd3982"
VERSION = "0.1.3a2"
MODES = ("stop", "length", "length-tool-text")


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def sdk_version():
    return version("deepseek-harness-sdk")


def private_write(path, raw):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)


def wire_response(mode, sentinel):
    if mode == "abort409":
        return (
            409,
            "application/json",
            json.dumps(
                {
                    "error": {
                        "message": "Backend generation was aborted; session cannot continue",
                        "type": "conflict_error",
                        "code": None,
                        "param": None,
                    }
                }
            ).encode(),
        )
    if mode not in MODES:
        raise ValueError("Unknown scripted mode")
    text = "Scripted text; no model was called."
    if mode == "length-tool-text":
        text = (
            "<tool_call>\n"
            + json.dumps(
                {
                    "name": "str_replace_editor",
                    "arguments": {"command": "create", "path": str(sentinel), "file_text": "MUST_NOT_EXIST"},
                }
            )
            + "\n</tool_call>"
        )
    frames = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if mode == "stop" else "length"}]},
    ]
    raw = b"".join(("data: " + json.dumps(frame) + "\n\n").encode() for frame in frames)
    return 200, "text/event-stream", raw + b"data: [DONE]\n\n"


def assess(mode, finish_reason, events, sentinel):
    terminal = [e.get("data", {}).get("reason", {}).get("kind") for e in events if e.get("type") == "turn/end"]
    tool_calls = sum(e.get("type") == "tool/call" for e in events)
    side_effect = sentinel.exists() or sentinel.is_symlink()
    expected = "completed" if mode == "stop" else "max-tokens"
    passed = finish_reason == expected and terminal == [expected] and not tool_calls and not side_effect
    return dict(
        passed=passed,
        finish_reason=finish_reason,
        finished=finish_reason == "completed",
        terminal_reasons=terminal,
        tool_calls=tool_calls,
        side_effect=side_effect,
    )


def start_server(mode, sentinel):
    requests, errors = [], []

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def do_POST(self):
            try:
                size = int(self.headers.get("content-length", "0"))
                if not 0 < size <= 1_000_000 or len(requests) >= 8:
                    raise ValueError("Request budget exceeded")
                body = self.rfile.read(size)
                parsed = json.loads(body)
                if parsed.get("stream") is not True:
                    raise ValueError("Expected SSE request")
                status, content_type, raw = wire_response(mode, sentinel)
                requests.append(dict(body_sha256=sha(body), bytes=len(body), status=status))
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)
            except Exception as exc:
                errors.append(type(exc).__name__)
                self.send_error(500)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests, errors


@contextmanager
def case_deadline(seconds=120):
    """SDK subscription.next() has no timeout; bound the actual event wait too."""
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RuntimeError("An existing alarm prevents a private canary deadline")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError("DSH canary wall-clock deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def scenario(root, exe, mode):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness.errors import JsonRpcError

    root.mkdir(mode=0o700)
    sentinel = root / "unexpected-side-effect.txt"
    patch = root / "closed.patch.json"
    private_write(
        patch,
        json.dumps([{"id": "persistent-bash", "disabled": True}, {"id": "persistent-pwsh", "disabled": True}]).encode(),
    )
    server, thread, requests, errors = start_server(mode, sentinel)
    record = dict(mode=mode, passed=False, trace_available=False)
    try:
        config = DeepSeekHarnessConfig(
            provider="deepseek-official",
            model="deepseek-v4-pro",
            profile="sdk-minimal",
            patches=(str(patch),),
            cwd=str(root),
            runtime_cwd=str(root),
            dsh_home=str(root / "home"),
            dsh_bin=str(exe),
            base_url=f"http://127.0.0.1:{server.server_port}",
            api_key="EMPTY",
            initialize_timeout_seconds=60,
            request_timeout_seconds=60,
            shutdown_timeout_seconds=5,
            max_tokens=4096,
            reasoning_effort="off",
            env={"DSH_TELEMETRY_DISABLED": "1"},
        )
        try:
            with case_deadline(), DeepSeekHarness(config) as harness:
                result = harness.run(
                    "Return the scripted endpoint response; this is an operator canary.",
                    session_id="finish-canary-" + uuid.uuid4().hex,
                )
        except Exception as exc:
            record.update(error_type=type(exc).__name__, finished=False)
            # An observed HTTP409 plus an explicit SDK error is evidence of rejection,
            # not a complete Task trace. Timeouts/transport errors never pass.
            if mode == "abort409" and requests and all(r["status"] == 409 for r in requests):
                record["passed"] = isinstance(exc, JsonRpcError)
        else:
            raw = _canonical_event_bytes(result.events)
            private_write(root / "events.jsonl", raw)
            record.update(
                trace_available=True,
                trace_sha256=sha(raw),
                session_id=result.session_id,
                final_response_sha256=sha(result.final_response.encode()),
            )
            record.update(assess(mode, result.finish_reason, result.events, sentinel))
            if mode == "abort409":
                record["passed"] = (
                    bool(requests)
                    and all(r["status"] == 409 for r in requests)
                    and (
                        result.finish_reason not in ("completed", "max-tokens", None)
                        and not record["tool_calls"]
                        and not record["side_effect"]
                    )
                )
        record.update(requests=requests, http_errors=errors)
        record["passed"] = bool(record["passed"] and requests and not errors and not sentinel.exists())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        private_write(root / "result.json", (json.dumps(record, indent=2) + "\n").encode())
    return record


def run(output, runtime, *, include_abort=False):
    lock_path = ROOT / "deployment/versions/g1-deployment-lock.json"
    lock = json.loads(lock_path.read_bytes())["dsh"]
    if lock["source_revision"] != SOURCE or lock["version"] != VERSION:
        raise ValueError("Expected fixed b236/0.1.3a2 lock")
    exe = Path(runtime).resolve(strict=True)
    digest = sha(exe.read_bytes())
    if digest != lock["runtime_binary_sha256"]:
        raise ValueError("Runtime pin mismatch")
    if sdk_version() != VERSION:
        raise ValueError("SDK version mismatch")
    output = Path(output).absolute()
    if output.parent.resolve() != output.parent:
        raise ValueError("Use canonical output parent")
    output.mkdir(mode=0o700)
    cases = [scenario(output / mode, exe, mode) for mode in (*MODES, *(("abort409",) if include_abort else ()))]
    report = dict(
        schema="dsh.finish-reason-canary.v1",
        passed=all(c["passed"] for c in cases),
        scope="scripted loopback HTTP + fixed SDK/runtime; no GPU/model/RL admission",
        runtime_source=SOURCE,
        runtime_version=VERSION,
        runtime_sha256=digest,
        sdk_version=sdk_version(),
        script_sha256=sha(Path(__file__).read_bytes()),
        lock_sha256=sha(lock_path.read_bytes()),
        cases=cases,
    )
    private_write(output / "result.json", (json.dumps(report, indent=2) + "\n").encode())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--include-abort", action="store_true")
    args = parser.parse_args()
    report = run(args.output, args.runtime, include_abort=args.include_abort)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
