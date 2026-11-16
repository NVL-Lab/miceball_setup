"""Exact deployment credentials across existing public connection workflows."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from lab_sync_acquisition import NatsCommunicationBoundary, RuntimeParticipant
from lab_sync_acquisition.nats_configuration import load_nats_configuration, report_nats_error
from lab_sync_acquisition.service_maintenance_cli import request_service_maintenance, recover_controller_claim
from tests.nats_server_fixture import NATS_SERVER, restartable_jetstream_server


class NatsAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def credentials(self, suffix=""):
        return {"nats_username": uuid4().hex, "nats_password": uuid4().hex + suffix}

    def test_invalid_authentication_never_constructs_an_sdk_client(self):
        user, password = uuid4().hex, uuid4().hex
        cases = [{"nats_username": user}, {"nats_password": password}]
        for bad in ("", None, 0, False, [], {}):
            cases.extend(({"nats_username": user, "nats_password": bad},
                          {"nats_username": bad, "nats_password": password}))
        for fields in cases:
            with self.subTest(fields=list(fields)), patch("lab_sync_acquisition.nats_communication.NATS") as sdk:
                with self.assertRaises(ValueError) as failure:
                    NatsCommunicationBoundary("terminal", "test", ("nats://example.invalid:4222",), **fields)
                self.assertNotIn(user, str(failure.exception))
                self.assertNotIn(password, str(failure.exception))
                sdk.assert_not_called()
        for url in ("nats://@example.invalid:4222", "nats://token@example.invalid:4222",
                    "nats://user:pass@example.invalid:4222", "nats://example.invalid:invalid"):
            with self.subTest(url_kind=url.split(":")[0]), self.assertRaises(ValueError):
                NatsCommunicationBoundary("terminal", "test", ("nats://first.invalid:4222", url),
                    nats_username=user, nats_password=password)

    async def test_runtime_exact_strings_and_legacy_urls(self):
        for suffix in ("", "@:/?#%40&=+", "\r\n\t ", "\u03bb\U0001f9ea", "\x00"):
            auth = self.credentials(suffix)
            boundary = NatsCommunicationBoundary("terminal", "test",
                ("nats://first.invalid:4222", "nats://second.invalid:4222"), **auth)
            client = SimpleNamespace(connect=AsyncMock(), options={}, jetstream=lambda: None,
                is_connected=False, is_closed=False, close=AsyncMock())
            with patch("lab_sync_acquisition.nats_communication.NATS", return_value=client):
                await boundary.connect()
                await boundary.close()
            options = client.connect.call_args.kwargs
            self.assertEqual(options["user"], auth["nats_username"])
            self.assertEqual(options["password"], auth["nats_password"])
            self.assertEqual(options["servers"], ["nats://first.invalid:4222", "nats://second.invalid:4222"])
        for url in ("nats://example.invalid:4222", "nats://user:literal%40@example.invalid:4222"):
            client.connect.reset_mock()
            boundary = NatsCommunicationBoundary("terminal", "test", (url,))
            with patch("lab_sync_acquisition.nats_communication.NATS", return_value=client):
                await boundary.connect()
                await boundary.close()
            self.assertEqual(client.connect.call_args.kwargs["servers"], [url])
            self.assertNotIn("user", client.connect.call_args.kwargs)
            self.assertNotIn("password", client.connect.call_args.kwargs)

    async def test_connection_errors_and_callbacks_do_not_disclose_credentials(self):
        auth = self.credentials("@:/?#%")
        secret = json.dumps(auth)
        client = SimpleNamespace(connect=AsyncMock(side_effect=ValueError(secret)), options={},
            is_connected=False, is_closed=False, close=AsyncMock())
        boundary = NatsCommunicationBoundary("terminal", "test", ("nats://example.invalid:4222",), **auth)
        with patch("lab_sync_acquisition.nats_communication.NATS", return_value=client):
            with self.assertRaises(ConnectionError) as failure:
                await boundary.connect()
        self.assertIsNone(failure.exception.__context__)
        self.assertIsNone(failure.exception.__cause__)
        output = ''.join(traceback.format_exception(failure.exception))
        with self.assertLogs("lab_sync_acquisition.deployment", level="WARNING") as logs:
            await report_nats_error(ValueError(secret))
        output += '\n'.join(logs.output)
        for value in auth.values():
            self.assertNotIn(value, output)
        self.assertIn("ValueError", output)

    async def test_authenticated_cleanup_error_retains_ownership_without_secret_exception_chain(self):
        auth = self.credentials()
        client = SimpleNamespace(connect=AsyncMock(), options={}, jetstream=lambda: None,
            is_connected=False, is_closed=False, close=AsyncMock(side_effect=OSError(auth["nats_password"])))
        boundary = NatsCommunicationBoundary("terminal", "test", ("nats://example.invalid:4222",), **auth)
        with patch("lab_sync_acquisition.nats_communication.NATS", return_value=client):
            await boundary.connect()
            for _ in range(2):
                with self.assertRaises(ConnectionError) as failure:
                    await boundary.close()
                self.assertIsNone(failure.exception.__context__)
                self.assertNotIn(auth["nats_password"], ''.join(traceback.format_exception(failure.exception)))
            with self.assertRaisesRegex(RuntimeError, "owned NATS client"):
                await boundary.connect()

    def test_connection_file_loading_preserves_values_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.json"
            auth = self.credentials(" \r\n\t%40\u03bb ")
            data = {"servers": ["nats://example.invalid:4222"], **auth, "service_id": "owner"}
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_nats_configuration(path)
            self.assertEqual(loaded, {k: v for k, v in data.items() if k != "service_id"})
            path.write_text('{"servers": [], "servers": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_nats_configuration(path)

    async def test_maintenance_and_claim_paths_forward_without_secret_command_flags(self):
        auth = self.credentials("@% ")
        class Stopped(Exception):
            pass
        for operation in (lambda: request_service_maintenance(servers=("nats://example.invalid:4222",),
                participant=RuntimeParticipant("controller", "control"), operation="stop",
                administrator_id="operator", result_window_s=1, **auth),
                lambda: recover_controller_claim(servers=("nats://example.invalid:4222",),
                    account="LAB", bucket="AUTHORITY", key="controller", timeout_s=1, **auth)):
            with patch("lab_sync_acquisition.service_maintenance_cli.NatsCommunicationBoundary", side_effect=Stopped) as factory:
                with self.assertRaises(Stopped):
                    await operation()
                self.assertEqual(factory.call_args.kwargs, auth)

    def test_maintenance_cli_loads_credentials_from_file_without_password_flags(self):
        from lab_sync_acquisition.service_launcher import main
        auth = self.credentials("@% ")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'service.json'
            path.write_text(json.dumps({"servers": ["nats://example.invalid:4222"], **auth}), encoding='utf-8')
            for role in ('stop', 'inspect-controller-claim'):
                method = 'request_service_maintenance' if role == 'stop' else 'recover_controller_claim'
                args = [role, '--deployment-config', str(path), '--result-window-s', '1']
                args += (['--target-type', 'controller', '--target-id', 'control', '--administrator-id', 'operator']
                         if role == 'stop' else ['--controller-claim-account', 'LAB', '--controller-claim-bucket', 'AUTHORITY',
                                                '--controller-claim-key', 'controller'])
                with patch('lab_sync_acquisition.service_maintenance_cli.' + method, new_callable=AsyncMock, return_value=0) as operation:
                    self.assertEqual(main(args), 0)
                    for key, value in auth.items():
                        self.assertEqual(operation.call_args.kwargs[key], value)
                        self.assertNotIn(value, repr(args))

    @unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
    async def test_real_authenticated_connection_reconnect_and_legacy_control(self):
        auth = self.credentials("@:/?#%40&=+ \u03bb")
        legacy = self.credentials()
        users = [{"user": pair["nats_username"], "password": pair["nats_password"]} for pair in (auth, legacy)]
        config = 'accounts {\nLAB {\njetstream: enabled\nusers: ' + json.dumps(users, ensure_ascii=False) + '\n}\n}\n'
        async with restartable_jetstream_server(server_configuration=config) as server:
            boundary = NatsCommunicationBoundary("terminal", "test", (server.url,), **auth)
            try:
                await boundary.connect()
                await boundary.flush()
                self.assertTrue(boundary.check_ready().ready)
                legacy_url = server.url.replace('://', '://' + legacy['nats_username'] + ':' + legacy['nats_password'] + '@')
                old = NatsCommunicationBoundary("terminal", "legacy", (legacy_url,))
                try:
                    await old.connect()
                    await old.flush()
                finally:
                    await old.close()
                rejected = NatsCommunicationBoundary("terminal", "wrong", (server.url,),
                    nats_username=auth['nats_username'], nats_password=uuid4().hex)
                with self.assertRaises(ConnectionError) as failure:
                    await rejected.connect()
                for value in auth.values():
                    self.assertNotIn(value, ''.join(traceback.format_exception(failure.exception)))
                server.stop()
                async def wait_until(predicate):
                    async with asyncio.timeout(15):
                        while not predicate():
                            await asyncio.sleep(.02)
                await wait_until(lambda: not boundary.connected)
                await server.start()
                await wait_until(lambda: boundary.connected)
                await boundary.flush()
            finally:
                await boundary.close()
