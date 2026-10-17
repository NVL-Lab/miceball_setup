"""Explicit installation check through the existing node readiness command."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from lab_sync_acquisition.communication import RuntimeParticipant, build_runtime_subject
from lab_sync_acquisition.deployment_configuration import load_service_configuration
from lab_sync_acquisition.nats_communication import NatsCommunicationBoundary, NatsControllerCommunication


def _valid_node_readiness(data, node_id):
    """Validate the existing plain-data readiness report without interpreting readiness."""
    if (not isinstance(data, dict) or data.get("node_id") != node_id
            or type(data.get("ready")) is not bool
            or not isinstance(data.get("role"), str) or not data["role"]
            or "reserved_for_session_id" not in data
            or (data["reserved_for_session_id"] is not None
                and (not isinstance(data["reserved_for_session_id"], str) or not data["reserved_for_session_id"]))):
        return False
    for key, identity_fields, boolean_fields in (
        ("device_readiness", ("device_id", "reason"), ("ready",)),
        ("service_readiness", ("component_id", "component_type", "reason"), ("required", "ready")),
    ):
        records = data.get(key)
        if not isinstance(records, list):
            return False
        for record in records:
            if (not isinstance(record, dict)
                    or any(not isinstance(record.get(field), str) for field in identity_fields)
                    or any(type(record.get(field)) is not bool for field in boolean_fields)):
                return False
            if key == "device_readiness" and (not isinstance(record.get("capabilities_available"), list)
                    or any(not isinstance(item, str) for item in record["capabilities_available"])):
                return False
    return True


async def verify_node_communication(deployment_config, node_id, *, report=print):
    """Check one registered node with a fresh bounded request; never construct a Controller owner."""
    result = {"node_id": node_id, "outcome": "FAIL", "communication_confirmed": False,
              "node_readiness": None, "failure_reason": None}
    try:
        settings = load_service_configuration(deployment_config, "controller")
        build_runtime_subject(None, "command", "acquisition_node", node_id, "check_readiness")
        if node_id not in settings["known_nodes"]:
            raise ValueError("Node is not registered in the Controller deployment configuration")
    except (ValueError, TypeError) as error:
        result["failure_reason"] = str(error)
        report(json.dumps(result, sort_keys=True))
        return 1

    requester, command_id, nonce = uuid4().hex, uuid4().hex, uuid4().hex
    boundary = NatsCommunicationBoundary("terminal", requester, settings["servers"])
    requests = NatsControllerCommunication(boundary)
    participant = RuntimeParticipant("acquisition_node", node_id)
    window = settings["result_window_s"]
    subscription, reply = None, None
    invalid = []

    def matching(response):
        if (response.command_id != command_id or response.session_id is not None
                or response.source_id != node_id or response.target_id != requester
                or response.payload.get("request_nonce") != nonce
                or not isinstance(response.result_id, str) or not response.result_id
                or type(response.success) is not bool or response.status not in {"succeeded", "failed"}
                or response.success != (response.status == "succeeded")):
            invalid.append("Stale or mismatched readiness response")
            return False
        if response.success and not _valid_node_readiness(response.payload.get("acquisition_node_readiness"), node_id):
            invalid.append("Invalid AcquisitionNode readiness report")
            return False
        return True

    async def execute():
        nonlocal subscription
        await boundary.connect()
        # Streams belong to the running deployment; verification does not provision them.
        subscription = await requests.subscribe_command_results(None, new_only=True,
            participant=participant, command_type="check_readiness", result_filter=matching,
            invalid_result_callback=invalid.append)
        return await requests.request_command(participant, "check_readiness", None,
            {"request_nonce": nonce}, window, command_id=command_id)

    try:
        reply = await asyncio.wait_for(execute(), window)
        if reply is None:
            result["failure_reason"] = invalid[-1] if invalid else "No current response within the configured result window; availability is unknown"
        elif not reply.success:
            result["failure_reason"] = "Readiness request rejected by node"
        else:
            result["communication_confirmed"] = True
            result["node_readiness"] = reply.payload["acquisition_node_readiness"]
    except TimeoutError:
        result["failure_reason"] = invalid[-1] if invalid else "No current response within the configured result window; availability is unknown"
    except asyncio.CancelledError:
        result["failure_reason"] = "Installation communication verification interrupted; outcome is unconfirmed"
    except Exception as error:
        result["failure_reason"] = f"Installation communication failed ({type(error).__name__}); check NATS connectivity and service configuration"
    finally:
        try:
            if subscription is not None:
                await asyncio.wait_for(subscription.unsubscribe(), window)
        except (Exception, asyncio.CancelledError):
            result["failure_reason"] = "Verification subscription cleanup unconfirmed"
        finally:
            try:
                await asyncio.wait_for(boundary.close(), window)
            except (Exception, asyncio.CancelledError):
                result["failure_reason"] = "Verification connection cleanup unconfirmed"
    if result["communication_confirmed"] and result["failure_reason"] is None:
        result["outcome"] = "PASS"
    report(json.dumps(result, sort_keys=True))
    return 0 if result["outcome"] == "PASS" else 1
