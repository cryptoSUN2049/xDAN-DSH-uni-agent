"""Start one authenticated, loopback-only Harbor worker for a fixed run."""

import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import web

from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.protocol import RequestPolicy
from uni_agent.tasks.harbor_dsh.worker import HarborWorker
from uni_agent.tasks.harbor_dsh.worker_http import create_app


async def main(args):
    if args.token_file.stat().st_mode & 0o077:
        raise ValueError("Token file must not be accessible to group or other users")
    token = args.token_file.read_text().strip()
    policy = RequestPolicy.model_validate(json.loads(args.policy.read_text()))
    with JobLedger(args.root / "jobs.sqlite") as ledger:
        worker = HarborWorker(
            ledger=ledger,
            policy=policy,
            worker_id=args.worker_id,
            task_dir=args.task_dir,
            root=args.root / "jobs",
            gateway_base_url=args.gateway_origin,
        )
        runner = web.AppRunner(create_app(worker, token=token), access_log=None)
        try:
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", args.port).start()
            print(
                json.dumps(
                    {
                        "status": "listening",
                        "host": "127.0.0.1",
                        "port": args.port,
                        "worker_id": args.worker_id,
                        "max_runtime": args.max_runtime,
                    }
                ),
                flush=True,
            )
            await asyncio.sleep(args.max_runtime)
        finally:
            await runner.cleanup()
            await worker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--gateway-origin", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--max-runtime", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.max_runtime <= 14400:
        parser.error("port or runtime outside supported range")
    asyncio.run(main(args))
