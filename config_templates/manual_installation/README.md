# Manual Installation Examples

These are editable examples, not runnable laboratory configuration, credentials,
an installer or an installation certificate. Follow the
[manual runbook](../../docs/installation_and_deployment.md#manual-installation-runbook-w067-closed).
Copy needed files outside Git and replace every uppercase placeholder there.
No environment-variable substitution is performed by the loaders.

| File | Computer / selected CLI role |
| --- | --- |
| `controller.json` | Controller / `controller` |
| `synchronization-manager.json` | SynchronizationManager / `synchronization-manager` |
| `acquisition-node-service.json` | Each AcquisitionNode / `acquisition-node` |
| `acquisition-node.json` | Separate node hardware file referenced by its service file |
| `storage-services.json` | Shared Ingestor/StorageManager computer / either storage role |

The storage example's `no_operational_dependents: true` is valid **only for an
isolated pair with no external operational dependents**. Do not use it to launch
a pair serving Controller, SynchronizationManager or nodes that depend on it.
The existing file launcher cannot compose their required maintenance callbacks;
this is an outstanding deployment integration gap, not permission to omit them.
`verify-retrieval` can read the endpoint settings without launching the pair or
evaluating this declaration. No complete distributed launch is claimed here.

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
