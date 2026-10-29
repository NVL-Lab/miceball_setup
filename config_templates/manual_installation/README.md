# Manual Installation Examples

These are editable examples, not runnable laboratory configuration, credentials,
an installer or an installation certificate. Follow the
[manual runbook](../../docs/installation_and_deployment.md#manual-installation-runbook-w067-closed).
Copy needed files outside Git and replace every uppercase placeholder there.
No environment-variable substitution is performed by the loaders.

All participating service files require the shared installation's explicit
`controller_claim_account`, `controller_claim_bucket` and `controller_claim_key`.
An operator must provision and verify the persistent, non-expiring authority
bucket first. Runtime startup never creates missing authority storage. See the
runbook's Controller claim section for account verification, durability
prerequisites and crash-retention limitations; the examples provision none of them.

| File | Computer / selected CLI role |
| --- | --- |
| `controller.json` | Controller / `controller` |
| `synchronization-manager.json` | SynchronizationManager / `synchronization-manager` |
| `acquisition-node-service.json` | Each AcquisitionNode / `acquisition-node` |
| `acquisition-node.json` | Separate node hardware file referenced by its service file |
| `storage-services.json` | Shared Ingestor/StorageManager computer / either storage role |

The storage example explicitly lists the Controller, SynchronizationManager and
node as external dependents. Keep this list consistent with the actual deployment;
it is not inferred from traffic or Controller registration. W068 composes existing
maintenance callbacks from these identities and requires positive `result_window_s`
for current confirmation. W068 is CLOSED after independent manual validation and
final audit PASS, including ordinary archive continuation and the maintenance-write
guard correction; see W068 in `docs/validated_workflows.md`.
For a genuinely isolated pair only, remove `external_dependents` (retain `result_window_s` for authority requests)
and use `no_operational_dependents: true`; never combine the modes or falsely declare
absence of dependents. `verify-retrieval` can read the endpoint settings without
launching the pair. Complete physical distributed deployment remains unverified.

Identity placeholders must agree across files: the node's `node_id`, Controller
`known_nodes` entry and StorageManager endpoint key refer to the same persistent
identity. Device identity and product identity are separate. Add distinct nodes
with distinct files/identities; never start two processes with the same identity.

The 30-second preservation window and 10-second result window are illustrative
explicit settings, not recommended timing guarantees or hidden runtime defaults.
Choose appropriate values for the installation. They do not configure scientific
synchronization accuracy, cadence or Session timing policy.

The camera example is the currently supported file-loader adapter, not a universal
device model. Replace the source path, OpenCV backend number (0 is the illustrative
automatic-backend selection), frame dimensions, shape, dtype and collection count
with explicitly verified device settings. A requested resolution is not proof the
backend delivers it. Declaring `frames` makes it available; an Experiment must
explicitly select it before scientific recording. No Session configuration is
included here.

General-service relative paths resolve beside their service JSON. Scientific/error
paths in the hardware file resolve beside that hardware file. Prefer operator-chosen
absolute paths for a real installation. The private key and known-host references
must exist locally on the StorageManager computer before validation. No key bytes,
hosts, accounts or directories are provisioned by these examples.
