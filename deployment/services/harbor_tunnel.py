"""Owned, bounded OpenSSH master lifecycle; credentials stay on the Mac."""

import asyncio
import os
import signal


class SshTunnel:
    def __init__(self, spec, *, kind, gateway_port=None, spawn=asyncio.create_subprocess_exec):
        self.spec, self.kind, self.spawn = spec, kind, spawn
        self.socket = spec.root / (kind + ".sock")
        self.log = spec.root / (kind + "-ssh.log")
        self.process = None
        destination = f"{spec.ssh_user}@{spec.ssh_host}"
        self.check_argv = ["ssh", "-S", str(self.socket), "-O", "check", destination]
        self.argv = [
            "ssh",
            "-N",
            "-M",
            "-S",
            str(self.socket),
            "-p",
            str(spec.ssh_port),
            "-i",
            str(spec.ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={spec.known_hosts}",
            "-o",
            "ControlPersist=no",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=2",
        ]
        if kind == "control":
            self.argv += [
                "-R",
                f"127.0.0.1:{spec.remote_control_port}:127.0.0.1:{spec.control_port}",
                "-R",
                f"127.0.0.1:{spec.remote_worker_port}:127.0.0.1:{spec.worker_port}",
            ]
        elif kind == "model" and type(gateway_port) is int and 1 <= gateway_port <= 65535:
            self.argv += ["-L", f"127.0.0.1:{spec.model_port}:{spec.policy_template['gateway_host']}:{gateway_port}"]
        else:
            raise ValueError("Unsupported tunnel kind or port")
        self.argv.append(destination)

    @property
    def alive(self):
        return self.process is not None and self.process.returncode is None

    async def start(self):
        if self.process is not None or self.socket.exists():
            raise ValueError("Tunnel cannot reuse process or control socket")
        descriptor = os.open(self.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            self.process = await self.spawn(
                *self.argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=descriptor
            )
        finally:
            os.close(descriptor)
        try:
            async with asyncio.timeout(15):
                while self.alive:
                    if self.socket.exists():
                        check = await self.spawn(
                            *self.check_argv,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        try:
                            code = await asyncio.wait_for(check.wait(), 1)
                        finally:
                            if check.returncode is None:
                                check.kill()
                            await asyncio.wait_for(check.wait(), 3)
                        if code == 0 and self.alive:
                            return
                    await asyncio.sleep(0.05)
                raise RuntimeError("Owned SSH tunnel exited before readiness")
        except BaseException:
            await self.close()
            raise

    async def close(self):
        process = self.process
        if process is None:
            return
        if process.returncode is None:
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await asyncio.wait_for(process.wait(), 3)
        else:
            await process.wait()
