"""Explicit independent-role composition using existing service owners."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.communication import RuntimeParticipant, build_runtime_subject
from lab_sync_acquisition.controller import Controller
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.device_manager import DeviceManager
from lab_sync_acquisition.nats_communication import (
    NatsAcquisitionNodeCommunication, NatsCommunicationBoundary, NatsControllerCommunication,
    NatsServiceMaintenanceCommunication, NatsSynchronizationManagerCommunication,
)
from lab_sync_acquisition.opencv_camera import OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter
from lab_sync_acquisition.service_launcher import ServiceLauncher
from lab_sync_acquisition.service_maintenance import ServiceMaintenanceInterface
from lab_sync_acquisition.synchronization import SynchronizationManager


def read_acquisition_node_configuration(path):
    """Validate installation settings without constructing an owner or opening hardware."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"node_id", "role", "local_storage_root", "error_evidence_location", "devices"}:
        raise ValueError("Node installation requires node_id, role, local_storage_root, error_evidence_location and devices")
    if not isinstance(data["devices"], list) or not data["devices"]:
        raise ValueError("Node installation requires a nonempty installed-device list")
    for key in ("node_id", "role", "local_storage_root", "error_evidence_location"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"Node installation requires nonempty {key}")
    build_runtime_subject(None, "command", "acquisition_node", data["node_id"], "stop")
    configurations = {}
    for item in data["devices"]:
        if not isinstance(item, dict) or set(item) != {"adapter", "declaration", "configuration"}:
            raise ValueError("Each installed device requires adapter, declaration and configuration")
        declaration = DeviceDeclaration.from_dict(item["declaration"])
        if item["adapter"] != "seeed_imx219_opencv":
            raise ValueError(f"Unsupported installed adapter: {item['adapter']}")
        if (not isinstance(declaration.device_id, str) or not declaration.device_id.strip()
                or not isinstance(declaration.device_type, str) or not declaration.device_type.strip()
                or declaration.declared_capabilities is None
                or any(not isinstance(value, str) or not value for value in declaration.declared_capabilities)
                or type(declaration.enabled) is not bool or type(declaration.required) is not bool
                or declaration.device_id in configurations):
            raise ValueError("Installed devices require unique identities and explicit capabilities/enabled/required settings")
        config = OpenCVCameraConfig(**item["configuration"])
        if type(config.frames_per_collect) is not int or config.frames_per_collect < 1:
            raise ValueError("frames_per_collect must be a positive integer")
        from math import isfinite
        if (type(config.api_preference) is not int
                or not (type(config.camera_source) is int and config.camera_source >= 0
                        or isinstance(config.camera_source, str) and config.camera_source.strip())
                or any(value is not None and (type(value) is not int or value <= 0)
                       for value in (config.frame_width, config.frame_height))
                or config.fps is not None and (type(config.fps) not in {int, float}
                                              or not isfinite(config.fps) or config.fps <= 0)):
            raise ValueError("Invalid explicit OpenCV installation connection or capture settings")
        configurations[declaration.device_id] = item["configuration"]
    return data


def load_acquisition_node(path, synchronization_source_id):
    """Load installation declarations and explicit supported adapters without opening hardware."""
    path = Path(path)
    data = read_acquisition_node_configuration(path)
    declarations = [DeviceDeclaration.from_dict(item["declaration"]) for item in data["devices"]]
    adapters = [SeeedIMX219OpenCVCameraAdapter(d.device_id, d.device_type,
        d.declared_capabilities, d.required) for d in declarations]
    configurations = {item["declaration"]["device_id"]: item["configuration"] for item in data["devices"]}
    return AcquisitionNode(device_manager=DeviceManager(adapters), node_id=data["node_id"], role=data["role"],
        synchronization_source_id=synchronization_source_id, device_declarations=declarations,
        default_local_storage_root=path.parent / data["local_storage_root"],
        error_evidence_location=str(path.parent / data["error_evidence_location"]),
        deployment_device_configurations=configurations)


async def launch_independent_service(*, role, servers, service_id, ingestor_id, storage_id,
                                     preservation_window_s, result_window_s,
                                     synchronization_id=None, known_nodes=None, node_config=None, report=print):
    """Run one explicit owner with remote preservation, readiness and existing maintenance."""
    from math import isfinite
    servers = tuple(servers)
    if (not servers or any(not isinstance(s, str) or not s.strip() for s in servers)
            or type(result_window_s) not in {int, float} or not isfinite(result_window_s) or result_window_s <= 0
            or type(preservation_window_s) not in {int, float} or not isfinite(preservation_window_s) or preservation_window_s <= 0):
        raise ValueError("Explicit servers and positive finite preservation/result windows are required")
    ingestor = RuntimeParticipant("ingestor", ingestor_id)
    storage = RuntimeParticipant("storage_manager", storage_id)
    dependencies = [ingestor, storage]
    if role == "controller":
        if synchronization_id is None or known_nodes is None:
            raise ValueError("Controller requires its configured synchronization identity and explicit known-node collection")
        owner = Controller(component_id=service_id)
        dependencies += [RuntimeParticipant("synchronization_manager", synchronization_id)]
        dependencies += [RuntimeParticipant("acquisition_node", identity) for identity in known_nodes]
        handler_type = None
    elif role == "synchronization-manager":
        owner = SynchronizationManager()
        handler_type = NatsSynchronizationManagerCommunication
    elif role == "acquisition-node":
        owner = load_acquisition_node(node_config, synchronization_id)
        if service_id is not None and service_id != owner.node_id:
            raise ValueError("CLI identity conflicts with persistent AcquisitionNode identity")
        service_id = owner.node_id
        dependencies.append(RuntimeParticipant("synchronization_manager", synchronization_id))
        handler_type = NatsAcquisitionNodeCommunication
    else:
        raise ValueError("Independent launcher supports Controller, AcquisitionNode and SynchronizationManager")
    kind = role.replace("-", "_")
    for participant in [RuntimeParticipant(kind, service_id), *dependencies]:
        build_runtime_subject(None, "command", participant.component_type, participant.component_id, "stop")
    boundary = NatsCommunicationBoundary(kind, service_id, servers)
    communication = NatsControllerCommunication(boundary)
    runtime = handler_type(boundary, owner) if handler_type is not None else None

    async def cleaned(force):
        if isinstance(runtime, NatsAcquisitionNodeCommunication):
            await runtime.stop_acquisition_execution()
        if isinstance(runtime, NatsSynchronizationManagerCommunication) and runtime._assessment_task is not None:
            runtime._assessment_task.cancel()
            try:
                await runtime._assessment_task
            except asyncio.CancelledError:
                pass
            runtime._assessment_task = None
        return True

    maintenance = ServiceMaintenanceInterface(owner, RuntimeParticipant(kind, service_id),
        ingestor=None, storage_manager=None, preservation_window_s=preservation_window_s,
        close_resources=cleaned, dependency_participants=dependencies,
        evidence_publisher=boundary.publish_evidence, framework_communication=communication,
        framework_ingestor=ingestor, framework_storage=storage)
    launcher = ServiceLauncher((maintenance,), (boundary,), report=report)

    async def startup():
        admitted = False
        try:
            await boundary.connect()
            await boundary.ensure_streams()
            admitted = True
            startup_interface = NatsServiceMaintenanceCommunication(boundary, maintenance,
                startup_participants=dependencies if role == "controller" else None,
                startup_result_window_s=result_window_s if role == "controller" else None)
            # Existing handlers remain available for maintenance/instance readback;
            # service-owned new-work admission stays closed until registration.
            if isinstance(runtime, NatsAcquisitionNodeCommunication):
                await runtime.start_acquisition_execution()
            if runtime is None:
                await startup_interface.subscribe_commands()
            else:
                await runtime.subscribe_commands()
            await maintenance.register_ingestor_dependency()
            status = await startup_interface.start()
            if role != "controller":
                for dependency in dependencies:
                    await startup_interface.check_dependency_readiness(dependency, result_window_s)
            report(json.dumps({"target": maintenance.participant.to_dict(), "startup": status}, sort_keys=True))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if admitted:
                report(f"Startup unconfirmed: {error}; process retained; Ctrl+C requests local maintenance.")
            else:
                await boundary.close()
                raise

    return await launcher.run(startup=startup)
