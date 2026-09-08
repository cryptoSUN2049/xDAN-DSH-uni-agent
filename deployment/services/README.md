# Harbor worker (single fixed run)

Run on the existing Docker host with the pinned Harbor 0.16.1 environment.
`harbor_worker.py` binds only `127.0.0.1`. A run token is required for every
request; keep its file mode at `0600`, outside the repository. Do not place it
in task instructions, container environment or model requests.

```sh
PYTHONPATH=. /private/tmp/harbor-h0-20260908/bin/python deployment/services/harbor_worker.py \
  --policy /private/run/request-policy.json --token-file /private/run/worker-token \
  --root /private/run/worker --task-dir examples/harbor/m2-file-write \
  --worker-id worker-1 --gateway-origin http://host.docker.internal:LOCAL_FORWARD_PORT \
  --port 47880 --max-runtime 3600
```

Replace the policy and route with independently registered run identities.
`RequestPolicy` is defined in `uni_agent/tasks/harbor_dsh/protocol.py`. Its
Gateway node IP/port must match the actual Gateway actor; the local forward
must point at that pair. Never build the approval policy from a submitted job.
Dynamic route registration and the trainer-side Task are still pending.

The RunPod controller reaches this loopback service through the previously
verified SSH reverse forward. It sends `Authorization: Bearer <run token>` to:

- `POST /v1/jobs`: validated job request, returns 202 and the accepted hash.
- `GET /v1/jobs/{id}`: durable state; `unconfirmed` requires cleanup reconciliation.
- `POST /v1/jobs/{id}/cancel`: requests stop; does not claim cleanup succeeded.
- `GET /v1/jobs/{id}/manifest`: only a sealed result, otherwise 409.
- `GET /v1/jobs/{id}/artifacts/{opaque_id}`: only manifest-listed, hash-checked bytes.

The request body limit is 64 KiB. One job executes at a time. Reopening the
SQLite ledger does not resume queued/running jobs or erase their identities.
A failure whose cleanup is unknown keeps the ledger slot occupied, records
only its exception class, and never retries automatically. This first worker
has no automatic reconciliation endpoint; inspect the job's actual resources
before explicitly resolving its state. Successful execution requires the
executor's cleanup check and complete bounded artifacts before sealing.

The service deadline closes HTTP then cancels active work. It does not stop or
delete the GPU server. No model run is implied by the HTTP unit tests.
