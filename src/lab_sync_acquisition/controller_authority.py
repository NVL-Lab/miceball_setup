"""Controller claim verification and service-lifetime command admission (Decision 436)."""

from dataclasses import dataclass, replace
from contextvars import ContextVar
from math import isfinite

from nats.js.api import RetentionPolicy, StorageType


_admitted_commands = ContextVar("admitted_controller_commands", default=())


@dataclass(frozen=True)
class ControllerClaimSnapshot:
    """An inspected claim, including the exact installation scope and KV revision."""

    account: str
    bucket: str
    key: str
    operational_instance_id: str
    revision: int

    def __post_init__(self):
        if (any(not isinstance(v, str) or not v.strip() for v in
                (self.account, self.bucket, self.key, self.operational_instance_id))
                or type(self.revision) is not int or self.revision <= 0):
            raise ValueError("Complete claim scope, owner and positive revision are required")


async def open_controller_claim_store(boundary, *, account, bucket, key, timeout_s):
    """Open existing authoritative storage after account and durability verification."""
    import json
    if (any(not isinstance(v, str) or not v.strip() for v in (account, bucket, key))
            or type(timeout_s) not in (int, float) or not isfinite(timeout_s) or timeout_s <= 0):
        raise ValueError("Explicit authority scope and positive finite timeout are required")
    if not boundary.connected or boundary._jetstream is None:
        raise RuntimeError("Controller authority storage is unavailable")
    response = await boundary._client.request("$SYS.REQ.USER.INFO", b"", timeout=timeout_s)
    identity = json.loads(response.data)
    if identity.get("error") or identity.get("data", {}).get("account") != account:
        raise RuntimeError("Controller authority JetStream account is unverified")
    kv = await boundary._jetstream.key_value(bucket)
    config = (await kv.status()).stream_info.config
    if (config.name != "KV_" + bucket or config.storage != StorageType.FILE
            or config.retention != RetentionPolicy.LIMITS or config.max_age not in (None, 0)
            or config.max_msgs not in (None, -1) or config.max_bytes not in (None, -1)
            or config.mirror is not None or config.sources or config.no_ack
            or config.subject_transform is not None or config.sealed):
        raise RuntimeError("Controller claim bucket must be persistent, non-expiring authoritative storage without eviction limits")
    return kv


# These commands do not exercise Controller operational authority. Their existing
# receiving handlers still validate their own scope, authorization and identity.
AUTHORITY_READ_COMMANDS = frozenset({
    "check_readiness", "get_inventory", "read_controller_admission", "read_operational_instance",
    "check_stop_readiness", "list_storage_sessions", "read_storage_session", "read_storage_history",
    "read_session_preservation", "get_saved_session_collection_status", "confirm_collected_originals",
    "compile_session_evidence", "verify_acquisition_receipt", "read_runtime_evidence_acceptance",
    "read_session_closeout", "read_experiment_expiry", "read_session_time",
})


def controller_independent_command(command):
    """Recognize existing readback, administrator and service-owned command paths."""
    from lab_sync_acquisition.communication import DEPENDENT_MAINTENANCE_COMMANDS, SERVICE_RECOVERY_COMMAND_TYPES
    if command.command_type in AUTHORITY_READ_COMMANDS:
        return True
    if command.issuer_type == "controller":
        return False
    if any(v is not None for v in (command.controller_instance_id,
                                   command.controller_claim_revision, command.receiver_instance_id)):
        raise RuntimeError("Controller authority metadata requires a Controller issuer")
    if (command.issuer_type == "controller_service" and command.command_type in
            (DEPENDENT_MAINTENANCE_COMMANDS | {"preserve_service_evidence"})):
        return True
    if (command.command_type in ({"stop", "kill", "cancel", "prepare_stop"} | SERVICE_RECOVERY_COMMAND_TYPES)
            and command.issuer_type in (None, "terminal")
            and isinstance(command.payload.get("administrator_id"), str)
            and command.payload["administrator_id"].strip()):
        return True
    allowed = {
        "acquisition_node": {"preserve_service_evidence", "preserve_session_acquisition"},
        "synchronization_manager": {"preserve_service_evidence", "release_session", "read_local_time", "accept_synchronization_quality"},
        "ingestor": {"preserve_service_evidence"},
        "storage_manager": {"preserve_service_evidence"},
    }
    return (command.issuer_type in allowed
            and command.command_type in (allowed[command.issuer_type] | DEPENDENT_MAINTENANCE_COMMANDS))


class ControllerCommandAdmission:
    """Volatile recognized Controller authority, owned by one receiving service lifetime."""

    def __init__(self, maintenance):
        self.maintenance = maintenance
        self.recognized = None

    def register(self, command, snapshot):
        """Acknowledge current verified ownership without restoring historical registrations."""
        owner = self.maintenance
        with owner._admission_lock:
            if (owner.terminated or command.issuer_type != "controller"
                    or command.receiver_instance_id != owner.operational_instance_id
                    or command.controller_instance_id != snapshot.operational_instance_id
                    or type(command.controller_claim_revision) is not int
                    or command.controller_claim_revision != snapshot.revision
                    or (self.recognized is not None and snapshot.revision < self.recognized[1])):
                raise RuntimeError("Controller registration is stale, mismatched or unconfirmed")
            if (self.recognized is not None and snapshot.revision == self.recognized[1]
                    and (snapshot.operational_instance_id, command.source_id) != (self.recognized[0], self.recognized[2])):
                raise RuntimeError("Controller registration conflicts with the recognized participant")
            previous = owner._commands.get(command.command_id)
            if previous is not None and previous != command.to_dict():
                raise RuntimeError("Conflicting Controller registration command identity")
            self.recognized = (snapshot.operational_instance_id, snapshot.revision, command.source_id)
            return {"controller_instance_id": snapshot.operational_instance_id,
                    "controller_claim_revision": snapshot.revision,
                    "receiver_instance_id": owner.operational_instance_id}

    def admit(self, command):
        """Serialize new command admission with replacement; do not cancel admitted work."""
        owner = self.maintenance
        with owner._admission_lock:
            if (id(owner), command.command_id, command.controller_instance_id,
                    command.controller_claim_revision) in _admitted_commands.get():
                return
            if controller_independent_command(command):
                return
            if command.issuer_type == "controller":
                if (self.recognized is None
                        or command.receiver_instance_id != owner.operational_instance_id
                        or type(command.controller_claim_revision) is not int
                        or (command.controller_instance_id, command.controller_claim_revision, command.source_id) != self.recognized):
                    raise RuntimeError("Controller command requires current service-instance registration")
                if owner.terminated:
                    # Delivery retry is not new operational work. Only the exact
                    # completed retirement command from the still-recognized
                    # Controller may reach the existing result replay path.
                    logical = replace(command, receiver_instance_id=None).to_dict()
                    retained = owner._results.get(command.command_id)
                    if (command.command_type not in {"stop", "kill"}
                            or owner._commands.get(command.command_id) != logical
                            or retained is None or not retained.success
                            or retained.payload.get("outcome") != "completed"
                            or retained.payload.get("termination_confirmed") is not True):
                        raise RuntimeError("Retired service admits only exact retirement-result replay")
                return
            raise RuntimeError("Controller-dependent command has no recognized Controller authority")
