"""Scripted-policy integration smoke: real DSH tools, no model or training claim."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST_CODE = (
    r"""
return {inject:['tools'],apply(ctx){return harness.registerTool(ctx,harness.defineTool({
 name:'filter_redact_logs',description:'Filter logs and redact email addresses',
 parameters:{records:{type:'array',items:{type:'json'},required:true},
 severity:{oneOf:[{type:'string'},{type:'null'}]},service:{oneOf:[{type:'string'},{type:'null'}]}},
 output:{schema:{type:'array',items:{type:'json'}},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]},
 execute(a){const keys=['timestamp','service','severity','message'];
 const email=/(?<![\w.%+@-])[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za"""
    r"""-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}(?![\w@-]|\.[A-Za-z0-9])/g;
 return a.records.filter(r=>r&&keys.every(k=>typeof r[k]==='string')&&
 (a.severity==null||r.severity===a.severity)&&(a.service==null||r.service===a.service))
 .map(r=>Object.fromEntries(keys.map(k=>[k,k==='message'?r[k].replace(email,'[REDACTED_EMAIL]'):r[k]])));}
}));}};
"""
)


class ScriptedPolicy:
    def __init__(self, calls):
        self.calls = calls
        self.step = 0
        self.plugin = self.package = None

    def respond(self, body):
        messages = body.get("messages", [])
        if self.step and (not messages or messages[-1].get("role") != "tool"):
            raise ValueError("Expected real tool result before next scripted action")
        if self.step == 3:
            match = re.fullmatch(
                r"Defined ([^/\s]+)/([^\s]+) \([^\n]+\); it is not running yet\. "
                r"Use cordis_run to activate this Package\.",
                messages[-1].get("content", "").strip(),
            )
            if not match:
                raise ValueError("Invalid real define result")
            self.plugin, self.package = match.groups()
        inventory = ("cordis_inspect_query", {"platform": "host", "provider": "Tool", "method": "listTools"})
        actions = [
            ("cordis_inspect_self", {}),
            inventory,
            (
                "cordis_define",
                {
                    "plugin": {"kind": "new", "idPrefix": "log"},
                    "name": "log",
                    "purpose": "Scripted-policy smoke",
                    "code": {"host": HOST_CODE},
                },
            ),
            ("cordis_run", {"pluginId": self.plugin, "packageId": self.package, "mode": "run"}),
            ("cordis_inspect_self", {"pluginId": self.plugin}),
            inventory,
            *[("filter_redact_logs", call) for call in self.calls],
            ("cordis_stop", {"pluginId": self.plugin}),
            inventory,
            ("cordis_undefine", {"pluginId": self.plugin}),
            ("cordis_inspect_self", {}),
        ]
        if self.step > len(actions):
            raise ValueError("Scripted request budget exhausted")
        if self.step == len(actions):
            self.step += 1
            return [
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "scripted-policy smoke complete"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ]
        name, arguments = actions[self.step]
        self.step += 1
        return [
            {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": f"scripted-{self.step}",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"content": ""}, "finish_reason": "tool_calls"}]},
        ]


def sdk_version():
    try:
        return importlib.metadata.version("deepseek-harness-sdk")
    except importlib.metadata.PackageNotFoundError:
        return None


def run(fixture_path: Path, output: Path, exe: str | None = None):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    from examples.dsh.capability_tasks.log_tool.verifier import verify_trace
    from uni_agent.agents.dsh.runner import _canonical_event_bytes

    fixture = json.loads(fixture_path.read_text())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    policy = ScriptedPolicy(fixture["calls"])
    requests = []
    errors = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers.get("content-length", "0"))
                if not 0 < size < 8_000_000:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(size))
                requests.append(body)
                chunks = policy.respond(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception as exc:
                errors.append(str(exc))
                self.send_error(500)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 2
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = DeepSeekHarnessConfig(
            provider="deepseek-official",
            model="deepseek-v4-pro",
            profile="sdk-minimal",
            patches=(str(Path("examples/dsh/evolution.patch.yml").resolve()),),
            cwd=str(output.resolve()),
            runtime_cwd=str(output.resolve()),
            dsh_bin=exe,
            dsh_home=str((output / "home").resolve()),
            initialize_timeout_seconds=60,
            request_timeout_seconds=120,
            shutdown_timeout_seconds=5,
            base_url=f"http://127.0.0.1:{server.server_port}",
            api_key="sk-scripted-no-model",
            env={"DSH_PERMISSION_MODE": "danger-full-access", "DSH_TELEMETRY_DISABLED": "1"},
        )
        with DeepSeekHarness(config) as harness:
            result = harness.run("Execute the scripted-policy integration smoke. No model capability claim.")
        raw = _canonical_event_bytes(result.events)
        trace = output / "events.jsonl"
        trace.write_bytes(raw)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        verdict = verify_trace(trace, digest, fixture=fixture)
        report = {
            "schema": "dsh.t2-scripted-runtime-smoke.v1",
            "scope": "scripted-policy integration smoke",
            "runtime_mode": "source-built-executable" if exe else "installed-sdk-runtime",
            "runtime_source_commit": None,
            "trace_sha256": digest,
            "fixture_sha256": "sha256:" + hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            "sdk_version": sdk_version(),
            "host_code_sha256": "sha256:" + hashlib.sha256(HOST_CODE.encode()).hexdigest(),
            "executable": str(Path(exe).resolve()) if exe else None,
            "executable_entry_sha256": "sha256:" + hashlib.sha256(Path(exe).read_bytes()).hexdigest() if exe else None,
            "session_id": result.session_id,
            "finish_reason": result.finish_reason,
            "verdict": verdict,
            "http_errors": errors,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if errors or not verdict["passed"]:
            raise RuntimeError("Real runtime smoke did not pass; inspect saved evidence")
        return report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        (output / "requests.json").write_text(json.dumps(requests, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe")
    args = parser.parse_args()
    print(json.dumps(run(args.fixture, args.output, args.exe), indent=2))


if __name__ == "__main__":
    main()
