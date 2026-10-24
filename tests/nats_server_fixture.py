"""Optional isolated local JetStream server for public transport workflows."""

import asyncio
from contextlib import asynccontextmanager
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path


NATS_SERVER = os.environ.get("LAB_SYNC_NATS_SERVER") or shutil.which("nats-server")


@asynccontextmanager
async def temporary_jetstream_server(*, authorization: str | None = None):
    async with restartable_jetstream_server(authorization=authorization) as server:
        yield server.url


class JetStreamServer:
    """Restart one isolated broker without replacing its address or durable store."""

    def __init__(self, arguments, url):
        self.arguments = arguments
        self.url = url
        self.process = None

    async def start(self):
        if self.process is not None:
            raise RuntimeError("Test broker is already running")
        self.process = subprocess.Popen(
            self.arguments, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        async def ready():
            while True:
                line = await asyncio.to_thread(self.process.stderr.readline)
                if "Server is ready" in line:
                    return
                if not line:
                    raise RuntimeError("Temporary NATS server exited before readiness")
        await asyncio.wait_for(ready(), 15)

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process.stderr.close()
            self.process = None


@asynccontextmanager
async def restartable_jetstream_server(*, authorization: str | None = None):
    with tempfile.TemporaryDirectory(prefix="lab-sync-jetstream-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        arguments = [NATS_SERVER, "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", directory]
        if authorization is not None:
            config = Path(directory) / "broker.conf"
            config.write_text("authorization {\n" + authorization + "\n}\n", encoding="utf-8")
            arguments.extend(("-c", str(config)))
        server = JetStreamServer(arguments, f"nats://127.0.0.1:{port}")
        try:
            await server.start()
            yield server
        finally:
            server.stop()
