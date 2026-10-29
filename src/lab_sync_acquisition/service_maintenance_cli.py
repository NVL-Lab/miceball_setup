"""One terminal invocation of existing addressed NATS service maintenance."""

from __future__ import annotations

import asyncio
import json
from math import isfinite
from uuid import uuid4

from lab_sync_acquisition.communication import RuntimeParticipant, build_runtime_subject
from lab_sync_acquisition.nats_communication import NatsCommunicationBoundary, NatsControllerCommunication


async def recover_controller_claim(*, servers, account, bucket, key, timeout_s,
                                   clear=False, expected_owner=None, expected_revision=None,
                                   administrator_id=None, authorized=False, termination_verified=False,
                                   termination_evidence=None, report=print):
    """Inspect, or clear an exact inspected claim after independent operator termination verification."""
    from dataclasses import asdict
    from lab_sync_acquisition.controller_authority import ControllerClaimSnapshot
    if (not servers or type(timeout_s) not in (int, float) or not isfinite(timeout_s) or timeout_s <= 0):
        raise ValueError("Explicit servers and positive finite timeout are required")
    if clear:
        snapshot = ControllerClaimSnapshot(account, bucket, key, expected_owner, expected_revision)
        if (authorized is not True or termination_verified is not True
                or any(not isinstance(v, str) or not v.strip() for v in (administrator_id, termination_evidence))):
            raise ValueError("Clearing requires explicit authorization and independently verified prior termination")
    elif any(v not in (None, False) for v in (expected_owner, expected_revision, authorized,
                                             termination_verified, termination_evidence, administrator_id)):
        raise ValueError("Inspection does not authorize clearing")
    boundary = NatsCommunicationBoundary("terminal", uuid4().hex, tuple(servers))
    boundary.configure_controller_authority(account=account, bucket=bucket, key=key, timeout_s=timeout_s)
    try:
        async with asyncio.timeout(timeout_s):
            await boundary.connect()
            if clear:
                await boundary.clear_controller_claim(snapshot, administrator_id=administrator_id,
                    authorized=authorized, termination_verified=termination_verified,
                    termination_evidence=termination_evidence, timeout_s=timeout_s)
                report(json.dumps({"outcome": "conditionally_cleared", "claim": asdict(snapshot),
                    "administrator_id": administrator_id, "termination_evidence": termination_evidence}, sort_keys=True))
            else:
                snapshot = await boundary.inspect_controller_claim(account=account, bucket=bucket, key=key, timeout_s=timeout_s)
                report(json.dumps({"outcome": "occupied", "claim": asdict(snapshot),
                    "operator_action": "Independently verify this exact Controller has terminated before authorizing conditional clearing. Network silence is not proof."}, sort_keys=True))
            return 0
    finally:
        await asyncio.wait_for(boundary.close(), timeout_s)


async def request_service_maintenance(*, servers, participant, operation, administrator_id,
                                      result_window_s, stop_attempt_id=None, authorized=False,
                                      report=print):
    """Request one owner operation; report existing outcomes, never infer process exit."""
    servers = tuple(servers)
    if (not servers or any(not isinstance(s, str) or not s.strip() for s in servers)
            or not isinstance(administrator_id, str) or not administrator_id.strip()
            or not isinstance(participant, RuntimeParticipant)
            or participant.component_type not in {"controller", "acquisition_node", "ingestor",
                                                  "storage_manager", "synchronization_manager"}
            or operation not in {"stop", "kill", "cancel"}
            or type(result_window_s) not in {int, float}
            or not isfinite(result_window_s) or result_window_s <= 0):
        raise ValueError("Explicit servers, service identity, administrator and positive finite result window are required")
    build_runtime_subject(None, "command", participant.component_type, participant.component_id, operation)
    if operation == "stop":
        if stop_attempt_id is not None or authorized:
            raise ValueError("Stop creates a new attempt; attempt continuation and authorization are for Kill/Cancel")
        stop_attempt_id = uuid4().hex
    elif not isinstance(stop_attempt_id, str) or not stop_attempt_id.strip():
        raise ValueError("Kill/Cancel require the existing blocked stop-attempt ID")
    if operation == "kill" and authorized is not True:
        raise ValueError("Kill requires explicit operator authorization")
    if operation == "cancel" and authorized:
        raise ValueError("Cancel does not authorize force")

    requester, command_id = uuid4().hex, uuid4().hex
    # This is an issuer transport, not a Controller or a new service owner.
    boundary = NatsCommunicationBoundary("terminal", requester, servers)
    requests = NatsControllerCommunication(boundary)
    payload = {"stop_attempt_id": stop_attempt_id, "administrator_id": administrator_id}
    if operation == "kill":
        payload["authorized"] = True
    result, error, subscription = None, None, None

    def matching(reply):
        if (reply.command_id != command_id or reply.session_id is not None
                or reply.source_id != participant.component_id or reply.target_id != requester
                or not isinstance(reply.result_id, str) or not reply.result_id
                or type(reply.success) is not bool or reply.status not in {"succeeded", "failed"}
                or reply.success != (reply.status == "succeeded")):
            return False
        attempt = reply.payload.get("attempt")
        if attempt is not None:
            if (not isinstance(attempt, dict) or attempt.get("stop_attempt_id") != stop_attempt_id
                    or attempt.get("target") != participant.to_dict()
                    or any(not isinstance(attempt.get(key, []), list)
                           for key in ("blockers", "failures", "remaining_obligations"))):
                return False
        if reply.success:
            return (attempt is not None and reply.payload.get("outcome") == "completed"
                    and reply.payload.get("termination_confirmed") is True)
        return reply.payload.get("outcome") in {"blocked", "failed"}

    async def execute():
        nonlocal subscription
        await boundary.connect()
        await boundary.ensure_streams()
        subscription = await requests.subscribe_command_results(None, new_only=True,
            participant=participant, command_type=operation, result_filter=matching)
        return await requests.request_command(participant, operation, None, payload,
                                              result_window_s, command_id=command_id)

    try:
        result = await asyncio.wait_for(execute(), result_window_s)
    except asyncio.CancelledError:
        if operation == "kill":
            error = ("Terminal request interrupted; remote outcome is unconfirmed. "
                     "Explicitly authorized Kill may already have been submitted or executed. "
                     "Interruption does not revoke a submitted request; do not assume the target "
                     "remains active or has retired.")
        else:
            error = ("Terminal request interrupted; remote outcome is unconfirmed; "
                     "no automatic force escalation was requested. "
                     "Interruption does not revoke a submitted request.")
    except Exception as failure:
        error = f"{type(failure).__name__}: {failure}"
    finally:
        try:
            if subscription is not None:
                await asyncio.wait_for(subscription.unsubscribe(), result_window_s)
        except Exception as failure:
            error = f"Result subscription cleanup unconfirmed: {failure}"
        finally:
            try:
                await asyncio.wait_for(boundary.close(), result_window_s)
            except Exception as failure:
                error = f"Terminal connection cleanup unconfirmed: {failure}"

    confirmed = result is not None
    outcome = result.payload if confirmed else {}
    attempt = outcome.get("attempt") or {}
    successful = confirmed and error is None and result.success and outcome.get("outcome") == "completed"
    report(json.dumps({
        "target": participant.to_dict(), "command": operation, "command_id": command_id,
        "requester_id": requester, "administrator_id": administrator_id,
        "stop_attempt_id": stop_attempt_id, "outcome": outcome.get("outcome", "unconfirmed"),
        "reason": result.reason if confirmed else (error or "No confirmed result within the request window"),
        "blockers": attempt.get("blockers", []),
        "errors": attempt.get("failures", []) + ([error] if error is not None else []),
        "remaining_obligations": attempt.get("remaining_obligations", []),
        "termination_confirmed": outcome.get("termination_confirmed") is True,
        "operator_action": ("Owner retirement confirmed; OS process exit is not confirmed" if successful else
            "Inspect the target and unresolved obligations; Kill is never automatic. "
            "Use the blocked attempt ID for explicitly authorized Kill or Cancel."),
    }, sort_keys=True))
    return 0 if successful else 1
