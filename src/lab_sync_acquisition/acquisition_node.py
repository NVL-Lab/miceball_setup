"""Bounded acquisition-side execution for Phase 1 workflows."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, asdict, is_dataclass
import json
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from threading import RLock
from typing import Any, Iterable

from lab_sync_acquisition.acquisition_health import (
    AcquisitionHealthPolicy,
    HealthInterpretationEvidence,
)
from lab_sync_acquisition.communication import (
    ARTIFACT_MANIFEST_EVIDENCE_TYPE, RuntimeEvidenceMessage,
)
from lab_sync_acquisition.acquisition_node_readiness import AcquisitionNodeReadiness
from lab_sync_acquisition.device_manager import (
    DeviceManager, DeviceReadinessSummary, DeviceCollectionResult,
    _PartialDeviceCollectionError,
)
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.device_adapter import DeviceAdapterState, DeviceReadiness
from lab_sync_acquisition.local_storage import LocalStorageManager, ArtifactManifest
from lab_sync_acquisition.session import ScientificOutputSelection, ExperimentConfiguration
from lab_sync_acquisition.experiment_runtime import (
    ActiveExperimentRuntimeContext,
    ExperimentRuntimeHealthMapping,
    ExperimentScopedHealthObservation,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness, dependency_readiness_reports
from lab_sync_acquisition.service_maintenance import service_operation
from lab_sync_acquisition.synchronization import (
    SynchronizationManager,
    SynchronizationMapping,
)


@dataclass(frozen=True)
class AcquisitionIterationSummary:
    """Inspectable result for one bounded acquisition iteration."""

    iteration_index: int
    collections_seen: int
    scientific_observations: int


class AcquisitionNode:
    """Owns bounded acquisition execution without owning Session lifecycle."""

    def __init__(
        self,
        session_id: str | None = None,
        device_manager: DeviceManager | None = None,
        synchronization_manager: SynchronizationManager | None = None,
        ingestor: InMemoryIngestor | None = None,
        node_id: str | None = None,
        role: str | None = None,
        acquisition_health_policies: Iterable[AcquisitionHealthPolicy] = (),
        error_evidence_location: str | None = None,
        *,
        default_local_storage_root: str | Path | None = None,
        device_declarations: Iterable[DeviceDeclaration] | None = None,
        synchronization_source_id: str | None = None,
        deployment_device_configurations: dict[str, Any] | None = None,
    ) -> None:
        self._session_id = session_id
        self._service_operation_lock = RLock()
        self._active_service_operations = 0
        # Explicitly pre-bound nodes retain the historical caller-prepared workflow.
        self._session_prepared = session_id is not None
        if device_manager is None or (synchronization_manager is None and not synchronization_source_id):
            raise ValueError("AcquisitionNode requires deployment runtime collaborators")
        if synchronization_manager is not None and synchronization_source_id is not None:
            raise ValueError("Choose local synchronization or an explicit remote authority, not both")
        if synchronization_source_id is not None and (not isinstance(synchronization_source_id, str)
                or not synchronization_source_id or not isinstance(node_id, str) or not node_id):
            raise ValueError("Distributed synchronization requires explicit authority and node identities")
        self._synchronization_source_id = synchronization_source_id
        self._synchronization_quality: dict[str, Any] | None = None
        self._synchronization_quality_history: list[dict[str, Any]] = []
        self._mapping_activation_history: list[dict[str, Any]] = []
        self._timing_quality_reported = False
        self._device_manager = device_manager
        self._deployment_device_configurations = {
            adapter.device_id: deepcopy(adapter.initialization_config)
            for adapter in device_manager.adapters
        }
        if deployment_device_configurations is not None:
            if set(deployment_device_configurations) != set(self._deployment_device_configurations):
                raise ValueError("Installation configuration must identify every installed adapter exactly")
            self._deployment_device_configurations = deepcopy(deployment_device_configurations)
        self._runtime_device_manager = device_manager
        self._reservation_lock = RLock()
        self._reserved_for_session_id: str | None = None
        self._initialization_cleanup_confirmed = True
        self._initialization_touched_adapters = []
        self._declared_devices = tuple(device_declarations) if device_declarations is not None else tuple(
            DeviceDeclaration(a.device_id, a.device_type, True, a.required, a.declared_capabilities)
            for a in device_manager.adapters)
        if len({d.device_id for d in self._declared_devices}) != len(self._declared_devices):
            raise ValueError("Duplicate device identity in node inventory")
        self._synchronization_manager = synchronization_manager
        self._ingestor = ingestor
        self._node_id = node_id
        self._default_local_storage_root = (
            Path(default_local_storage_root) if default_local_storage_root is not None else None
        )
        self._local_storage_manager: LocalStorageManager | None = None
        self._device_declarations: tuple[DeviceDeclaration, ...] = ()
        self._scientific_output_storage_ids: dict[tuple[str, str, str], str] = {}
        self._prepared_scientific_outputs: dict[str, tuple[ScientificOutputSelection, ...]] = {}
        self._experiment_configurations: dict[str, ExperimentConfiguration] = {}
        self._experiment_deadline: dict[str, Any] | None = None
        self._session_device_configurations: dict[str, Any] | None = None
        self._ended_experiment_ids: set[str] = set()
        self._artifact_manifest_evidence: list[RuntimeEvidenceMessage] = []
        self._role = role
        self._error_evidence_location = error_evidence_location
        self._acquisition_health_policies = {
            policy.policy_id: policy
            for policy in acquisition_health_policies
        }
        self._acquisition_health_observed_counts: dict[str, int] = {}
        self._acquisition_health_observations_recorded: set[str] = set()
        self._acquisition_start_session_time_s: float | None = None
        self._failed = False
        self._runtime_evidence: list[RuntimeEvidenceMessage] = []
        self._running = False
        self._iteration_index = 0
        self._last_error: str | None = None
        self._active_experiment_runtime_health_mapping: tuple[
            ExperimentRuntimeHealthMapping, ...
        ] = ()
        self._active_experiment_runtime_context: (
            ActiveExperimentRuntimeContext | None
        ) = None
        self._active_synchronization_mapping: SynchronizationMapping | None = None
        self._active_experiment_id: str | None = None
        self._experiment_scoped_health_observations: list[
            ExperimentScopedHealthObservation
        ] = []
        self._health_interpretation_evidence: list[
            HealthInterpretationEvidence
        ] = []
        self._health_runtime_evidence: list[RuntimeEvidenceMessage] = []
        self._next_health_observation_id = 1

    @property
    def node_id(self) -> str | None:
        return self._node_id

    @property
    def declared_devices(self) -> tuple[DeviceDeclaration, ...]:
        """Deployment inventory, independent of Session selections and availability."""
        return self._declared_devices

    def get_inventory(self) -> dict[str, Any]:
        """Return installed declarations and adapter-owned Session parameter definitions."""
        declared_ids = {d.device_id for d in self.declared_devices}
        return {"devices": [d.to_dict() for d in self.declared_devices],
                "synchronization_source_id": self.synchronization_source_id,
                "session_parameter_definitions": {
                    adapter.device_id: deepcopy(adapter.get_session_parameter_definitions())
                    for adapter in self._device_manager.adapters if adapter.device_id in declared_ids}}

    @property
    def reserved_for_session_id(self) -> str | None:
        with self._reservation_lock:
            return self._reserved_for_session_id

    @service_operation(new_work=True)
    def reserve(self, session_id: str) -> bool:
        """Atomically reserve this node, idempotently for the same Session."""
        self._validate_session_id(session_id)
        with self._reservation_lock:
            if self._reserved_for_session_id not in {None, session_id}:
                return False
            if self._session_id not in {None, session_id}:
                return False
            self._reserved_for_session_id = session_id
            return True

    @service_operation()
    def release_reservation(self, session_id: str) -> bool:
        """Release only the owner's reservation after confirmed local cleanup."""
        self._validate_session_id(session_id)
        with self._reservation_lock:
            if self._reserved_for_session_id != session_id:
                return False
            if self._running or not self._initialization_cleanup_confirmed:
                return False
            if self._local_storage_manager is not None and any(m.lifecycle_state != "finalized" for m in self._local_storage_manager.manifests):
                return False
            self._reserved_for_session_id = None
            self._session_id = None
            self._session_prepared = False
            self._local_storage_manager = None
            self._device_declarations = ()
            self._session_device_configurations = None
            self._active_synchronization_mapping = None
            self._synchronization_quality = None
            self.clear_experiment_runtime_context()
            self.clear_experiment_runtime_health_mapping()
            return True

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("A real nonempty session_id is required")

    @service_operation(new_work=True)
    def prepare_local_storage(
        self,
        session_id: str,
        declarations: Iterable[DeviceDeclaration],
        root_path: str | Path | None = None,
    ) -> LocalStorageManager:
        """Physically create Session-authorized storage in this node's process."""
        root = root_path if root_path is not None else self._default_local_storage_root
        if root is None or not self._node_id:
            raise ValueError("Node local storage root and identity must be configured")
        manager = LocalStorageManager(root, session_id, self._node_id)
        self.attach_local_storage_manager(manager, declarations)
        return manager

    @service_operation(new_work=True)
    def initialize_session(
        self,
        session_id: str,
        selected_devices: Iterable[DeviceDeclaration],
        device_configurations: dict[str, Any] | None = None,
        scientific_outputs: Iterable[ScientificOutputSelection] = (),
    ) -> ServiceReadiness:
        """Prepare reserved Session runtime locally without creating a Session replica."""
        self._validate_session_id(session_id)
        with self._reservation_lock:
            if self._reserved_for_session_id != session_id:
                raise RuntimeError("Session initialization requires matching reservation")
            if self._session_id is not None:
                raise RuntimeError("Session binding is already established; abort before reinitializing")
            self._session_id = session_id
            self._session_prepared = False
            self._initialization_cleanup_confirmed = False
            self._initialization_touched_adapters = []
            declarations = tuple(selected_devices)
            inventory = {d.device_id: d for d in self._declared_devices if d.enabled}
            adapters = {a.device_id: a for a in self._device_manager.adapters}
            selected_adapters = []
            for declaration in declarations:
                if declaration.device_id not in inventory or declaration.device_id not in adapters:
                    raise ValueError(f"Selected device is unavailable: {declaration.device_id}")
                declared = inventory[declaration.device_id]
                if declaration.scientific_products != declared.scientific_products:
                    raise ValueError("Session cannot redefine declared scientific products")
                selected_adapters.append(adapters[declaration.device_id])
            self._runtime_device_manager = DeviceManager(selected_adapters)
            configurations = {
                adapter.device_id: adapter.resolve_session_configuration(
                    self._deployment_device_configurations[adapter.device_id],
                    (device_configurations or {}).get(adapter.device_id))
                for adapter in selected_adapters}
            self._session_device_configurations = deepcopy(configurations)
            self._experiment_configurations.clear()
            self._experiment_deadline = None
            for adapter in selected_adapters:
                self._initialization_touched_adapters.append(adapter)
                configuration = configurations[adapter.device_id]
                if (adapter.state in {DeviceAdapterState.INITIALIZED, DeviceAdapterState.READY}
                        and configuration != adapter.initialization_config):
                    adapter.shutdown()
                if adapter.state == DeviceAdapterState.DECLARED:
                    adapter.initialize(configuration)
                elif configuration is not None and configuration != adapter.initialization_config:
                    raise ValueError(f"Device already prepared with different configuration: {adapter.device_id}")
                readiness = adapter.check_ready()
                if not isinstance(readiness, DeviceReadiness) or readiness.ready is not True:
                    raise RuntimeError(f"Selected device preparation failed: {adapter.device_id}")
            self._scientific_output_storage_ids.clear()
            self._prepared_scientific_outputs.clear()
            self._ended_experiment_ids.clear()
            self._acquisition_health_observed_counts.clear()
            self._acquisition_health_observations_recorded.clear()
            self._acquisition_start_session_time_s = None
            self._iteration_index = 0
            self._failed = False
            self._last_error = None
            self.prepare_local_storage(session_id, declarations)
            readiness = self._local_storage_manager.check_ready()
            if not readiness.ready:
                raise RuntimeError(readiness.reason)
            for selection in scientific_outputs:
                if selection.source_node_id != self._node_id or selection.source_device_id not in {d.device_id for d in declarations}:
                    raise ValueError("Scientific selection is not assigned to this Session/node")
                declaration = inventory[selection.source_device_id]
                if not any(product.data_product_id == selection.data_product_id
                           for product in declaration.scientific_products):
                    raise ValueError(f"Unknown scientific product: {selection.data_product_id}")
            self._session_prepared = True
            return ServiceReadiness(self._node_id, "acquisition_node", True, True, "session_prepared")

    @service_operation()
    def abort_session_initialization(self, session_id: str) -> bool:
        """Idempotently clean partial initialization while protecting reservation."""
        self._validate_session_id(session_id)
        with self._reservation_lock:
            if self._reserved_for_session_id != session_id or self._session_id not in {None, session_id}:
                raise RuntimeError("Initialization abort requires matching reservation/binding")
            self._session_prepared = False
            if self._initialization_cleanup_confirmed:
                return True
            cleanup_confirmed = False
            try:
                if self._running:
                    outcome = self.stop_runtime()
                    if any(not r.succeeded for r in (*outcome["device_stop_results"], *outcome["device_shutdown_results"])):
                        raise RuntimeError("Device runtime cleanup failed")
                    if self._local_storage_manager is not None:
                        self._local_storage_manager.cleanup()
                else:
                    failures = []
                    for adapter in self._initialization_touched_adapters:
                        try:
                            if adapter.state == DeviceAdapterState.RUNNING:
                                adapter.stop()
                            if adapter.state in {DeviceAdapterState.INITIALIZED, DeviceAdapterState.READY,
                                                 DeviceAdapterState.FAILED, DeviceAdapterState.STOPPED}:
                                adapter.shutdown()
                        except Exception as error:
                            failures.append(error)
                    try:
                        self._finalize_prepared_scientific_outputs()
                    except Exception as error:
                        failures.append(error)
                    if self._local_storage_manager is not None:
                        try:
                            self._local_storage_manager.cleanup()
                        except Exception as error:
                            failures.append(error)
                    if failures:
                        raise ExceptionGroup("Local initialization cleanup failed", failures)
                cleanup_confirmed = True
                return True
            finally:
                # stop_runtime confirms its own stages, not the entire abort.
                self._initialization_cleanup_confirmed = cleanup_confirmed

    @property
    def default_local_storage_root(self) -> Path | None:
        return self._default_local_storage_root

    @property
    def local_storage_manager(self) -> LocalStorageManager | None:
        return self._local_storage_manager

    @property
    def scientific_output_storage_ids(self) -> dict[tuple[str, str, str], str]:
        """Readback copy keyed by Experiment, source device, and product identity."""
        return dict(self._scientific_output_storage_ids)

    @property
    def artifact_manifest_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Produced artifact lifecycle evidence for independent transport publication."""
        return tuple(self._artifact_manifest_evidence)

    def _record_artifact_manifest(self, manifest: ArtifactManifest, *, resubmit_unconfirmed: bool = False) -> None:
        evidence_id = f"artifact-manifest-{manifest.artifact_manifest_id}-{manifest.lifecycle_state}"
        message = next((retained for retained in self._artifact_manifest_evidence
                        if retained.evidence_id == evidence_id), None)
        if message is not None and (not resubmit_unconfirmed or (
                self._ingestor is not None and self._ingestor.has_durable_runtime_evidence(message))):
            return
        if message is None:
            message = RuntimeEvidenceMessage(
                evidence_id=evidence_id, session_id=manifest.session_id,
                evidence_type=ARTIFACT_MANIFEST_EVIDENCE_TYPE,
                source_id=manifest.acquisition_node_id, payload=manifest.to_dict(),
                is_persistent=True,
            )
            self._artifact_manifest_evidence.append(message)
        if self._ingestor is not None:
            self._ingestor.receive_runtime_evidence(message)

    @service_operation(new_work=True)
    def attach_local_storage_manager(
        self,
        manager: LocalStorageManager,
        device_declarations: Iterable[DeviceDeclaration],
    ) -> None:
        """Attach Session-authorized storage without taking persistence ownership."""
        if manager.session_id != self._session_id or manager.acquisition_node_id != self._node_id:
            raise ValueError("Local storage Session/node identity does not match AcquisitionNode")
        if self._local_storage_manager is not None and self._local_storage_manager is not manager:
            raise ValueError("LocalStorageManager is already attached for this Session/node")
        declarations = tuple(device_declarations)
        for declaration in declarations:
            installed = next((device for device in self._declared_devices
                              if device.device_id == declaration.device_id), None)
            if installed is None or installed.scientific_products != declaration.scientific_products:
                raise ValueError("Scientific products differ from installed device declarations")
        self._local_storage_manager = manager
        self._device_declarations = declarations

    @service_operation(new_work=True)
    def prepare_experiment_scientific_outputs(
        self,
        experiment_id: str,
        scientific_outputs: Iterable[ScientificOutputSelection],
        *, configuration: ExperimentConfiguration | None = None,
    ) -> ServiceReadiness:
        """Resolve explicit declarations and request empty streams before acquisition."""
        with self._reservation_lock:
            if not self._session_prepared and not self._running:
                return ServiceReadiness(self._node_id or "acquisition_node", "scientific_output_preparation",
                                        True, False, "Session runtime is not prepared or has closed")
            self._initialization_cleanup_confirmed = False
            return self._prepare_experiment_scientific_outputs(experiment_id, scientific_outputs, configuration)

    def _prepare_experiment_scientific_outputs(self, experiment_id, scientific_outputs, configuration):
        created: list[str] = []
        try:
            outputs = tuple(scientific_outputs)
            if experiment_id in self._ended_experiment_ids:
                raise ValueError("Experiment runtime identity has ended and cannot be reused")
            if len(set(outputs)) != len(outputs):
                raise ValueError("Duplicate scientific output selection")
            if not isinstance(configuration, ExperimentConfiguration):
                raise ValueError("An explicit ExperimentConfiguration is required")
            previous = self._experiment_configurations.get(experiment_id)
            if previous is not None and previous != configuration:
                raise ValueError("Conflicting Experiment configuration")
            if self._active_experiment_runtime_context is not None:
                raise RuntimeError("Cannot prepare while an Experiment is active")
            capacity = self.check_experiment_capacity(outputs, configuration)
            if capacity["ready"] is not True:
                raise RuntimeError(str(capacity))
            for adapter, parameters in self._experiment_device_parameters(configuration):
                if (parameters != adapter.initialization_config or adapter.state not in {
                        DeviceAdapterState.INITIALIZED, DeviceAdapterState.READY, DeviceAdapterState.RUNNING}):
                    if adapter.state == DeviceAdapterState.RUNNING:
                        adapter.stop()
                    if adapter.state != DeviceAdapterState.DECLARED:
                        adapter.shutdown()
                    adapter.initialize(parameters)
                readiness = adapter.check_ready()
                if (not isinstance(readiness, DeviceReadiness) or readiness.device_id != adapter.device_id
                        or readiness.ready is not True):
                    raise RuntimeError(f"Experiment device configuration is unready: {adapter.device_id}")
                if self._running and adapter.state == DeviceAdapterState.READY:
                    adapter.start()
                if self._running and adapter.state != DeviceAdapterState.RUNNING:
                    raise RuntimeError(f"Experiment device is not running: {adapter.device_id}")
            self._experiment_configurations[experiment_id] = deepcopy(configuration)
            if outputs and not experiment_id:
                raise ValueError("experiment_id is required")
            if outputs and self._local_storage_manager is None:
                raise ValueError("LocalStorageManager is not attached")
            manager = self._local_storage_manager
            if outputs:
                readiness = manager.check_ready()
                if not readiness.ready:
                    raise RuntimeError(readiness.reason)
            for output in outputs:
                if output.source_node_id != self._node_id:
                    raise ValueError(f"Unknown AcquisitionNode: {output.source_node_id}")
                devices = [device for device in self._device_declarations
                           if device.device_id == output.source_device_id]
                if len(devices) != 1 or not devices[0].enabled:
                    raise ValueError(f"Unknown, ambiguous, or disabled device: {output.source_device_id}")
                products = [product for product in devices[0].scientific_products
                            if product.data_product_id == output.data_product_id]
                if len(products) != 1:
                    raise ValueError(f"Unknown scientific product: {output.data_product_id}")
                key = (experiment_id, output.source_device_id, output.data_product_id)
                if key in self._scientific_output_storage_ids:
                    manifest = next(m for m in manager.manifests
                                    if m.storage_id == self._scientific_output_storage_ids[key])
                    if manifest.lifecycle_state != "open":
                        raise ValueError("Prepared scientific stream is finalized and cannot reopen")
                    continue
                product = products[0]
                manifest = manager.create_stream(
                    session_id=self._session_id, experiment_id=experiment_id,
                    acquisition_node_id=self._node_id,
                    source_component_id=output.source_device_id,
                    data_product_id=product.data_product_id, artifact_type=product.product_type,
                    schema=product.schema, storage_format=product.storage_format,
                    details={"storage_requirements": product.storage_requirements,
                             "expected_data_size_bytes": product.expected_data_size_bytes,
                             "expected_acquisition_rate_hz": product.expected_acquisition_rate_hz},
                )
                self._scientific_output_storage_ids[key] = manifest.storage_id
                created.append(manifest.storage_id)
                self._record_artifact_manifest(manifest)
        except Exception as error:
            cleanup_errors = []
            for storage_id in created:
                try:
                    manifest = self._local_storage_manager.finalize_stream(storage_id)
                    self._record_artifact_manifest(manifest)
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            reason = f"{type(error).__name__}: {error}"
            if cleanup_errors:
                reason += f"; preparation cleanup failed: {cleanup_errors}"
            return ServiceReadiness(self._node_id or "acquisition_node", "scientific_output_preparation",
                                    True, False, reason)
        self._prepared_scientific_outputs[experiment_id] = outputs
        return ServiceReadiness(self._node_id or "acquisition_node", "scientific_output_preparation",
                                True, True, "ready")

    def _experiment_device_parameters(self, configuration):
        if self._session_device_configurations is None:
            # Capture initialized local settings once, before any Experiment can
            # partially reconfigure a device; failed preparation cannot replace them.
            self._session_device_configurations = {
                a.device_id: deepcopy(a.initialization_config)
                for a in self._runtime_device_manager.adapters}
        overrides = (configuration.device_configurations or {}).get(self._node_id, {})
        adapters = self._runtime_device_manager.adapters
        if set(overrides) - {a.device_id for a in adapters}:
            raise ValueError("Experiment configuration references an unavailable device")
        return tuple((a, a.resolve_session_configuration(self._session_device_configurations[a.device_id],
                                                        overrides.get(a.device_id))) for a in adapters)

    @service_operation()
    def check_experiment_capacity(self, scientific_outputs: Iterable[ScientificOutputSelection],
                                  configuration: ExperimentConfiguration) -> dict[str, Any]:
        """Check this node's selected representation or explicit all-inclusive recording budget."""
        try:
            if not isinstance(configuration, ExperimentConfiguration) or self._local_storage_manager is None:
                raise ValueError("Prepared local storage and Experiment configuration are required")
            outputs = tuple(scientific_outputs)
            parameters = {a.device_id: asdict(value) if is_dataclass(value) else value
                          for a, value in self._experiment_device_parameters(configuration)}
            required = (configuration.recording_budgets or {}).get(self._node_id)
            total = 0
            for output in outputs:
                if output.source_node_id != self._node_id:
                    raise ValueError("Capacity output references another node")
                product = next(p for d in self._device_declarations if d.device_id == output.source_device_id
                               for p in d.scientific_products if p.data_product_id == output.data_product_id)
                if product.storage_format == "hdf5" and product.product_type == "camera_frames":
                    shape = product.schema.get("frame_shape")
                    selected = parameters[output.source_device_id]
                    if (not isinstance(shape, list) or len(shape) not in (2, 3)
                            or selected.get("frame_width") not in (None, shape[1])
                            or selected.get("frame_height") not in (None, shape[0])):
                        raise ValueError("Selected camera resolution differs from the declared stored representation")
                if required is None:
                    total += product.estimate_storage_bytes(configuration.duration_s, parameters[output.source_device_id])
            if required is None:
                required = total
            return self._local_storage_manager.check_capacity(required)
        except Exception as error:
            return {"ready": False, "reason": f"Recording capacity unconfirmed: {error}"}

    @property
    def experiment_runtime_active(self) -> bool:
        """Whether this node owns an active Experiment, including an idle timed Experiment."""
        return self._running and not self._failed and self._active_experiment_runtime_context is not None

    @property
    def experiment_deadline_remaining_s(self) -> float:
        """Remaining local monotonic time for the captured authorized deadline."""
        if self._experiment_deadline is None:
            raise RuntimeError("No established Experiment deadline")
        return max(0.0, self._experiment_deadline["local_deadline_s"] - monotonic())

    @service_operation()
    def expire_experiment_if_due(self) -> bool:
        """Finalize only the expired Experiment and retain its producer-owned expiry proof."""
        with self._reservation_lock:
            if not self.experiment_runtime_active or self.experiment_deadline_remaining_s > 0:
                return False
            deadline = deepcopy(self._experiment_deadline)
            failure = None
            manifests = ()
            try:
                manifests = self.finalize_experiment_scientific_outputs(deadline["experiment_id"])
            except Exception as error:
                failure = error
                self._record_acquisition_failure(error)
            evidence = RuntimeEvidenceMessage(
                f"experiment-expiry-{self._session_id}-{self._node_id}-{deadline['experiment_id']}",
                self._session_id, "experiment_duration_expired", self._node_id,
                {**deadline, "finalized_local_time_s": monotonic(), "finalization_confirmed": failure is None,
                 "error": str(failure) if failure is not None else None,
                 "artifact_manifest_ids": [m.artifact_manifest_id for m in manifests]}, True)
            self._retain_runtime_evidence(evidence)
            if failure is not None:
                raise failure
            return True

    def read_experiment_expiry(self, experiment_id: str) -> RuntimeEvidenceMessage | None:
        """Read retained exact expiry evidence without manufacturing a missing outcome."""
        return next((m for m in self.runtime_evidence if m.evidence_type == "experiment_duration_expired"
                     and m.session_id == self._session_id and m.payload["experiment_id"] == experiment_id), None)

    @service_operation()
    def finalize_experiment_scientific_outputs(self, experiment_id: str) -> tuple[ArtifactManifest, ...]:
        """Attempt every prepared stream, preserving artifacts and reporting all failures."""
        self._ended_experiment_ids.add(experiment_id)
        if (self._active_experiment_runtime_context is not None
                and self._active_experiment_runtime_context.experiment_id == experiment_id):
            self.clear_experiment_runtime_context()
        if self._active_experiment_id == experiment_id:
            self.clear_experiment_runtime_health_mapping()
        manifests = []
        failures = []
        for (owner_experiment_id, _, _), storage_id in self._scientific_output_storage_ids.items():
            if owner_experiment_id != experiment_id:
                continue
            try:
                manifest = self._local_storage_manager.finalize_stream(storage_id)
                manifests.append(manifest)
                self._record_artifact_manifest(manifest)
            except Exception as error:
                failures.append(f"{storage_id}: {type(error).__name__}: {error}")
        if failures:
            self._last_error = "; ".join(failures)
            raise RuntimeError(f"Scientific stream finalization failed: {self._last_error}")
        return tuple(manifests)

    def _finalize_prepared_scientific_outputs(self) -> None:
        failures = []
        experiment_ids = set(self._prepared_scientific_outputs)
        experiment_ids.update(key[0] for key in self._scientific_output_storage_ids)
        if self._active_experiment_runtime_context is not None:
            experiment_ids.add(self._active_experiment_runtime_context.experiment_id)
        try:
            for experiment_id in sorted(experiment_ids):
                try:
                    self.finalize_experiment_scientific_outputs(experiment_id)
                except Exception as error:
                    failures.append(str(error))
        finally:
            self.clear_experiment_runtime_context()
            self.clear_experiment_runtime_health_mapping()
        if failures:
            raise RuntimeError("; ".join(failures))

    @property
    def experiment_scoped_health_observations(
        self,
    ) -> tuple[ExperimentScopedHealthObservation, ...]:
        """Experiment-scoped health observations in detection order."""

        return tuple(self._experiment_scoped_health_observations)

    @property
    def health_interpretation_evidence(
        self,
    ) -> tuple[HealthInterpretationEvidence, ...]:
        """Policy interpretations in originating observation order."""

        return tuple(self._health_interpretation_evidence)

    @property
    def health_runtime_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Retain health publication identities and original Session association at production."""
        return tuple(self._health_runtime_evidence)

    @service_operation(new_work=True)
    def activate_experiment_runtime_health_mapping(
        self,
        experiment_id: str,
        runtime_health_mapping: Iterable[ExperimentRuntimeHealthMapping],
    ) -> None:
        """Store an immutable active Experiment runtime health mapping."""

        if experiment_id in self._ended_experiment_ids:
            raise ValueError("Experiment runtime identity has ended and cannot be reused")
        self._active_experiment_id = experiment_id
        self._active_experiment_runtime_health_mapping = tuple(
            runtime_health_mapping
        )
        self._acquisition_health_observed_counts = {
            mapping.live_source_id: 0
            for mapping in self._active_experiment_runtime_health_mapping
        }
        self._acquisition_health_observations_recorded.clear()

    @service_operation(new_work=True)
    def activate_experiment_runtime_context(
        self,
        context: ActiveExperimentRuntimeContext,
    ) -> None:
        """Store active Experiment timing context separately from health scope."""

        if context.experiment_id in self._ended_experiment_ids:
            raise ValueError("Experiment runtime identity has ended and cannot be reused")
        if (self._experiment_deadline is None
                or self._experiment_deadline["experiment_id"] != context.experiment_id
                or self._experiment_deadline["duration_s"] != context.duration_s):
            raise RuntimeError("Experiment activation requires prepared capacity and an authorized deadline")
        self._active_experiment_runtime_context = context

    @service_operation()
    def clear_experiment_runtime_context(self) -> None:
        """Clear active Experiment timing context without stopping runtime."""

        self._active_experiment_runtime_context = None
        self._experiment_deadline = None

    @service_operation()
    def receive_active_synchronization_mapping(
        self,
        mapping: SynchronizationMapping | None,
    ) -> None:
        """Passively replace the current SynchronizationManager-owned mapping."""

        self._active_synchronization_mapping = mapping

    @property
    def synchronization_source_id(self) -> str | None:
        """Configured remote timing authority; None denotes a local development owner."""
        return self._synchronization_source_id

    @property
    def mapping_activation_history(self) -> tuple[dict[str, Any], ...]:
        """Immutable snapshots of node-local prospective activation boundaries."""
        with self._reservation_lock:
            return tuple(deepcopy(self._mapping_activation_history))

    @service_operation()
    def accept_synchronization_quality(self, session_id: str, source_id: str, quality: dict[str, Any]) -> None:
        """Apply only owner-issued timing state to the matching bound Session."""
        with self._reservation_lock:
            if (source_id != self._synchronization_source_id or source_id is None
                    or session_id != self._session_id or not self._session_prepared
                    or quality.get("session_id") != session_id
                    or quality.get("acquisition_node_id") != self._node_id):
                raise ValueError("Synchronization authority, node or Session mismatch")
            if type(quality.get("acceptable")) is not bool:
                raise ValueError("Explicit synchronization validity is required")
            if type(quality.get("assessment_sequence")) is not int or quality["assessment_sequence"] < 1:
                raise ValueError("An owner-issued assessment sequence is required")
            mapping = SynchronizationMapping.from_dict(quality["mapping"]) if quality.get("mapping") else None
            if mapping is not None and (mapping.session_id != session_id or mapping.acquisition_node_id != self._node_id):
                raise ValueError("Synchronization mapping scope mismatch")
            if mapping is not None and (any(type(v) not in (int, float) or not isfinite(v) for v in (
                    mapping.local_time_anchor_s, mapping.session_time_anchor_s, mapping.scale,
                    mapping.created_session_time_s)) or mapping.scale <= 0):
                raise ValueError("Malformed synchronization mapping fields")
            for field in ("measured_local_time_s", "uncertainty_s", "valid_until_local_time_s"):
                if type(quality.get(field)) not in (int, float) or not isfinite(quality[field]):
                    raise ValueError("Invalid synchronization readback")
            from lab_sync_acquisition.synchronization import SynchronizationConfiguration
            SynchronizationConfiguration.from_dict(quality["configuration"])
            previous = self._synchronization_quality
            if previous is not None:
                if quality["assessment_sequence"] == previous["assessment_sequence"]:
                    if quality != previous:
                        raise ValueError("Conflicting synchronization assessment identity")
                    return
                if (quality["assessment_sequence"] < previous["assessment_sequence"]
                        or quality["measured_local_time_s"] < previous["measured_local_time_s"]):
                    raise ValueError("Historical synchronization assessment cannot replace newer state")
            boundary = monotonic()
            activation_message = None
            if mapping is not None and mapping != self._active_synchronization_mapping:
                activation = {"session_id": session_id, "acquisition_node_id": self._node_id,
                    "mapping": mapping.to_dict(), "activated_local_time_s": boundary,
                    "measurement": deepcopy(quality)}
                activation_message = RuntimeEvidenceMessage(
                    f"mapping-activation-{session_id}-{self._node_id}-{len(self._mapping_activation_history)}",
                    session_id, "mapping_activation", self._node_id, activation, True)
                self._mapping_activation_history.append(deepcopy(activation))
                self._active_synchronization_mapping = mapping
            self._synchronization_quality = deepcopy(quality)
            application = {"session_id": session_id, "acquisition_node_id": self._node_id,
                           "applied_local_time_s": boundary, "quality": deepcopy(quality)}
            self._synchronization_quality_history.append(application)
            self._timing_quality_reported = False
            if activation_message is not None:
                self._retain_runtime_evidence(activation_message)
            self._retain_runtime_evidence(RuntimeEvidenceMessage(
                f"timing-quality-{session_id}-{self._node_id}-{quality['assessment_sequence']}",
                session_id, "timing_quality_observation", self._node_id, deepcopy(application), True))
            if self._running and not self._synchronization_readiness().ready:
                self._record_degraded_timing(monotonic())

    def _synchronization_readiness(self, local_time_s: float | None = None) -> ServiceReadiness:
        if self._synchronization_manager is not None:
            return self._synchronization_manager.check_ready()
        with self._reservation_lock:
            if self._session_id is None:
                return ServiceReadiness(self._synchronization_source_id, "synchronization_manager", False,
                                        False, "Session synchronization is not established before Session preparation")
            local = monotonic() if local_time_s is None else local_time_s
            # Later reports cannot renew or improve an earlier observation's quality.
            quality = next((item["quality"] for item in reversed(self._synchronization_quality_history)
                            if item["session_id"] == self._session_id
                            and item["applied_local_time_s"] <= local), None)
            ready = (quality is not None and quality["acceptable"] and quality["mapping"] is not None
                     and local <= quality["valid_until_local_time_s"])
            return ServiceReadiness(self._synchronization_source_id, "synchronization_manager", True,
                                    bool(ready), "ready" if ready else "synchronization_unconfirmed_or_degraded")

    def _session_time(self, local_time_s: float | None = None) -> float:
        if self._synchronization_manager is not None:
            return self._synchronization_manager.current_session_time_s
        with self._reservation_lock:
            mapping = self._active_synchronization_mapping
            if mapping is None or mapping.session_id != self._session_id:
                raise RuntimeError("No authorized Session-Time mapping is available")
            local = monotonic() if local_time_s is None else local_time_s
            return mapping.session_time_anchor_s + mapping.scale * (local - mapping.local_time_anchor_s)

    @service_operation(new_work=True)
    def activate_experiment_runtime(self, context: ActiveExperimentRuntimeContext,
                                    health_mapping: Iterable[ExperimentRuntimeHealthMapping]) -> dict[str, Any]:
        """Atomically apply Controller context without resetting a repeated health scope."""
        with self._reservation_lock:
            mapping = tuple(health_mapping)
            if (not context.experiment_id or type(context.experiment_start_session_time_s) not in (int, float)
                    or not isfinite(context.experiment_start_session_time_s)):
                raise ValueError("Explicit Experiment identity and finite Session Time are required")
            if not self._synchronization_readiness().ready:
                raise RuntimeError("Experiment requires acceptable synchronization")
            if context.experiment_id not in self._prepared_scientific_outputs:
                raise RuntimeError("Experiment scientific outputs must be prepared first")
            configuration = self._experiment_configurations.get(context.experiment_id)
            if configuration is None or context.duration_s != configuration.duration_s:
                raise RuntimeError("Experiment deadline requires the exact prepared duration")
            if (not self._running or not self._runtime_device_manager.check_readiness().all_ready
                    or any(a.state != DeviceAdapterState.RUNNING for a in self._runtime_device_manager.adapters)):
                raise RuntimeError("Experiment activation requires ready, running devices")
            if self._active_experiment_runtime_context is not None:
                if (self._active_experiment_runtime_context != context
                        or self._active_experiment_runtime_health_mapping != mapping):
                    raise ValueError("Conflicting active Experiment context")
                return deepcopy(self._experiment_deadline)
            session_deadline = context.experiment_start_session_time_s + context.duration_s
            if self._synchronization_manager is not None:
                local_deadline = self._synchronization_manager.local_deadline_for_session_time(session_deadline)
                timing_mapping = {"source": "co_located_synchronization_manager"}
            else:
                authorized = self._active_synchronization_mapping
                local_deadline = authorized.local_time_anchor_s + (
                    session_deadline - authorized.session_time_anchor_s) / authorized.scale
                timing_mapping = authorized.to_dict()
            if not isfinite(local_deadline):
                raise ValueError("Experiment deadline is not finite")
            self._experiment_deadline = {"experiment_id": context.experiment_id,
                "experiment_start_session_time_s": context.experiment_start_session_time_s,
                "duration_s": context.duration_s, "session_deadline_s": session_deadline,
                "local_deadline_s": local_deadline, "mapping": timing_mapping}
            self.activate_experiment_runtime_context(context)
            self.activate_experiment_runtime_health_mapping(context.experiment_id, mapping)
            return deepcopy(self._experiment_deadline)

    @service_operation()
    def clear_experiment_runtime_health_mapping(self) -> None:
        """Clear active Experiment runtime mapping without stopping runtime."""

        self._active_experiment_runtime_health_mapping = ()
        self._active_experiment_id = None
        self._acquisition_health_observed_counts = {}
        self._acquisition_health_observations_recorded.clear()

    def check_ready(self) -> dict[str, Any]:
        """Return acquisition-side readiness using existing readiness contracts."""

        device_readiness = self._inventory_readiness()
        service_readiness = (
            self._synchronization_readiness(),
            *((self._ingestor.check_ready(),) if self._ingestor is not None else ()),
            self._failure_evidence_readiness(),
            *dependency_readiness_reports(self),
        )
        ready = all(
            not readiness.required or readiness.ready for readiness in service_readiness
        )
        return {
            "ready": ready,
            "device_readiness": device_readiness,
            "service_readiness": service_readiness,
        }

    def check_node_readiness(
        self,
        additional_service_readiness: Iterable[ServiceReadiness] = (),
    ) -> AcquisitionNodeReadiness:
        """Return node-scoped technical readiness and independent reservation state."""

        if not self._node_id or not self._role:
            raise ValueError("Phase 2 node readiness requires node_id and role")
        device_readiness = self._inventory_readiness()
        service_readiness = (
            self._synchronization_readiness(),
            *((self._ingestor.check_ready(),) if self._ingestor is not None else ()),
            self._failure_evidence_readiness(),
            *dependency_readiness_reports(self),
            *additional_service_readiness,
        )
        if getattr(getattr(self, "_maintenance", None), "terminated", False):
            service_readiness += (ServiceReadiness(self._node_id, "acquisition_node", True, False, "service_terminated"),)
        readiness = AcquisitionNodeReadiness(
            node_id=self._node_id,
            reserved_for_session_id=self.reserved_for_session_id,
            role=self._role,
            device_readiness=device_readiness,
            service_readiness=service_readiness,
        )
        return readiness

    def _inventory_readiness(self) -> DeviceReadinessSummary:
        reports = {r.device_id: r for r in self._device_manager.check_readiness()}
        if not self._session_prepared and not self._initialization_cleanup_confirmed:
            for adapter in self._initialization_touched_adapters:
                reports[adapter.device_id] = DeviceReadiness(
                    adapter.device_id, False, "session_cleanup_unconfirmed", adapter.declared_capabilities)
        results = tuple(reports.get(d.device_id, DeviceReadiness(
            d.device_id, False, "declared_device_has_no_adapter", d.declared_capabilities or ()))
            for d in self._declared_devices if d.enabled)
        return DeviceReadinessSummary(results, all(r.ready for r in results))

    @service_operation(new_work=True)
    def start_runtime(self) -> dict[str, Any]:
        """Start the Session acquisition runtime and its existing evidence path."""

        if self._session_id is None:
            raise RuntimeError("Acquisition requires an active Session binding")
        if not self._session_prepared:
            raise RuntimeError("Acquisition requires successful Session preparation")
        if self._synchronization_source_id is not None and self._running:
            if self._failed:
                raise RuntimeError("Acquisition runtime is failed")
            return {"session_time_s": self._acquisition_start_session_time_s, "device_start_results": ()}
        failure_evidence_readiness = self._failure_evidence_readiness()
        if not failure_evidence_readiness.ready:
            raise RuntimeError(
                "AcquisitionNode cannot start; failure evidence location is not writable: "
                f"{failure_evidence_readiness.reason}"
            )
        self._initialization_cleanup_confirmed = False
        if not self._synchronization_readiness().ready:
            raise RuntimeError("Acquisition requires acceptable synchronization")
        session_time_s = (self._synchronization_manager.start() if self._synchronization_manager is not None
                          else self._session_time())
        self._acquisition_start_session_time_s = session_time_s
        start_evidence = RuntimeEvidenceMessage(
            f"session-start-{self._session_id}-{self._node_id}", self._session_id,
            "event", self._node_id or "acquisition_node",
            {"event_category": "session_lifecycle", "event_type": "session_start",
             "session_time_s": session_time_s}, True)
        self._retain_runtime_evidence(start_evidence)
        device_start_results = self._runtime_device_manager.start_all()
        self._running = True
        return {
            "session_time_s": session_time_s,
            "session_start_evidence": start_evidence,
            "device_start_results": device_start_results,
        }

    def start_acquisition(self) -> dict[str, Any]:
        """Compatibility wrapper for start_runtime()."""

        return self.start_runtime()

    @service_operation()
    def run_one_iteration(self) -> AcquisitionIterationSummary:
        """Collect explicitly selected products and persist their observations locally."""
        with self._reservation_lock:
            return self._collect_iteration()

    def _collect_iteration(self) -> AcquisitionIterationSummary:
        """Keep a prospective mapping stable through collection and local persistence."""
        if self.expire_experiment_if_due():
            return AcquisitionIterationSummary(self._iteration_index, 0, 0)
        if not self._session_prepared:
            raise RuntimeError("Acquisition requires successful Session preparation")
        if self._failed or not self._running:
            raise RuntimeError("Acquisition requires a running, prepared, healthy node")
        context = self._active_experiment_runtime_context
        outputs = self._prepared_scientific_outputs.get(context.experiment_id, ()) if context else ()
        products_by_device = {}
        for output in outputs:
            device = next(d for d in self._device_declarations if d.device_id == output.source_device_id)
            product = next(p for p in device.scientific_products if p.data_product_id == output.data_product_id)
            products_by_device.setdefault(device.device_id, []).append(product)
        collection_error = None
        try:
            results = self._runtime_device_manager.collect_products(products_by_device,
                session_id=self._session_id, experiment_id=context.experiment_id if context else None,
                acquisition_node_id=self._node_id or "acquisition_node")
        except _PartialDeviceCollectionError as error:
            collection_error = error
            results = error.partial_results
        failures = [collection_error.original_error] if collection_error is not None else []
        count = 0
        # Attempt all completed scientific collections before handling operational intake.
        for result in results:
            try:
                count += self._persist_product_collection(result, outputs)
            except Exception as error:
                failures.append(error)
        for result in results:
            for message in result.operational_evidence:
                try:
                    if (not isinstance(message, RuntimeEvidenceMessage)
                            or message.session_id != self._session_id or message.source_id != self._node_id):
                        raise ValueError("Operational evidence has a mismatched Session or producer")
                    self._retain_runtime_evidence(message)
                except Exception as error:
                    failures.append(error)
        if not failures:
            try:
                self._evaluate_acquisition_health()
            except Exception as error:
                failures.append(error)
        if failures:
            if len(failures) == 1:
                error = collection_error if collection_error is not None else failures[0]
            else:
                details = "; ".join(f"{type(failure).__name__}: {failure}" for failure in failures)
                error = ExceptionGroup(f"Acquisition failed: {details}", failures)
            try:
                self._record_acquisition_failure(error)
            except Exception as evidence_error:
                raise ExceptionGroup(
                    f"{error}; failure evidence handling failed: {evidence_error}",
                    [error, evidence_error]) from evidence_error
            raise error
        self._iteration_index += 1
        return AcquisitionIterationSummary(self._iteration_index, len(results), count)

    def _persist_product_collection(
        self, result: DeviceCollectionResult, outputs: tuple[ScientificOutputSelection, ...],
    ) -> int:
        context = self._active_experiment_runtime_context
        failures = []
        count = 0
        for product_id, rows in result.scientific_products.items():
            try:
                if context is None or not any(output.source_device_id == result.source_device_id
                                             and output.data_product_id == product_id for output in outputs):
                    raise ValueError("Scientific product is not selected for the active Experiment")
                storage_id = self._scientific_output_storage_ids.get(
                    (context.experiment_id, result.source_device_id, product_id))
                if storage_id is None or self._local_storage_manager is None:
                    raise ValueError("Scientific product has no prepared local storage")
                product = next(product for device in self._device_declarations
                               if device.device_id == result.source_device_id
                               for product in device.scientific_products if product.data_product_id == product_id)
            except Exception as error:
                failures.append(error)
                continue
            for row in rows:
                try:
                    if (row.get("session_id", self._session_id) != self._session_id
                            or row.get("experiment_id", context.experiment_id) != context.experiment_id
                            or row.get("data_product_id", product_id) != product_id
                            or row.get("source_device_id", result.source_device_id) != result.source_device_id
                            or row.get("acquisition_node_id", self._node_id) != self._node_id):
                        raise ValueError("Scientific observation identity differs from its selected product")
                    timed = self._with_session_time(row)
                    timed["session_id"] = self._session_id
                    timed["experiment_id"] = context.experiment_id
                    self._local_storage_manager.append_rows(storage_id, (timed,))
                    count += 1
                    self._observe_acquisition_health_records(result.source_device_id, product.product_type, (timed,))
                except Exception as error:
                    failures.append(error)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            details = "; ".join(f"{type(failure).__name__}: {failure}" for failure in failures)
            raise ExceptionGroup(f"Scientific preservation failed: {details}", failures)
        return count

    @property
    def runtime_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Retain produced operational messages for durable NATS publication."""
        return tuple(deepcopy(message) for message in self._runtime_evidence)

    def _retain_runtime_evidence(self, message: RuntimeEvidenceMessage) -> None:
        previous = next((item for item in self._runtime_evidence if item.evidence_id == message.evidence_id), None)
        if previous is not None:
            if previous.to_dict() != message.to_dict():
                raise ValueError("Conflicting retained operational evidence identity")
        else:
            self._runtime_evidence.append(deepcopy(message))
        if self._ingestor is not None:
            audit = self._ingestor.receive_runtime_evidence(message)
            if not audit.accepted:
                raise RuntimeError("Operational evidence acceptance is unconfirmed")

    def _record_acquisition_failure(self, error) -> None:
        self._failed = True
        self._last_error = f"{type(error).__name__}: {error}"
        message = RuntimeEvidenceMessage(
            f"acquisition-failure-{self._session_id}-{self._node_id}-{len(self._runtime_evidence)}",
            self._session_id, "event", self._node_id or "acquisition_node",
            {"event_category": "acquisition_health", "event_type": "acquisition_failure",
             "error": self._last_error, "experiment_id": self._active_experiment_id,
             "session_time_s": self._session_time()}, True)
        self._retain_runtime_evidence(message)

    @service_operation()
    def stop_runtime(self) -> dict[str, Any]:
        """Stop acquisition, finalize scientific products, and retain operational evidence."""
        with self._reservation_lock:
            return self._stop_runtime()

    def _stop_runtime(self) -> dict[str, Any]:
        """Resume unresolved cleanup from authoritative adapter and stream states."""
        self._session_prepared = False
        self._initialization_cleanup_confirmed = False
        self._running = False
        failures = []
        final_session_time_s = None
        try:
            final_session_time_s = (self._synchronization_manager.stop() if self._synchronization_manager is not None
                                    else self._session_time())
        except Exception as error:
            failures.append(error)
        # Only RUNNING permits stop(). Other states are handled by shutdown(),
        # whose existing contract confirms resource closure, including retries.
        running = tuple(a for a in self._runtime_device_manager.adapters if a.state == DeviceAdapterState.RUNNING)
        device_stop_results = DeviceManager(running).stop_all() if running else ()
        device_shutdown_results = self._runtime_device_manager.shutdown_all()
        try:
            self._finalize_prepared_scientific_outputs()
        except Exception as error:
            failures.append(error)
        finally:
            self.clear_experiment_runtime_context()
            self.clear_experiment_runtime_health_mapping()
        self._initialization_cleanup_confirmed = not failures and all(
            result.succeeded for result in (*device_stop_results, *device_shutdown_results))
        stop_evidence = RuntimeEvidenceMessage(
            f"session-stop-{self._session_id}-{self._node_id}-{len(self._runtime_evidence)}", self._session_id,
            "event", self._node_id or "acquisition_node",
            {"event_category": "session_lifecycle", "event_type": "session_stop",
             "session_time_s": final_session_time_s,
             "participant_cleanup_confirmed": self._initialization_cleanup_confirmed,
             "errors": [f"{type(error).__name__}: {error}" for error in failures]}, True)
        self._retain_runtime_evidence(stop_evidence)
        if failures:
            if len(failures) == 1:
                raise failures[0]
            raise ExceptionGroup("Acquisition shutdown failed", failures)
        return {"final_session_time_s": final_session_time_s,
                "session_stop_evidence": stop_evidence,
                "device_stop_results": device_stop_results,
                "device_shutdown_results": device_shutdown_results}

    def stop_acquisition(self) -> dict[str, Any]:
        """Compatibility wrapper for stop_runtime()."""

        return self.stop_runtime()

    def abort_acquisition(self) -> dict[str, Any]:
        """Attempt minimal acquisition shutdown without defining a failure model."""

        result = self.stop_acquisition()
        return {
            **result,
            "aborted": True,
        }

    def maintenance_evidence(self):
        """Return retained operational evidence required before service retirement."""
        return (*self._runtime_evidence, *self._health_runtime_evidence, *self._artifact_manifest_evidence)

    def maintenance_blockers(self, ingestor, storage_manager) -> list[str]:
        """Report node-owned runtime, local persistence, evidence, and device obligations."""
        blockers = []
        if self._session_id is not None:
            blockers.append("Active Session participation")
        if self.reserved_for_session_id is not None:
            blockers.append("Outstanding Session reservation")
        if self._running:
            blockers.append("Unfinished acquisition")
        if not self._initialization_cleanup_confirmed:
            blockers.append("Unconfirmed device cleanup")
        if any(a.state != DeviceAdapterState.DECLARED for a in self._device_manager.adapters):
            blockers.append("Unreleased devices")
        if self._local_storage_manager is not None and any(
                m.lifecycle_state != "finalized" for m in self._local_storage_manager.manifests):
            blockers.append("Unfinished scientific streams")
        if any(not (ingestor.has_durable_runtime_evidence(m) if ingestor is not None
                    else self._maintenance.evidence_preserved(m)) for m in self._artifact_manifest_evidence):
            blockers.append("Unpreserved artifact evidence")
        return blockers

    def _preserve_scientific_artifact(self, command, authorization, attempt) -> dict[str, Any]:
        self._maintenance._require_recovery_authorization(command)
        obligation = command.payload["obligation"]
        if obligation.get("session_id") != self._session_id or self._local_storage_manager is None:
            raise ValueError("The original local artifact Session binding is unavailable")
        matches = [m for m in self._local_storage_manager.manifests
                   if m.storage_id == obligation.get("storage_id")
                   and m.artifact_manifest_id == obligation.get("artifact_manifest_id")
                   and m.experiment_id == obligation.get("experiment_id")]
        if len(matches) != 1:
            raise ValueError("No unique authoritative local artifact matches this obligation")
        manifest = matches[0]
        context = self._active_experiment_runtime_context
        if context is not None and context.experiment_id == manifest.experiment_id:
            raise RuntimeError("Scientific artifact still belongs to active acquisition")
        if manifest.lifecycle_state != "finalized" and not any(e.storage_id == manifest.storage_id
                and e.evidence_type in {"write_failure", "finalization_failure"}
                for e in self._local_storage_manager.evidence):
            raise ValueError("No known failed preservation obligation for this stream")
        finalized = manifest
        if manifest.lifecycle_state != "finalized":
            attempt["actions"].append("local_artifact_finalization_attempted")
            finalized = self._local_storage_manager.finalize_stream(manifest.storage_id)
            attempt["actions"].append("local_artifact_finalization_confirmed")
        attempt["confirmation"] = {"artifact_manifest": finalized.to_dict(),
            "local_finalization_confirmed": True, "manifest_acceptance_confirmed": False,
            "node_cleanup_confirmed": self._initialization_cleanup_confirmed}
        attempt["actions"].append("artifact_manifest_preservation_attempted")
        self._record_artifact_manifest(finalized, resubmit_unconfirmed=True)
        message = next(m for m in self._artifact_manifest_evidence
                       if m.payload == finalized.to_dict())
        attempt["confirmation"]["manifest_acceptance_confirmed"] = self._ingestor.has_durable_runtime_evidence(message)
        if not attempt["confirmation"]["manifest_acceptance_confirmed"]:
            raise RuntimeError("Finalized artifact manifest lacks durable Ingestor acceptance")
        self._confirm_recovered_cleanup()
        attempt["confirmation"]["node_cleanup_confirmed"] = self._initialization_cleanup_confirmed
        return attempt["confirmation"]

    def _cleanup_device_resources(self, command, authorization, attempt) -> dict[str, Any]:
        self._maintenance._require_recovery_authorization(command)
        obligation = command.payload["obligation"]
        if (obligation.get("session_id") not in {self._session_id, self._reserved_for_session_id}
                or not obligation.get("session_id")):
            raise ValueError("Device cleanup requires the original owned Session scope")
        if self._running or self._active_experiment_runtime_context is not None:
            raise RuntimeError("Active acquisition must end before scoped recovery cleanup")
        owned = tuple(self._initialization_touched_adapters or self._runtime_device_manager.adapters)
        identities = obligation.get("device_ids")
        if (not isinstance(identities, list) or not identities or len(set(identities)) != len(identities)
                or not set(identities).issubset(a.device_id for a in owned)):
            raise ValueError("Known unique owned device identities are required")
        results, failures = [], []
        for adapter in owned:
            if adapter.device_id not in identities:
                continue
            attempt["actions"].append({"device_id": adapter.device_id, "action": "cleanup_attempted"})
            try:
                if adapter.state == DeviceAdapterState.RUNNING:
                    adapter.stop()
                if adapter.state != DeviceAdapterState.DECLARED:
                    adapter.shutdown()
                if adapter.state != DeviceAdapterState.DECLARED:
                    raise RuntimeError("Device shutdown is unconfirmed")
                results.append({"device_id": adapter.device_id, "resource_cleanup_confirmed": True,
                                "shutdown_performed": adapter.get_status().shutdown})
            except Exception as error:
                failures.append(f"{adapter.device_id}: {type(error).__name__}: {error}")
                results.append({"device_id": adapter.device_id, "resource_cleanup_confirmed": False})
        self._confirm_recovered_cleanup()
        attempt["confirmation"] = {"devices": results, "node_cleanup_confirmed": self._initialization_cleanup_confirmed}
        if failures:
            raise RuntimeError("; ".join(failures))
        attempt["actions"].append("selected_device_cleanup_confirmed")
        return attempt["confirmation"]

    def _confirm_recovered_cleanup(self) -> None:
        owned = tuple(self._initialization_touched_adapters or self._runtime_device_manager.adapters)
        devices_closed = all(a.state == DeviceAdapterState.DECLARED for a in owned)
        artifacts_closed = (self._local_storage_manager is None
            or all(m.lifecycle_state == "finalized" for m in self._local_storage_manager.manifests))
        self._initialization_cleanup_confirmed = not self._running and devices_closed and artifacts_closed
        # Neither operation releases the reservation or makes acquisition eligible.

    def maintenance_diagnostics(self, ingestor, storage_manager) -> dict[str, Any]:
        """Report node-owned participation, device safety, streams, and manifest evidence."""
        interface = getattr(self, "_maintenance", None)
        blockers = self.maintenance_blockers(ingestor, storage_manager)
        return {
            "participation": {"session_id": self._session_id,
                "reserved_for_session_id": self.reserved_for_session_id,
                "administrative_outcome": (interface._administrative_outcome({"session_id": self._session_id or self.reserved_for_session_id})
                                            if interface and (self._session_id or self.reserved_for_session_id) else None),
                "cleanup_confirmed": self._initialization_cleanup_confirmed,
                "is_running": self._running, "failed": self._failed},
            "device_cleanup": [{"device_id": adapter.device_id, "state": adapter.state.value,
                "cleanup_outcome": ("completed" if adapter.get_status().shutdown else
                                    "unresolved" if adapter.state != DeviceAdapterState.DECLARED else None),
                "recovery_assessment": None if adapter.state == DeviceAdapterState.DECLARED else "administrator_intervention"}
                for adapter in self._device_manager.adapters],
            "scientific_streams": [{"storage_id": m.storage_id, "artifact_manifest_id": m.artifact_manifest_id,
                "experiment_id": m.experiment_id,
                "local_finalization_outcome": "completed" if m.lifecycle_state == "finalized" else "unresolved"}
                for m in self._local_storage_manager.manifests] if self._local_storage_manager else [],
            "manifest_handoffs": [{"evidence_id": m.evidence_id, "session_id": m.session_id,
                "handoff_outcome": "completed" if (ingestor.has_durable_runtime_evidence(m)
                    if ingestor else interface.evidence_preserved(m)) else "unresolved"}
                for m in self._artifact_manifest_evidence],
            "restricted_resources": "node participation and device reuse" if blockers else None,
            "blocking_conditions": blockers,
        }

    async def _close_maintenance_resources(self, force: bool) -> None:
        if self._session_id is not None:
            if not self.abort_session_initialization(self._session_id):
                raise RuntimeError("AcquisitionNode cleanup is unconfirmed")
        else:
            for adapter in self._device_manager.adapters:
                if adapter.state == DeviceAdapterState.RUNNING:
                    adapter.stop()
                if adapter.state != DeviceAdapterState.DECLARED:
                    adapter.shutdown()
            if self._local_storage_manager is not None:
                self._local_storage_manager.cleanup()
        if any(a.state != DeviceAdapterState.DECLARED for a in self._device_manager.adapters):
            raise RuntimeError("Device release remains unconfirmed")

    @property
    def scientific_acquisition_active(self) -> bool:
        """Whether the running Experiment selects scientific products for collection."""
        context = self._active_experiment_runtime_context
        return bool(self._running and not self._failed and context is not None
                    and self._prepared_scientific_outputs.get(context.experiment_id))

    def status(self) -> dict[str, Any]:
        """Return simple acquisition-side runtime status."""

        return {
            "session_id": self._session_id,
            "reserved_for_session_id": self.reserved_for_session_id,
            "is_running": self._running,
            "cleanup_confirmed": self._initialization_cleanup_confirmed,
            "iteration_count": self._iteration_index,
            "last_error": self._last_error,
            "failed": self._failed,
            "active_experiment_runtime_health_mapping": (
                self._active_experiment_runtime_health_mapping
            ),
            "active_experiment_runtime_context": (
                self._active_experiment_runtime_context
            ),
            "active_synchronization_mapping": (
                self._active_synchronization_mapping
            ),
        }


    def _with_session_time(self, row: dict[str, Any]) -> dict[str, Any]:
        timestamped_row = dict(row)
        remote = self._synchronization_source_id is not None
        if remote or "session_time_s" not in row:
            local = row.get("acquisition_node_local_time_s", monotonic()) if remote else monotonic()
            if type(local) not in (int, float) or not isfinite(local):
                raise ValueError("Observation local time must be finite")
            mapped = self._session_time(local)
            if remote:
                activations = [a for a in self._mapping_activation_history if a["session_id"] == self._session_id
                               and a["activated_local_time_s"] <= local]
                if not activations:
                    raise ValueError("Observation precedes authorized mapping activation")
                mapping = activations[-1]["mapping"]
                mapped = mapping["session_time_anchor_s"] + mapping["scale"] * (local - mapping["local_time_anchor_s"])
                if "session_time_s" in row and row["session_time_s"] != mapped:
                    raise ValueError("Observation Session Time conflicts with authorized mapping")
            timestamped_row.update(
                session_time_s=mapped,
                acquisition_node_local_time_s=local,
                timestamp_status=("runtime_timestamped" if self._synchronization_readiness(local).ready
                                  else "synchronization_degraded"))
            if self._synchronization_source_id is not None and not self._synchronization_readiness().ready:
                self._record_degraded_timing(monotonic())
        if (self._active_experiment_runtime_context is not None
                and (remote or "experiment_time_s" not in timestamped_row)):
            timestamped_row["experiment_time_s"] = (
                timestamped_row["session_time_s"]
                - self._active_experiment_runtime_context.experiment_start_session_time_s
            )
        return timestamped_row

    def _record_degraded_timing(self, local_time_s: float) -> None:
        if self._timing_quality_reported:
            return
        quality = self._synchronization_quality
        interpretation = quality["configuration"]["quality_interpretation"] if quality else "uninterpreted"
        self._retain_runtime_evidence(RuntimeEvidenceMessage(
            f"timing-degraded-{self._session_id}-{self._node_id}-{len(self._runtime_evidence)}",
            self._session_id, "timing_quality_interpretation", self._node_id,
            {"experiment_id": self._active_experiment_id, "interpretation_label": interpretation,
             "acquisition_node_local_time_s": local_time_s, "session_time_s": self._session_time(local_time_s),
             "quality": deepcopy(quality), "condition": "synchronization_degraded"}, True))
        self._timing_quality_reported = True


    def _failure_evidence_readiness(self) -> ServiceReadiness:
        if not self._error_evidence_location:
            return ServiceReadiness(
                component_id="failure_evidence",
                component_type="failure_evidence_location",
                required=True,
                ready=False,
                reason="missing_error_evidence_location",
            )
        try:
            evidence_directory = Path(self._error_evidence_location)
            evidence_directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=evidence_directory,
                prefix=".failure-evidence-readiness-",
                delete=True,
            ):
                pass
        except (OSError, ValueError) as error:
            return ServiceReadiness(
                component_id="failure_evidence",
                component_type="failure_evidence_location",
                required=True,
                ready=False,
                reason=str(error),
            )
        return ServiceReadiness(
            component_id="failure_evidence",
            component_type="failure_evidence_location",
            required=True,
            ready=True,
            reason="writable",
        )

    def _observe_acquisition_health_records(
        self,
        source_device_id: str,
        record_kind: str,
        records: tuple[dict[str, Any], ...],
    ) -> None:
        mapping = next(
            (
                mapping
                for mapping in self._active_experiment_runtime_health_mapping
                if mapping.live_source_id == source_device_id
            ),
            None,
        )
        if mapping is None:
            return
        policy = self._acquisition_health_policies.get(
            mapping.acquisition_health_policy
        )
        rule = self._first_evidence_rule(policy)
        if rule is None:
            return
        if record_kind != rule["record_kind"]:
            return
        grace_deadline = (
            (self._acquisition_start_session_time_s or 0.0)
            + float(rule["grace_window_s"])
        )
        self._acquisition_health_observed_counts[source_device_id] += sum(
            "session_time_s" in row
            and isinstance(row["session_time_s"], (int, float))
            and not isinstance(row["session_time_s"], bool)
            and float(row["session_time_s"]) <= grace_deadline
            for row in records
        )

    def _evaluate_acquisition_health(self) -> None:
        if (
            self._acquisition_start_session_time_s is None
            or not self._active_experiment_runtime_health_mapping
        ):
            return
        current_session_time_s = (
            self._session_time()
        )
        for mapping in self._active_experiment_runtime_health_mapping:
            source_device_id = mapping.live_source_id
            policy_name = mapping.acquisition_health_policy
            if source_device_id in self._acquisition_health_observations_recorded:
                continue
            policy = self._acquisition_health_policies.get(policy_name)
            rule = self._first_evidence_rule(policy)
            if rule is None:
                continue
            observed_count = self._acquisition_health_observed_counts[source_device_id]
            grace_window_s = float(rule["grace_window_s"])
            elapsed = current_session_time_s - self._acquisition_start_session_time_s
            if observed_count > 0 or elapsed < grace_window_s:
                continue
            observation = ExperimentScopedHealthObservation(
                observation_id=f"health-observation-{self._next_health_observation_id}",
                experiment_id=self._active_experiment_id or "",
                live_source_id=source_device_id,
                expected_participant_id=mapping.expected_participant_id,
                expected_contribution=mapping.expected_contribution,
                acquisition_health_policy=policy_name,
                observation_type="expected_acquisition_evidence_missing",
                required=mapping.required,
                session_time_s=current_session_time_s,
                details={
                    "policy_kind": "first_evidence",
                    "expected_record_kind": rule["record_kind"],
                    "grace_window_s": grace_window_s,
                    "observed_record_count": observed_count,
                },
            )
            self._next_health_observation_id += 1
            self._experiment_scoped_health_observations.append(observation)
            observation_message = RuntimeEvidenceMessage(
                f"health-observation-{self._session_id}-{self._node_id}-{observation.observation_id}",
                self._session_id, "event", self._node_id or "acquisition_node",
                {"event_category": "acquisition_health", **observation.to_dict()}, True)
            self._retain_runtime_evidence(observation_message)
            interpretation = HealthInterpretationEvidence(
                originating_observation_id=observation.observation_id,
                experiment_id=observation.experiment_id,
                live_source_id=observation.live_source_id,
                expected_participant_id=observation.expected_participant_id,
                observation_type=observation.observation_type,
                acquisition_health_policy=observation.acquisition_health_policy,
                interpretation_label=policy.interpretation.get(
                    observation.observation_type,
                    "uninterpreted",
                ),
                required=observation.required,
                session_time_s=observation.session_time_s,
                details={"expected_contribution": mapping.expected_contribution},
            )
            self._health_interpretation_evidence.append(interpretation)
            message = RuntimeEvidenceMessage(
                evidence_id=f"health-interpretation-{self._session_id}-{self._node_id}-{interpretation.originating_observation_id}",
                session_id=self._session_id, evidence_type="health_interpretation",
                source_id=self._node_id or "acquisition_node", payload=interpretation.to_dict(), is_persistent=True)
            self._health_runtime_evidence.append(message)
            self._retain_runtime_evidence(message)
            self._acquisition_health_observations_recorded.add(source_device_id)

    def _first_evidence_rule(
        self,
        policy: AcquisitionHealthPolicy | None,
    ) -> Mapping[str, Any] | None:
        if policy is None:
            return None
        rule = policy.evaluation_rules.get("first_evidence")
        if rule is None:
            return None
        grace_window_s = rule.get("grace_window_s")
        if (
            isinstance(rule.get("record_kind"), str)
            and not isinstance(grace_window_s, bool)
            and isinstance(grace_window_s, (int, float))
            and isfinite(grace_window_s)
            and grace_window_s >= 0
        ):
            return rule
        return None
