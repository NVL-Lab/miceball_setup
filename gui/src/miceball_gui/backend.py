"""Browser connection binding; all framework work remains behind external NATS."""

import argparse
import asyncio
import json
import math
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web, WSMsgType
from lab_sync_acquisition import (ExternalControllerRequest, ExternalSessionLaunchRequest,
    NatsCommunicationBoundary, NatsExternalSessionLaunchClient)
from lab_sync_acquisition.communication import SERVICE_RECOVERY_COMMAND_TYPES

READS = {"read_controller_state", "read_operation_outcome", "read_session_configuration", "get_node_inventory", "read_service_status", "read_synchronization_status"}
OPERATIONS = READS | {"take_browser_control", "view_only", "launch_session", "start_launched_session",
    "start_launched_experiment", "stop_launched_experiment", "reconcile_launched_experiment_expiry",
    "normal_stop_session", "release_session", "kill_session", "stop_service", "kill_service", "cancel_service", "shutdown_framework"} | SERVICE_RECOVERY_COMMAND_TYPES


class _ConnectedShell(HTMLParser):
    """Retain shared presenters and mark their single connected execution mode."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            values["data-runtime"] = "connected"
            self.parts.append("<html " + " ".join(f'{k}="{escape(v or "", quote=True)}"' for k, v in values.items()) + ">")
        else:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "body":
            self.parts.append('<script type="module" src="connected.js"></script>')
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")


def create_gui_app(*, servers, controller_id, client_id, origin, timeout_s, max_request_bytes=1048576):
    """Serve the existing shell and connection-bound commands via one NATS client."""
    if (not servers or not controller_id or not client_id or type(timeout_s) not in (float, int)
            or not math.isfinite(timeout_s) or timeout_s <= 0
            or type(max_request_bytes) is not int or max_request_bytes <= 0):
        raise ValueError("Explicit connection identities and positive bounds are required")
    url = urlsplit(origin)
    if url.scheme not in {"http", "https"} or not url.netloc or url.path or url.query or url.fragment:
        raise ValueError("An exact public HTTP(S) origin without path is required")
    boundary = NatsCommunicationBoundary("client", client_id, tuple(servers))
    client = NatsExternalSessionLaunchClient(boundary)
    sockets = set()
    connection = None

    async def transport():
        nonlocal connection
        if boundary.connected:
            return
        if connection is None or (connection.done() and (connection.cancelled() or connection.exception() is not None)):
            connection = asyncio.create_task(boundary.connect())
            connection.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        done, _ = await asyncio.wait([connection], timeout=timeout_s)
        if not done:
            raise ConnectionError("NATS initial connection remains unconfirmed")
        await asyncio.shield(connection)

    @web.middleware
    async def same_origin(request, handler):
        if request.host != url.netloc:
            raise web.HTTPForbidden(text="Unexpected Host")
        if request.path == "/ws" and request.headers.get("Origin") != origin:
            raise web.HTTPForbidden(text="Same-origin browser connection required")
        response = await handler(request)
        if request.path != "/ws":
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        return response

    app = web.Application(middlewares=[same_origin], client_max_size=max_request_bytes)

    async def startup(app):
        # Serving the page does not require a live broker; requests verify transport.
        return None

    async def cleanup(app):
        for socket in tuple(sockets):
            await socket.close(code=1001, message=b"Backend shutting down")
        if connection is not None and not connection.done():
            connection.cancel()
            await asyncio.gather(connection, return_exceptions=True)
        await boundary.close()

    async def connect(request):
        socket = web.WebSocketResponse(max_msg_size=max_request_bytes, heartbeat=20)
        await socket.prepare(request)
        sockets.add(socket)
        browser_id = uuid4().hex
        context = {"browser_id": browser_id, "instance_id": None, "generation": 0}
        await socket.send_json({"type": "connected", "browser_id": browser_id})

        async def submit(operation, parameters, session_id, identifier):
            await transport()
            envelope = dict(controller_id=controller_id, client_id=client_id, request_id=identifier,
                            browser_context=dict(context))
            if operation == "launch_session":
                model = ExternalSessionLaunchRequest(**envelope, **parameters)
                return await client.request_launch(model, timeout_s=timeout_s)
            model = ExternalControllerRequest(**envelope, operation=operation, session_id=session_id,
                                              parameters=parameters)
            result = await client.request_operation(model, timeout_s=timeout_s)
            # Repeating read-only requests can never dispatch a lifecycle command.
            deadline = asyncio.get_running_loop().time() + timeout_s
            while operation in READS and result.status == "pending" and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(.05)
                result = await client.request_operation(model, timeout_s=timeout_s)
            if operation == "read_controller_state" and result.status == "succeeded":
                state = result.outcome["details"]
                if state["browser_control_required"] is not True:
                    raise ValueError("Controller must configure browser_control_required=true for this GUI client")
                context.update(instance_id=state["instance_id"], generation=state["control"]["generation"])
            return result

        try:
            async for message in socket:
                if message.type != WSMsgType.TEXT:
                    continue
                identifier = None
                try:
                    data = json.loads(message.data)
                    if (isinstance(data, dict) and isinstance(data.get("id"), str)
                            and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", data["id"])):
                        identifier = data["id"]
                    if (not isinstance(data, dict) or set(data) != {"id", "operation", "session_id", "parameters"}
                            or not isinstance(data["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", data["id"])
                            or data["operation"] not in OPERATIONS or not isinstance(data["parameters"], dict)):
                        raise ValueError("Invalid bounded browser request")
                    if data["operation"] == "launch_session" and set(data["parameters"]) != {
                            "selections", "config_parameters", "scientific_outputs"}:
                        raise ValueError("Launch accepts only framework selections/configuration/outputs")
                    # Browser identity and routing identity are never taken from JSON.
                    result = await submit(data["operation"], data["parameters"], data["session_id"],
                                          browser_id + "-" + identifier)
                    if socket.closed:
                        break
                    await socket.send_json({"type": "result", "id": identifier, "instance_id": context["instance_id"],
                                            "result": result.to_dict()})
                except (ValueError, TypeError, KeyError) as error:
                    await socket.send_json({"type": "result", "id": identifier, "status": "rejected", "error": str(error)})
                except (ConnectionError, RuntimeError, OSError) as error:
                    if socket.closed:
                        break
                    await socket.send_json({"type": "result", "id": identifier, "status": "uncertain", "error": str(error)})
        finally:
            sockets.discard(socket)
        return socket

    static = Path(__file__).with_name("static")

    async def index(request):
        # Presenters select fixture execution or connected bindings from this marker.
        text = (static / "index.html").read_text(encoding="utf-8")
        shell = _ConnectedShell()
        shell.feed(text)
        shell.close()
        return web.Response(text="".join(shell.parts), content_type="text/html")

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    app.router.add_get("/ws", connect)
    app.router.add_static("/", static, show_index=False, follow_symlinks=False)
    return app


def main():
    """Start only the separately packaged web client, never framework services."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="append", required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    args = parser.parse_args()
    web.run_app(create_gui_app(servers=args.server, controller_id=args.controller, client_id=args.client,
        origin=args.origin, timeout_s=args.timeout), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
