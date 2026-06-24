# Code Map

## src/lab_sync_acquisition/__init__.py

- DeviceAdapter: Public import for the minimum live runtime control interface for one device adapter.
- DeviceAdapterLifecycleError: Public import for invalid live adapter lifecycle operations.
- DeviceAdapterState: Public import for minimum live adapter lifecycle states.
- DeviceDeclaration: Public import for persistent/config declarations of intended session devices.
- DeviceLifecycleResult: Public import for per-adapter Device Manager lifecycle call results.
- DeviceManager: Public import for coordinating already-created live Device Adapters.
- DeviceReadiness: Public import for live adapter readiness results.
- DeviceReadinessNotImplementedError: Public import for base adapters without concrete readiness behavior.
- DeviceReadinessSummary: Public import for aggregated Device Manager readiness results.
- DeviceStatus: Public import for live adapter status snapshots.
- LifecycleTransition: Public import for recorded lifecycle transitions.
- ReadinessCheck: Public import for recorded readiness checks.
- Session: Public import for the runtime session lifecycle model.
- SessionConfig: Public import for explicit session declarations required by this slice.
- SessionLifecycleError: Public import for lifecycle operation failures.
- SessionState: Public import for accepted Phase 1 session lifecycle states.

## src/lab_sync_acquisition/device.py

- DeviceDeclaration: Holds explicit persistent/config fields for an intended device before any live adapter exists, with capabilities stored immutably.

## src/lab_sync_acquisition/device_adapter.py

- DeviceAdapterState: Enumerates the minimum lifecycle states for a live device adapter.
- DeviceReadiness: Records whether a live device adapter is ready to start.
- DeviceStatus: Reports the current live adapter lifecycle status without scientific data.
- DeviceAdapterLifecycleError: Signals invalid live adapter lifecycle operations.
- DeviceReadinessNotImplementedError: Signals that a live adapter has no concrete readiness implementation.
- DeviceAdapter: Provides the minimum live runtime control interface for one device adapter with externally read-only lifecycle state.

## src/lab_sync_acquisition/device_manager.py

- DeviceLifecycleResult: Records the result of one Device Manager lifecycle call against one adapter.
- DeviceReadinessSummary: Aggregates readiness results across already-created adapters.
- DeviceManager: Holds at least one already-created Device Adapter and coordinates lifecycle, readiness, and status calls without creating adapters.

## src/lab_sync_acquisition/session.py

- SessionState: Enumerates the accepted Phase 1 session lifecycle states.
- SessionConfig: Holds explicit session declarations, including selected device declarations, needed to initialize a session.
- ReadinessCheck: Records the result of a readiness condition checked during lifecycle transitions.
- LifecycleTransition: Records an allowed lifecycle state transition in sequence order.
- SessionLifecycleError: Signals invalid lifecycle operations or failed readiness requirements.
- Session: Owns one session's lifecycle state, read-only transition history, read-only readiness checks, cleanup status, and final status in memory.
