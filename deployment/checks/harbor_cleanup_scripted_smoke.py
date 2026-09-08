"""Real Docker cleanup rejection then success on one durable ledger; no GPU."""

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from deployment.checks.harbor_evolution_scripted_smoke import Policy
from deployment.checks.harbor_t2_scripted_smoke import MODEL, private_output, start_server
from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.protocol import RequestPolicy, request_sha256
from uni_agent.tasks.harbor_dsh.worker import HarborWorker


class TruncatedPolicy:
    def respond(self, _body):
        return [{"choices": [{"delta": {"role": "assistant", "content": "Incomplete"}, "finish_reason": "length"}]}]


def check_terminal(mode, state):
    manifest = state.get("manifest") or {}
    if mode == "truncated":
        if (
            state["status"] != "cancelled"
            or manifest.get("status") != "cancelled"
            or manifest.get("error_code") != "evidence-rejected-after-cleanup"
            or manifest.get("artifacts") != []
            or "unconfirmed" in state
        ):
            raise RuntimeError("Truncated trial did not seal a clean non-training rejection")
    elif state["status"] != "succeeded" or manifest.get("status") != "succeeded":
        raise RuntimeError("Next job did not succeed after releasing the durable slot")


async def run(spec_path, output):
    # Only use local frozen package/policy fields; SSH/token-file entries are
    # never dereferenced, and no remote controller or Gateway is contacted.
    spec = json.loads(Path(spec_path).read_bytes())
    task = Path(spec["task_dir"])
    fixture = json.loads((task / "tests/fixture.json").read_bytes())
    metadata = json.loads((task / "tests/metadata.json").read_bytes())
    private_output(output)
    report = dict(
        passed=False,
        scope="real Docker scripted cleanup; no GPU/student/training",
        cases=[],
        task_ref=spec["policy_template"]["task_refs"][0],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    first_request = None
    try:
        with JobLedger(output / "jobs.sqlite") as ledger:
            for mode in ("truncated", "positive"):
                session = "cleanup-" + uuid.uuid4().hex
                scripted = (
                    TruncatedPolicy()
                    if mode == "truncated"
                    else Policy("positive", fixture=fixture, candidate=metadata["candidate_tool_name"])
                )
                server, thread, requests, errors = start_server(scripted, session, api_key="EMPTY")
                worker = None
                try:
                    policy = RequestPolicy.model_validate(
                        {
                            **spec["policy_template"],
                            "gateway_host": "127.0.0.1",
                            "gateway_port": server.server_port,
                            "model_name": MODEL,
                            "tunnel_alias": "local-cleanup",
                        }
                    )
                    # Reopen the worker over the SAME ledger/root. This proves
                    # release survives a worker lifecycle, with no ledger edit.
                    worker = HarborWorker(
                        ledger=ledger,
                        policy=policy,
                        worker_id="local-cleanup-worker",
                        task_dir=task,
                        root=output / "jobs",
                        gateway_base_url=f"http://host.docker.internal:{server.server_port}",
                    )
                    if first_request is not None:
                        assert worker.submit(first_request)["status"] == "cancelled"
                        assert not requests
                    data = dict(
                        schema="dsh.harbor-job-request.v1",
                        job_id="job-" + session,
                        idempotency_key="idem-" + session,
                        run_id="cleanup-smoke",
                        group_uid="group-" + session,
                        sample_index=0,
                        partition_id="test",
                        gateway_session_id=session,
                        nonce=uuid.uuid4().hex,
                        task_ref=policy.task_refs[0].model_dump(),
                        dsh_release=policy.dsh_release.model_dump(),
                        model_route=dict(
                            gateway_host=policy.gateway_host,
                            gateway_port=policy.gateway_port,
                            model_name=MODEL,
                            tunnel_alias=policy.tunnel_alias,
                            session_path=f"/sessions/{session}/v1",
                        ),
                        budgets=dict(
                            deadline_unix=time.time() + 300,
                            wall_time_seconds=300.0,
                            cpus=1.0,
                            memory_mb=2048,
                            max_tokens=512,
                            max_artifact_bytes=16 * 1024 * 1024,
                        ),
                    )
                    data["request_sha256"] = request_sha256(data)
                    worker.submit(data)
                    await asyncio.wait_for(worker.wait(data["job_id"]), timeout=360)
                    state = worker.status(data["job_id"])
                    check_terminal(mode, state)
                    if errors or not requests:
                        raise RuntimeError("Scripted model server failed or was never invoked")
                    case = dict(
                        mode=mode,
                        job_id=data["job_id"],
                        state=state["status"],
                        manifest=state["manifest"],
                        request_count=len(requests),
                        server_errors=errors,
                    )
                    statuses = list((output / "jobs" / data["job_id"]).glob("trials/*/*/agent/dsh/status.json"))
                    if len(statuses) != 1:
                        raise RuntimeError("Expected one native DSH status")
                    status = json.loads(statuses[0].read_bytes())
                    case["dsh_finished"], case["dsh_finish_reason"] = status["finished"], status["finish_reason"]
                    if mode == "truncated":
                        if status["finished"] is not False or status["finish_reason"] != "max-tokens":
                            raise RuntimeError("Native runtime did not record the intended token truncation")
                        first_request = data
                    else:
                        artifact = next(a for a in state["manifest"]["artifacts"] if a["kind"] == "reward")
                        reward = float(worker.artifact(data["job_id"], artifact["id"]))
                        if reward != 1.0:
                            raise RuntimeError("Next positive task did not score 1")
                        case["reward"] = reward
                    report["cases"].append(case)
                finally:
                    if worker is not None:
                        await worker.close()
                    await asyncio.to_thread(server.shutdown)
                    server.server_close()
                    await asyncio.to_thread(thread.join, 5)
            report["ledger_statuses"] = [
                list(row) for row in ledger.db.execute("SELECT status,count(*) FROM jobs GROUP BY status")
            ]
            report["passed"] = True
    finally:
        (output / "cleanup-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.spec, args.output.absolute())), indent=2))


if __name__ == "__main__":
    main()
