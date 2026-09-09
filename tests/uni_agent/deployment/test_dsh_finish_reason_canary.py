import json

import pytest

from deployment.checks import dsh_finish_reason_canary as canary


def test_length_printed_tool_is_only_sse_content(tmp_path):
    status, kind, raw = canary.wire_response("length-tool-text", tmp_path / "sentinel")
    assert status == 200 and kind == "text/event-stream"
    frames = [json.loads(x[6:]) for x in raw.decode().splitlines() if x.startswith("data: {")]
    assert frames[-1]["choices"][0]["finish_reason"] == "length"
    assert "<tool_call>" in frames[0]["choices"][0]["delta"]["content"]
    assert all("tool_calls" not in x["choices"][0]["delta"] for x in frames)
    assert raw.endswith(b"data: [DONE]\n\n")


@pytest.mark.parametrize("mode,reason,expected", [("stop", "completed", True), ("length", "max-tokens", False)])
def test_real_end_reason_contract(mode, reason, expected, tmp_path):
    events = [{"type": "turn/end", "data": {"reason": {"kind": reason}}}]
    result = canary.assess(mode, reason, events, tmp_path / "sentinel")
    assert result["passed"] and result["finished"] is expected


@pytest.mark.parametrize("failure", ["wrong_reason", "tool_call", "side_effect", "missing_end"])
def test_length_cannot_silently_pass_as_completed_or_execute_tools(tmp_path, failure):
    target = tmp_path / "sentinel"
    events = [{"type": "turn/end", "data": {"reason": {"kind": "max-tokens"}}}]
    reason = "max-tokens"
    if failure == "wrong_reason":
        reason = "completed"
    if failure == "tool_call":
        events.insert(0, {"type": "tool/call", "data": {}})
    if failure == "side_effect":
        target.write_text("executed")
    if failure == "missing_end":
        events = []
    assert not canary.assess("length-tool-text", reason, events, target)["passed"]


def test_abort_http409_contract(tmp_path):
    status, kind, raw = canary.wire_response("abort409", tmp_path / "sentinel")
    assert status == 409 and kind == "application/json"
    assert json.loads(raw)["error"] == {
        "message": "Backend generation was aborted; session cannot continue",
        "type": "conflict_error",
        "code": None,
        "param": None,
    }


def test_wrong_runtime_rejected_before_output_creation(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"wrong")
    output = tmp_path / "new"
    monkeypatch.setattr(canary, "sdk_version", lambda: "0.1.3a2")
    with pytest.raises(ValueError, match="Runtime pin mismatch"):
        canary.run(output, runtime)
    assert not output.exists()


@pytest.mark.parametrize("mode", ["stop", "length", "length-tool-text", "abort409"])
def test_actual_loopback_http_returns_exact_wire_and_private_request_digest(mode, tmp_path):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    server, thread, requests, errors = canary.start_server(mode, tmp_path / "sentinel")
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/chat/completions",
            data=json.dumps({"stream": True, "messages": []}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            expected_status, _, expected_raw = canary.wire_response(mode, tmp_path / "sentinel")
            assert response.status == expected_status
            assert response.read() == expected_raw
        assert len(requests) == 1 and requests[0]["status"] == expected_status
        assert set(requests[0]) == {"body_sha256", "bytes", "status"}
        assert errors == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_private_artifacts_reject_overwrite(tmp_path):
    target = tmp_path / "result.json"
    canary.private_write(target, b"original")
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        canary.private_write(target, b"replacement")
    assert target.read_bytes() == b"original"


def test_case_deadline_interrupts_event_wait_and_restores_signal():
    import signal
    import time

    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError, match="canary wall-clock"):
        with canary.case_deadline(0.01):
            time.sleep(0.2)
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
