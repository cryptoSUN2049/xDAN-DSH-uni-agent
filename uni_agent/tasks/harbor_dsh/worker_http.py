"""Authenticated loopback HTTP endpoints for the bounded Harbor worker."""

import hmac

from aiohttp import web


def create_app(worker, *, token: str) -> web.Application:
    if len(token) < 32 or token != token.strip():
        raise ValueError("A private run token of at least 32 characters is required")

    @web.middleware
    async def authenticate(request, handler):
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except KeyError:
            raise web.HTTPNotFound() from None
        except (ValueError, TypeError):
            # Do not return exception text containing local paths or request data.
            raise web.HTTPConflict(text="Request or job state rejected") from None

    def status(job):
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "accepted_request_sha256": job["request"]["request_sha256"],
            **({"unconfirmed": job["unconfirmed"]} if "unconfirmed" in job else {}),
        }

    async def submit(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        return web.json_response(status(worker.submit(data)), status=202)

    async def get_status(request):
        return web.json_response(status(worker.status(request.match_info["job_id"])))

    async def cancel(request):
        return web.json_response(status(await worker.cancel(request.match_info["job_id"])))

    async def manifest(request):
        return web.json_response(worker.manifest(request.match_info["job_id"]))

    async def artifact(request):
        content = worker.artifact(request.match_info["job_id"], request.match_info["artifact_id"])
        return web.Response(body=content, content_type="application/octet-stream")

    app = web.Application(middlewares=[authenticate], client_max_size=65536)
    app.router.add_post("/v1/jobs", submit)
    app.router.add_get("/v1/jobs/{job_id}", get_status)
    app.router.add_post("/v1/jobs/{job_id}/cancel", cancel)
    app.router.add_get("/v1/jobs/{job_id}/manifest", manifest)
    app.router.add_get("/v1/jobs/{job_id}/artifacts/{artifact_id}", artifact)
    return app
