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
    with tempfile.TemporaryDirectory(prefix="lab-sync-jetstream-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        arguments = [NATS_SERVER, "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", directory]
        if authorization is not None:
            config = Path(directory) / "broker.conf"
            config.write_text("authorization {\n" + authorization + "\n}\n", encoding="utf-8")
            arguments.extend(("-c", str(config)))
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            async def ready():
                while True:
                    line = await asyncio.to_thread(process.stderr.readline)
                    if "Server is ready" in line:
                        return
                    if not line:
                        raise RuntimeError("Temporary NATS server exited before readiness")
            await asyncio.wait_for(ready(), 15)
            yield f"nats://127.0.0.1:{port}"
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stderr.close()
