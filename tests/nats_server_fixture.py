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

CONTROLLER_AUTHORITY_SERVER_CONFIGURATION = (
    'system_account: SYS\naccounts {\nSYS {}\nLAB {\njetstream: enabled\n'
    'users: [{user: demo, password: demo}]\n}\n}\n')


async def acquire_test_controller_authority(test_case, maintenance):
    """Give an existing public workflow an isolated real Controller claim with owned cleanup."""
    if not NATS_SERVER:
        test_case.skipTest("Set LAB_SYNC_NATS_SERVER for Controller authority workflows")
    import nats
    from nats.js.api import KeyValueConfig, StorageType
    from lab_sync_acquisition import NatsCommunicationBoundary
    server = await test_case.enterAsyncContext(restartable_jetstream_server(
        server_configuration=CONTROLLER_AUTHORITY_SERVER_CONFIGURATION))
    url = server.url.replace("nats://", "nats://demo:demo@")
    client = await nats.connect(url)
    test_case.addAsyncCleanup(client.close)
    await client.jetstream().create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))
    boundary = NatsCommunicationBoundary("controller", maintenance.participant.component_id, (url,))
    await boundary.connect()
    test_case.addAsyncCleanup(boundary.close)
    await maintenance.acquire_controller_authority(boundary, account="LAB", bucket="AUTHORITY",
                                                   key="controller", timeout_s=2)
    return boundary


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
async def restartable_jetstream_server(*, authorization: str | None = None,
                                     server_configuration: str | None = None):
    with tempfile.TemporaryDirectory(prefix="lab-sync-jetstream-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        arguments = [NATS_SERVER, "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", directory]
        if authorization is not None or server_configuration is not None:
            config = Path(directory) / "broker.conf"
            config.write_text(("authorization {\n" + authorization + "\n}\n" if authorization else "")
                              + (server_configuration or ""), encoding="utf-8")
            arguments.extend(("-c", str(config)))
        server = JetStreamServer(arguments, f"nats://127.0.0.1:{port}")
        try:
            await server.start()
            yield server
        finally:
            server.stop()
