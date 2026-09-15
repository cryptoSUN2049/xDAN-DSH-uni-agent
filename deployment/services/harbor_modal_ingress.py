"""Controller-owned named Cloudflare ingress for session model traffic only."""

import asyncio
import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from multidict import CIMultiDict
from pydantic import BaseModel, ConfigDict, field_validator
from yarl import URL

from uni_agent.tasks.harbor_dsh.environment_backend import validate_gateway_origin
from uni_agent.tasks.harbor_dsh.protocol import Port


def require_external_private_path(path: Path) -> None:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and path.resolve().is_relative_to(parent):
            raise ValueError("Modal private paths must be outside the repository")


class ModalIngressConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: str
    tunnel_id: UUID
    credentials_file: Path
    listen_port: Port

    @field_validator("origin")
    @classmethod
    def _origin(cls, value):
        value = validate_gateway_origin(value, backend="modal")
        if urlsplit(value).port not in (None, 443):
            raise ValueError("Named tunnel requires default HTTPS port")
        return value

    @field_validator("credentials_file")
    @classmethod
    def _credential_path(cls, value):
        if not value.is_absolute() or ".." in value.parts:
            raise ValueError("Tunnel credential path must be absolute and traversal-free")
        require_external_private_path(value)
        return value


def _headers(headers):
    blocked = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
    }
    for connection in headers.getall("Connection", []):
        blocked.update(part.strip().lower() for part in connection.split(","))
    return CIMultiDict((name, value) for name, value in headers.items() if name.lower() not in blocked)


def proxy_app(upstream: str, probe_path: str, nonce: str):
    """Forward bounded model paths to a fixed loopback origin without buffering SSE."""
    app = web.Application(client_max_size=16 * 1024 * 1024)
    route = re.compile(r"/sessions/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/v1/(?:chat/completions|messages)")
    session_key = web.AppKey("upstream", ClientSession)

    async def lifecycle(app):
        async with ClientSession(auto_decompress=False, timeout=ClientTimeout(total=None, sock_connect=10)) as client:
            app[session_key] = client
            yield

    app.cleanup_ctx.append(lifecycle)

    async def handle(request):
        if request.path == probe_path and request.method == "GET" and not request.query_string:
            return web.Response(text=nonce, headers={"Cache-Control": "no-store"})
        if not route.fullmatch(request.path) or "%" in request.raw_path.split("?", 1)[0]:
            raise web.HTTPNotFound()
        expected_method = "POST"
        if request.method != expected_method:
            raise web.HTTPMethodNotAllowed(request.method, [expected_method])
        response = None
        try:
            async with app[session_key].request(
                request.method,
                URL(upstream + request.raw_path, encoded=True),
                headers=_headers(request.headers),
                data=request.content.iter_chunked(65536),
                allow_redirects=False,
            ) as remote:
                response = web.StreamResponse(status=remote.status, headers=_headers(remote.headers))
                await response.prepare(request)
                async for chunk in remote.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (ClientError, OSError, TimeoutError):
            if response is not None and response.prepared:
                response.force_close()
                if request.transport is not None:
                    request.transport.close()
                return response
            raise web.HTTPBadGateway() from None

    app.router.add_route("*", "/{tail:.*}", handle)
    return app


class ModalIngress:
    def __init__(self, spec, *, spawn=asyncio.create_subprocess_exec):
        self.spec, self.config, self.spawn = spec, spec.modal_ingress, spawn
        self.process = self.runner = None
        self.nonce = secrets.token_urlsafe(32)
        self.probe_path = "/_harbor_probe/" + secrets.token_urlsafe(32)
        self.ready = False
        self.started = False

    @property
    def alive(self):
        return self.ready and self.process is not None and self.process.returncode is None

    async def _probe(self, client, url):
        try:
            async with client.get(url, allow_redirects=False, timeout=ClientTimeout(total=2)) as response:
                body = bytearray()
                limit = len(self.nonce.encode()) + 1
                while len(body) < limit:
                    chunk = await response.content.read(limit - len(body))
                    if not chunk:
                        break
                    body.extend(chunk)
                return response.status == 200 and body == self.nonce.encode()
        except (ClientError, OSError, TimeoutError):
            return False

    async def start(self):
        if self.started:
            raise ValueError("Modal ingress cannot restart")
        self.started = True
        descriptor = os.open(self.config.credentials_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Tunnel credentials must be owned, regular and private")
            credentials = source.read(65537)
        if len(credentials) > 65536:
            raise ValueError("Tunnel credentials exceed size bound")
        credential_copy = self.spec.root / "modal-tunnel-credentials.json"
        config_path = self.spec.root / "modal-tunnel.json"
        for path, body in (
            (credential_copy, credentials),
            (
                config_path,
                json.dumps(
                    {
                        "tunnel": str(self.config.tunnel_id),
                        "credentials-file": str(credential_copy),
                        "ingress": [
                            {
                                "hostname": urlsplit(self.config.origin).hostname,
                                "service": f"http://127.0.0.1:{self.config.listen_port}",
                            },
                            {"service": "http_status:404"},
                        ],
                    }
                ).encode(),
            ),
        ):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
        try:
            self.runner = web.AppRunner(
                proxy_app(f"http://127.0.0.1:{self.spec.model_port}", self.probe_path, self.nonce), access_log=None
            )
            await self.runner.setup()
            await web.TCPSite(self.runner, "127.0.0.1", self.config.listen_port).start()
            self.process = await self.spawn(
                "cloudflared",
                "tunnel",
                "--config",
                str(config_path),
                "--no-autoupdate",
                "run",
                str(self.config.tunnel_id),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(30), ClientSession() as client:
                while self.process.returncode is None:
                    if await self._probe(client, self.config.origin + self.probe_path):
                        self.ready = True
                        return
                    await asyncio.sleep(0.2)
                raise RuntimeError("Owned Modal tunnel exited before readiness")
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self.ready = False
        try:
            if self.process is not None and self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 5)
                except TimeoutError:
                    self.process.kill()
                    await asyncio.wait_for(self.process.wait(), 5)
        finally:
            if self.runner is not None:
                await self.runner.cleanup()
                self.runner = None
