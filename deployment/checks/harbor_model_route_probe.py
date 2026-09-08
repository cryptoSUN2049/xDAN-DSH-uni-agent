"""Probe Docker-to-RunPod session HTTP routing without a model call."""

import argparse
import json
import shlex
import socket
import subprocess
import time
import uuid
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh-host", required=True)
parser.add_argument("--ssh-port", type=int, required=True)
parser.add_argument("--ssh-key", type=Path, required=True)
parser.add_argument("--image", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise ValueError("Output must be new")
if args.ssh_host.startswith("-"):
    raise ValueError("Invalid SSH destination")
nonce = uuid.uuid4().hex
container_name = "dsh-route-" + nonce[:12]
path = "/sessions/route-" + nonce + "/v1/chat/completions"
remote = r"""
import http.server,json,socket,sys,time
class H(http.server.BaseHTTPRequestHandler):
 def do_POST(self):
  data=self.rfile.read(int(self.headers.get('Content-Length','0')))
  body=json.dumps({'path':self.path,'body':json.loads(data)}).encode()
  self.server.received=True
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
address=socket.gethostbyname(socket.gethostname())
s=http.server.HTTPServer((address,0),H);s.timeout=90
print(json.dumps({'address':address,'port':s.server_port}),flush=True)
s.received=False
deadline=time.monotonic()+90
while not s.received and time.monotonic()<deadline:s.handle_request()
s.server_close()
"""
ssh = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "-i",
    str(args.ssh_key.expanduser()),
    "-p",
    str(args.ssh_port),
]
server = None
tunnel = None
try:
    server = subprocess.Popen(
        ssh + [args.ssh_host, "timeout 100 python3 -u -c " + shlex.quote(remote)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    import select

    if not select.select([server.stdout], [], [], 25)[0]:
        raise RuntimeError("remote probe did not become ready")
    endpoint = json.loads(server.stdout.readline())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tunnel = subprocess.Popen(
        ssh
        + [
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"127.0.0.1:{port}:{endpoint['address']}:{endpoint['port']}",
            args.ssh_host,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(100):
        if tunnel.poll() is not None:
            raise RuntimeError(tunnel.stderr.read())
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    code = (
        "import urllib.request,json; req=urllib.request.Request("
        + repr(f"http://host.docker.internal:{port}" + path)
        + ",data="
        + repr(json.dumps({"nonce": nonce}).encode())
        + ",headers={'Content-Type':'application/json'}); print(urllib.request.urlopen(req,timeout=20).read().decode())"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--platform",
            "linux/amd64",
            "--memory",
            "256m",
            "--cpus",
            "1",
            args.image,
            "python",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    actual = json.loads(result.stdout)
    assert actual == {"path": path, "body": {"nonce": nonce}}, actual
    report = {
        "schema": "dsh.harbor-model-route-probe.v1",
        "passed": True,
        "route": "Docker host.docker.internal -> Mac loopback SSH local forward -> RunPod node IP HTTP probe",
        "session_path_preserved": True,
        "body_nonce_preserved": True,
        "actual_gateway_used": False,
        "model_called": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
finally:
    for p in (tunnel, server):
        if p is not None:
            if p.poll() is None:
                p.terminate()
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
