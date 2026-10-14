# Installation And Deployment

## Status And Scope

Q022-A Decisions 367-374 are accepted and synchronized, not implemented or
independently validated. This is the initial manual installation contract and a
current-interface reference, not a working installer or deployment certification.
The framework remains device-independent; a first camera deployment does not
define general adapter/configuration requirements. Q022 remains OPEN.

## Accepted Manual Procedure

1. Install the common software package and dependencies needed by the chosen
   supported devices/services. Select the service role explicitly at launch;
   configuration does not implicitly start services. Final role CLI syntax is
   not yet implemented or prescribed.
2. Create installation-local configuration outside the Git repository from
   committed templates/definitions. Keep NATS/service storage/retrieval settings
   distinct from node hardware settings. Credentials and private keys stay outside
   Git and portable Session evidence.
3. Assign the node's persistent unique identity, identify installed devices,
   select adapters explicitly, and configure their physical connections and
   node-owned scientific storage. Do not infer hardware through discovery.
4. Configure key-based SSH/SFTP access and the StorageManager mapping from logical
   node identity to endpoint/authentication references. Verify connectivity,
   retrieve a small dummy file, and confirm retrieved bytes match the source.
   Required retrieval setup must succeed before the node is fully installed.
5. Add the identity to Controller's local known-node list and restart Controller
   to load it. Report duplicate identities as conflicts; do not launch against
   ambiguous identity. Coordinate restarts between Experiments without bypassing
   existing active-acquisition safeguards.
6. Start the selected services independently. Verify node NATS connectivity and
   Controller-to-node readiness request/response through existing communication.
   Historical announcements are not current readiness; missing replies mean
   unknown availability, not confirmed failure or stopped acquisition.
7. Strongly recommend a device-appropriate acquisition smoke check: communicate,
   acquire representative data, inspect output/local persistence, stop safely,
   release resources, and record results. This is not a mandatory runtime gate,
   commissioning certificate, or universal acquisition-test interface.

Installation changes require service restart; live reload/registration is not
required. AcquisitionNode startup supports both a default local configuration
location and an explicit path. Exact syntax, file format, and default location
remain ordinary implementation choices. Future setup utilities must use the same
runtime file-loading/validation mechanism; no interactive installer is required.

Valid configuration is not proof of hardware readiness. Invalid/missing node
configuration must diagnose the problem and prevent acquisition. Existing readiness
reports actual hardware/service conditions. StorageManager validates local retrieval
configuration at startup but checks node connectivity when retrieval is requested;
temporarily offline nodes do not block its startup. Installation checks do not
require continuously reachable SSH/SFTP during scientific Sessions. NATS connection
alone does not establish durable Ingestor acceptance or Q019 completeness.

## Current Reusable Interfaces And Gaps

| Boundary | Existing foundation | Missing integration |
| --- | --- | --- |
| Package/launch | `pyproject.toml` builds one `lab-sync-acquisition` package, Python 3.12, with optional `artifact-retrieval`; scripts demonstrate manual startup | General explicit-role entry point and supported configuration bootstrap |
| Local configuration | Constructors accept NATS servers, journals, storage roots, retrieval endpoints, and node declarations | File loader, templates/definitions, startup validation, default/explicit node paths |
| Node/device setup | `AcquisitionNode`, `DeviceDeclaration`, `DeviceManager`, concrete adapters and retained deployment device settings | File-to-object construction and explicit supported adapter selection |
| Operator parameters | `SessionConfig.device_configurations`, node initialization overrides, adapter `initialize(config)` and concrete validation | Generic adapter-defined parameter constraints, inventory exposure, Controller readback |
| Readiness/startup | Existing node/service reports, NATS `check_readiness`/`get_inventory`, fresh announcements, `Controller.reconcile_outcomes()` | Load known-node identities from local files and integrate configuration diagnostics |
| Scientific retrieval | `SshRetrievalEndpoint`, configured node-to-endpoint mapping, StorageManager SSH/SFTP pull with host-key checks | Startup-local endpoint validation and explicit verified installation dummy retrieval |

Current demos and optional manual hardware checks are not a general installer.
Concrete camera configuration is an adapter example, not the generic parameter
contract. No principal-service package split, registry, database, plugin framework,
GUI, supervision, automatic discovery, or new readiness state is needed here.

Controller archival/collection and maintenance preservation currently use actual
Ingestor/StorageManager collaborators, including synchronous owner guards; they
are not remote APIs merely because NATS participant commands exist. Decision 304
does not require one process per service. If separate-process launching is intended
for these collaborating owners, return the composition/access contract to LLC
before inventing proxies, distributed locking, or implicitly launching unselected
services. This interface gap does not change the accepted Q022-A decisions or
require a new subsystem for file loading, node inventory, or installation checks.

## Validation Boundaries

Future implementation needs focused software tests of configuration loading,
role selection, explicit identities/adapter construction, parameter constraints and
successive Session isolation, startup/readiness communication, and installation
dummy retrieval. Test invalid configuration, ambiguous known identities, offline
nodes, mismatched dummy contents, and failure diagnostics without manufacturing
scientific readiness or evidence acceptance.

Independent manual validation and source audit follow implementation under the
authoritative workflow. Real deployment/device validation remains separately
identified. Q019 is CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN. Historical
validated workflows and existing service ownership/safety contracts are unchanged.
