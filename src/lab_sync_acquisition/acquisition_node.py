"""Bounded acquisition-side execution for Phase 1 workflows."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
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
from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.communication import (
    ARTIFACT_MANIFEST_EVIDENCE_TYPE, RuntimeEvidenceMessage,
)
from lab_sync_acquisition.acquisition_node_readiness import AcquisitionNodeReadiness
from lab_sync_acquisition.device_manager import (
    DeviceManager, DeviceReadinessSummary, DeviceRecordCollection,
    _PartialDeviceCollectionError,
)
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.device_adapter import DeviceAdapterState, DeviceReadiness
from lab_sync_acquisition.local_storage import LocalStorageManager, ArtifactManifest
from lab_sync_acquisition.session import ScientificOutputSelection
from lab_sync_acquisition.experiment_runtime import (
    ActiveExperimentRuntimeContext,
    ExperimentRuntimeHealthMapping,
    ExperimentScopedHealthObservation,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.synchronization import (
    SynchronizationManager,
    SynchronizationMapping,
)


@dataclass(frozen=True)
class AcquisitionIterationSummary:
    """Inspectable result for one bounded acquisition iteration."""

    iteration_index: int
    collections_seen: int
    envelopes_sent: int
    accepted_count: int
    rejected_count: int


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
        acquisition_configuration: Mapping[str, Any] | None = None,
        acquisition_health_policies: Iterable[AcquisitionHealthPolicy] = (),
        error_evidence_location: str | None = None,
        *,
        default_local_storage_root: str | Path | None = None,
        device_declarations: Iterable[DeviceDeclaration] | None = None,
    ) -> None:
        self._session_id = session_id
        # Explicitly pre-bound nodes retain the historical caller-prepared workflow.
        self._session_prepared = session_id is not None
        if device_manager is None or synchronization_manager is None or ingestor is None:
            raise ValueError("AcquisitionNode requires deployment runtime collaborators")
        self._device_manager = device_manager
        self._deployment_device_configurations = {
            adapter.device_id: deepcopy(adapter.initialization_config)
            for adapter in device_manager.adapters
        }
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
        self._handoff_failure_policy = self._read_handoff_failure_policy(
            acquisition_configuration
        )
        self._must_preserve_failure_threshold = (
            self._read_must_preserve_failure_threshold(acquisition_configuration)
        )
        self._consecutive_must_preserve_handoff_failures = 0
        self._failed = False
        (
            self._stream_batch_max_records,
            self._stream_batch_max_age_s,
        ) = self._read_stream_batch_configuration(acquisition_configuration)
        self._pending_stream_batches: dict[
            tuple[str | None, str, str], list[dict[str, Any]]
        ] = {}
        self._pending_stream_batch_started_session_times: dict[
            tuple[str | None, str, str], float
        ] = {}
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
        self._next_health_observation_id = 1

    @property
    def node_id(self) -> str | None:
        return self._node_id

    @property
    def declared_devices(self) -> tuple[DeviceDeclaration, ...]:
        """Deployment inventory, independent of Session selections and availability."""
        return self._declared_devices

    @property
    def reserved_for_session_id(self) -> str | None:
        with self._reservation_lock:
            return self._reserved_for_session_id

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
            self._active_synchronization_mapping = None
            self.clear_experiment_runtime_context()
            self.clear_experiment_runtime_health_mapping()
            return True

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("A real nonempty session_id is required")

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
            for adapter in selected_adapters:
                self._initialization_touched_adapters.append(adapter)
                configuration = (device_configurations or {}).get(adapter.device_id)
                if configuration is None:
                    configuration = deepcopy(self._deployment_device_configurations[adapter.device_id])
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
            self._consecutive_must_preserve_handoff_failures = 0
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

    def _record_artifact_manifest(self, manifest: ArtifactManifest) -> None:
        evidence_id = f"artifact-manifest-{manifest.artifact_manifest_id}-{manifest.lifecycle_state}"
        if any(message.evidence_id == evidence_id for message in self._artifact_manifest_evidence):
            return
        message = RuntimeEvidenceMessage(
            evidence_id=evidence_id, session_id=manifest.session_id,
            evidence_type=ARTIFACT_MANIFEST_EVIDENCE_TYPE,
            source_id=manifest.acquisition_node_id, payload=manifest.to_dict(),
            is_persistent=True,
        )
        self._artifact_manifest_evidence.append(message)
        self._ingestor.receive_runtime_evidence(message)

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
        self._local_storage_manager = manager
        self._device_declarations = tuple(device_declarations)

    def prepare_experiment_scientific_outputs(
        self,
        experiment_id: str,
        scientific_outputs: Iterable[ScientificOutputSelection],
    ) -> ServiceReadiness:
        """Resolve explicit declarations and request empty streams before acquisition."""
        created: list[str] = []
        try:
            outputs = tuple(scientific_outputs)
            if experiment_id in self._ended_experiment_ids:
                raise ValueError("Experiment runtime identity has ended and cannot be reused")
            if len(set(outputs)) != len(outputs):
                raise ValueError("Duplicate scientific output selection")
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

    def activate_experiment_runtime_context(
        self,
        context: ActiveExperimentRuntimeContext,
    ) -> None:
        """Store active Experiment timing context separately from health scope."""

        if context.experiment_id in self._ended_experiment_ids:
            raise ValueError("Experiment runtime identity has ended and cannot be reused")
        self._active_experiment_runtime_context = context

    def clear_experiment_runtime_context(self) -> None:
        """Clear active Experiment timing context without stopping runtime."""

        self._active_experiment_runtime_context = None

    def receive_active_synchronization_mapping(
        self,
        mapping: SynchronizationMapping | None,
    ) -> None:
        """Passively replace the current SynchronizationManager-owned mapping."""

        self._active_synchronization_mapping = mapping

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
            self._synchronization_manager.check_ready(),
            self._ingestor.check_ready(),
            self._failure_evidence_readiness(),
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
            self._synchronization_manager.check_ready(),
            self._ingestor.check_ready(),
            self._failure_evidence_readiness(),
            *additional_service_readiness,
        )
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

    def start_runtime(self) -> dict[str, Any]:
        """Start the Session acquisition runtime and its existing evidence path."""

        if self._session_id is None:
            raise RuntimeError("Acquisition requires an active Session binding")
        if not self._session_prepared:
            raise RuntimeError("Acquisition requires successful Session preparation")
        failure_evidence_readiness = self._failure_evidence_readiness()
        if not failure_evidence_readiness.ready:
            raise RuntimeError(
                "AcquisitionNode cannot start; failure evidence location is not writable: "
                f"{failure_evidence_readiness.reason}"
            )
        self._initialization_cleanup_confirmed = False
        session_time_s = self._synchronization_manager.start()
        self._acquisition_start_session_time_s = session_time_s
        session_start_audit = self._send_envelope(
            source_device_id="acquisition_node",
            record_kind="event",
            records=[
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_start",
                    "session_time_s": session_time_s,
                }
            ],
        )
        device_start_results = self._runtime_device_manager.start_all()
        self._running = True
        return {
            "session_time_s": session_time_s,
            "session_start_audit": session_start_audit,
            "device_start_results": device_start_results,
        }

    def start_acquisition(self) -> dict[str, Any]:
        """Compatibility wrapper for start_runtime()."""

        return self.start_runtime()

    def run_one_iteration(self) -> AcquisitionIterationSummary:
        """Collect one bounded batch of records and send envelopes to ingestion."""

        if self._failed:
            raise RuntimeError("AcquisitionNode has failed and cannot run new iterations")
        if not self._session_prepared:
            raise RuntimeError("Acquisition requires successful Session preparation")
        if not self._running:
            raise RuntimeError("AcquisitionNode must be running before iteration")

        context = self._active_experiment_runtime_context
        outputs = self._prepared_scientific_outputs.get(context.experiment_id, ()) if context else ()
        try:
            if outputs:
                collected = self._runtime_device_manager.collect_scientific_records(
                    scientific_source_device_ids={output.source_device_id for output in outputs}
                )
                record_collections = collected
            else:
                record_collections = self._runtime_device_manager.collect_records()
        except _PartialDeviceCollectionError as error:
            try:
                self._preserve_partial_scientific_collections(error, outputs)
            except Exception as preservation_error:
                self._last_error = str(preservation_error)
                raise
            self._last_error = str(error)
            raise
        except Exception as error:
            self._last_error = f"{type(error).__name__}: {error}"
            raise
        self._iteration_index += 1
        envelopes_sent = 0
        accepted_count = 0
        rejected_count = 0

        for collection in record_collections:
            try:
                if outputs:
                    collection = self._persist_scientific_collection(collection, outputs)
                audits = self._send_runtime_collection(collection)
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"
                raise
            envelopes_sent += len(audits)
            accepted_count += sum(audit.accepted for audit in audits)
            rejected_count += sum(not audit.accepted for audit in audits)

        health_audits = self._evaluate_acquisition_health()
        envelopes_sent += len(health_audits)
        accepted_count += sum(audit.accepted for audit in health_audits)
        rejected_count += sum(not audit.accepted for audit in health_audits)

        return AcquisitionIterationSummary(
            iteration_index=self._iteration_index,
            collections_seen=len(record_collections),
            envelopes_sent=envelopes_sent,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
        )

    def _send_runtime_collection(self, collection: DeviceRecordCollection) -> tuple[Any, ...]:
        records = tuple(self._with_session_time(row) for row in collection.records)
        self._observe_acquisition_health_records(
            source_device_id=collection.source_device_id, record_kind=collection.record_kind, records=records,
        )
        if collection.record_kind == "stream" and self._stream_batching_enabled():
            return self._append_stream_records(
                source_device_id=collection.source_device_id, record_kind=collection.record_kind, records=records,
            )
        return (self._send_envelope(
            source_device_id=collection.source_device_id, record_kind=collection.record_kind, records=records,
        ),)

    def _preserve_partial_scientific_collections(
        self, error: _PartialDeviceCollectionError, outputs: tuple[ScientificOutputSelection, ...],
    ) -> None:
        preservation_errors = []
        for result in error.partial_results:
            try:
                collection = self._persist_scientific_collection(result, outputs)
                self._send_runtime_collection(collection)
            except Exception as preservation_error:
                preservation_errors.append(preservation_error)
        if preservation_errors:
            reason = "; ".join(f"{type(failure).__name__}: {failure}" for failure in preservation_errors)
            raise ExceptionGroup(
                f"Collection failed: {error}; partial-data preservation failed: {reason}",
                [error.original_error, *preservation_errors],
            ) from error

    def _persist_scientific_collection(self, result: Any, outputs: tuple[ScientificOutputSelection, ...]) -> DeviceRecordCollection:
        runtime = result.runtime_records
        runtime_rows = [dict(row) for row in runtime.records]
        # Validate the lightweight half before any raw data can enter an envelope.
        json.dumps(runtime_rows, allow_nan=False)
        scientific = result.scientific_records
        if scientific is not None:
            context = self._active_experiment_runtime_context
            if context is None or scientific.source_device_id != runtime.source_device_id:
                raise ValueError("Scientific collection requires matching active Experiment/source context")
            device = next((device for device in self._device_declarations
                           if device.device_id == scientific.source_device_id), None)
            if device is None:
                raise ValueError("Scientific collection source has no device declaration")
            selected_ids = {output.data_product_id for output in outputs
                            if output.source_device_id == scientific.source_device_id}
            pending_rows = []
            used_metadata = set()
            for row in scientific.records:
                product_id = row.get("data_product_id")
                candidates = [product for product in device.scientific_products
                              if (product.data_product_id == product_id if product_id is not None
                                  else product.product_type == scientific.record_kind)]
                if len(candidates) != 1:
                    raise ValueError("Scientific record product identity is unknown or ambiguous")
                product = candidates[0]
                if product.data_product_id not in selected_ids:
                    continue
                if row.get("experiment_id", context.experiment_id) != context.experiment_id:
                    raise ValueError("Scientific record belongs to a different Experiment")
                if row.get("session_id", self._session_id) != self._session_id:
                    raise ValueError("Scientific record belongs to a different Session")
                storage_id = self._scientific_output_storage_ids.get((
                    context.experiment_id, scientific.source_device_id, product.data_product_id))
                if storage_id is None or self._local_storage_manager is None:
                    raise ValueError("Scientific product has no prepared storage mapping")
                matches = [index for index, metadata in enumerate(runtime_rows)
                           if "frame_index" in row and metadata.get("frame_index") == row["frame_index"]
                           and metadata.get("data_product_id", product.data_product_id) == product.data_product_id
                           and metadata.get("read_success", True)]
                if len(matches) > 1:
                    raise ValueError("Ambiguous runtime metadata for scientific frame")
                if "frame" in row and not matches:
                    raise ValueError("Scientific frame has no matching lightweight runtime metadata")
                metadata_index = matches[0] if matches else None
                if "frame" in row:
                    association = (product.data_product_id, metadata_index)
                    if association in used_metadata:
                        raise ValueError("Ambiguous scientific frames reuse one runtime metadata record")
                    used_metadata.add(association)
                metadata = runtime_rows[metadata_index] if metadata_index is not None else None
                timing_source = row if "session_time_s" in row else (metadata if metadata is not None else row)
                timed = self._with_session_time(timing_source)
                timing_fields = ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status")
                timing = {name: timed[name] for name in timing_fields if name in timed}
                for original in (row, metadata):
                    if original is not None and "session_time_s" in original:
                        if any(name in original and original[name] != value for name, value in timing.items()):
                            raise ValueError("Pre-existing scientific/runtime timing does not agree")
                scientific_row = {**row, **timing, "experiment_id": context.experiment_id,
                                  "session_id": self._session_id}
                if metadata_index is not None:
                    runtime_rows[metadata_index] = {**metadata, **timing}
                pending_rows.append((storage_id, scientific_row))
            # Validate associations for the entire bounded collection before writing.
            for storage_id, scientific_row in pending_rows:
                self._local_storage_manager.append_rows(storage_id, (scientific_row,))
        return DeviceRecordCollection(runtime.source_device_id, runtime.record_kind, tuple(runtime_rows))

    def stop_runtime(self) -> dict[str, Any]:
        """Stop the Session acquisition runtime and perform existing cleanup."""

        self._session_prepared = False
        self._initialization_cleanup_confirmed = False
        try:
            self._flush_pending_stream_batches()
        finally:
            try:
                final_session_time_s = self._synchronization_manager.stop()
                session_stop_audit = self._send_envelope(
                    source_device_id="acquisition_node",
                    record_kind="event",
                    records=[
                        {
                            "event_category": "session_lifecycle",
                            "event_type": "session_stop",
                            "session_time_s": final_session_time_s,
                        }
                    ],
                )
            finally:
                device_stop_results = self._runtime_device_manager.stop_all()
                device_shutdown_results = self._runtime_device_manager.shutdown_all()
                self._running = False
                self._finalize_prepared_scientific_outputs()
        self._initialization_cleanup_confirmed = all(r.succeeded for r in (*device_stop_results, *device_shutdown_results))
        return {
            "final_session_time_s": final_session_time_s,
            "session_stop_audit": session_stop_audit,
            "device_stop_results": device_stop_results,
            "device_shutdown_results": device_shutdown_results,
        }

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

    def status(self) -> dict[str, Any]:
        """Return simple acquisition-side runtime status."""

        return {
            "session_id": self._session_id,
            "reserved_for_session_id": self.reserved_for_session_id,
            "is_running": self._running,
            "iteration_count": self._iteration_index,
            "last_error": self._last_error,
            "failed": self._failed,
            "consecutive_must_preserve_handoff_failures": (
                self._consecutive_must_preserve_handoff_failures
            ),
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

    def _send_envelope(
        self,
        source_device_id: str,
        record_kind: str,
        records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> Any:
        envelope = AcquisitionRecordEnvelope(
            session_id=self._session_id,
            source_device_id=source_device_id,
            record_kind=record_kind,
            records=records,
            source_node_id=self._node_id,
        )
        envelope_data = envelope.to_dict()
        reconstructed_envelope = AcquisitionRecordEnvelope.from_dict(envelope_data)
        try:
            audit = self._ingestor.receive_envelope(reconstructed_envelope)
            self._consecutive_must_preserve_handoff_failures = 0
            return audit
        except Exception as error:
            return self._record_handoff_failure(reconstructed_envelope, error)

    def _record_handoff_failure(
        self,
        envelope: AcquisitionRecordEnvelope,
        error: Exception,
    ) -> Any:
        if not self._error_evidence_location:
            raise RuntimeError(
                "Sender handoff failed but error_evidence_location is not configured"
            ) from error

        preserve = self._handoff_failure_policy == "must_preserve"
        evidence = {
            "session_id": envelope.session_id,
            "source_node_id": envelope.source_node_id,
            "source_device_id": envelope.source_device_id,
            "record_kind": envelope.record_kind,
            "record_count": len(envelope.records),
            "failure_type": type(error).__name__,
            "error_message": str(error),
            "policy_name": self._handoff_failure_policy,
            "action_taken": (
                "preserved_failed_envelope"
                if preserve
                else "recorded_drop_and_continued"
            ),
            "failure_session_time_s": (
                self._synchronization_manager.current_session_time_s
            ),
            "preserved_envelope": preserve,
        }
        if preserve:
            evidence["envelope"] = envelope.to_dict()

        evidence_directory = Path(self._error_evidence_location)
        evidence_directory.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_directory / "sender_handoff_failures.jsonl"
        with evidence_path.open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(evidence))
            evidence_file.write("\n")

        if preserve:
            self._consecutive_must_preserve_handoff_failures += 1
            if (
                self._must_preserve_failure_threshold is not None
                and self._consecutive_must_preserve_handoff_failures
                >= self._must_preserve_failure_threshold
            ):
                self._failed = True
                self._running = False
                self._last_error = f"{type(error).__name__}: {error}"

        return _FailedHandoffAudit()

    def _with_session_time(self, row: dict[str, Any]) -> dict[str, Any]:
        if "session_time_s" in row:
            return dict(row)
        session_time_s = self._synchronization_manager.current_session_time_s
        timestamped_row = {
            **row,
            "session_time_s": session_time_s,
            "acquisition_node_local_time_s": monotonic(),
            "timestamp_status": "runtime_timestamped",
        }
        if self._active_experiment_runtime_context is not None:
            timestamped_row["experiment_time_s"] = (
                session_time_s
                - self._active_experiment_runtime_context.experiment_start_session_time_s
            )
        return timestamped_row

    def _append_stream_records(
        self,
        source_device_id: str,
        record_kind: str,
        records: tuple[dict[str, Any], ...],
    ) -> tuple[Any, ...]:
        key = (self._node_id, source_device_id, record_kind)
        pending = self._pending_stream_batches.get(key)
        if records:
            if pending is None:
                pending = []
                self._pending_stream_batches[key] = pending
                self._pending_stream_batch_started_session_times[key] = (
                    self._synchronization_manager.current_session_time_s
                )
            pending.extend(records)
        elif pending is None:
            return ()

        audits = []
        while (
            self._stream_batch_max_records is not None
            and len(pending) >= self._stream_batch_max_records
        ):
            batch = pending[: self._stream_batch_max_records]
            audit = self._send_envelope(
                source_device_id=source_device_id,
                record_kind=record_kind,
                records=tuple(batch),
            )
            del pending[: self._stream_batch_max_records]
            audits.append(audit)
            if pending:
                self._pending_stream_batch_started_session_times[key] = (
                    self._synchronization_manager.current_session_time_s
                )

        if pending and self._stream_batch_max_age_s is not None:
            batch_started = self._pending_stream_batch_started_session_times[key]
            batch_age = (
                self._synchronization_manager.current_session_time_s
                - batch_started
            )
            if batch_age >= self._stream_batch_max_age_s:
                audit = self._send_envelope(
                    source_device_id=source_device_id,
                    record_kind=record_kind,
                    records=tuple(pending),
                )
                pending.clear()
                audits.append(audit)

        if not pending:
            self._pending_stream_batches.pop(key, None)
            self._pending_stream_batch_started_session_times.pop(key, None)
        return tuple(audits)

    def _flush_pending_stream_batches(self) -> None:
        for key, records in tuple(self._pending_stream_batches.items()):
            source_node_id, source_device_id, record_kind = key
            if source_node_id != self._node_id:
                continue
            if records:
                self._send_envelope(
                    source_device_id=source_device_id,
                    record_kind=record_kind,
                    records=tuple(records),
                )
            self._pending_stream_batches.pop(key, None)
            self._pending_stream_batch_started_session_times.pop(key, None)

    def _read_stream_batch_configuration(
        self,
        acquisition_configuration: Mapping[str, Any] | None,
    ) -> tuple[int | None, float | None]:
        if not isinstance(acquisition_configuration, Mapping):
            return None, None
        policy_name = acquisition_configuration.get("batch_policy")
        policies = acquisition_configuration.get("batch_policies")
        if policy_name != "type_1" or not isinstance(policies, Mapping):
            return None, None
        policy = policies.get(policy_name)
        if not isinstance(policy, Mapping):
            return None, None
        max_records = policy.get("max_records")
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records <= 1
        ):
            max_records = None
        max_batch_age_s = policy.get("max_batch_age_s")
        if (
            isinstance(max_batch_age_s, bool)
            or not isinstance(max_batch_age_s, (int, float))
            or not isfinite(max_batch_age_s)
            or max_batch_age_s <= 0
        ):
            max_batch_age_s = None
        return max_records, (
            float(max_batch_age_s) if max_batch_age_s is not None else None
        )

    def _read_handoff_failure_policy(
        self,
        acquisition_configuration: Mapping[str, Any] | None,
    ) -> str:
        if not isinstance(acquisition_configuration, Mapping):
            return "must_preserve"
        policy_name = acquisition_configuration.get("handoff_failure_policy")
        policies = acquisition_configuration.get("handoff_failure_policies")
        if policy_name not in {"must_preserve", "best_effort"}:
            return "must_preserve"
        if not isinstance(policies, Mapping):
            return "must_preserve"
        policy = policies.get(policy_name)
        if not isinstance(policy, Mapping):
            return "must_preserve"
        expected_preserve = policy_name == "must_preserve"
        if policy.get("preserve_failed_envelope") is not expected_preserve:
            return "must_preserve"
        return policy_name

    def _read_must_preserve_failure_threshold(
        self,
        acquisition_configuration: Mapping[str, Any] | None,
    ) -> int | None:
        if not isinstance(acquisition_configuration, Mapping):
            return None
        policies = acquisition_configuration.get("handoff_failure_policies")
        if not isinstance(policies, Mapping):
            return None
        policy = policies.get("must_preserve")
        if not isinstance(policy, Mapping):
            return None
        threshold = policy.get("consecutive_failure_threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            return None
        if threshold < 1:
            return None
        return threshold

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

    def _evaluate_acquisition_health(self) -> tuple[Any, ...]:
        if (
            self._acquisition_start_session_time_s is None
            or not self._active_experiment_runtime_health_mapping
        ):
            return ()
        current_session_time_s = (
            self._synchronization_manager.current_session_time_s
        )
        audits = []
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
            audits.append(
                self._send_envelope(
                    source_device_id="acquisition_node",
                    record_kind="event",
                    records=(observation.to_dict(),),
                )
            )
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
            audits.append(
                self._send_envelope(
                    source_device_id="acquisition_node",
                    record_kind="event",
                    records=(interpretation.to_dict(),),
                )
            )
            self._acquisition_health_observations_recorded.add(source_device_id)
        return tuple(audits)

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

    def _stream_batching_enabled(self) -> bool:
        return (
            self._stream_batch_max_records is not None
            or self._stream_batch_max_age_s is not None
        )


@dataclass(frozen=True)
class _FailedHandoffAudit:
    accepted: bool = False
