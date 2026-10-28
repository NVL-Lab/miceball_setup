# Miceball GUI

This separately packaged browser interface is a demonstration with fictional
Setup information, a Protocol Editor, and seven permanent sections. It runs entirely
in the browser. Launch Session and other operational-looking controls do not
start or contact scientific framework services or execute scientific algorithms.

## Local preview

From the repository root:

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory gui/src/miceball_gui/static
```

Then open <http://127.0.0.1:8000/>.

## Storage preview (Slice 7)

Permanent navigation is Setup, Session, Parameters, Experiment, Analysis, Storage,
Services. Storage has Collection, Delete originals and History workspaces. All
Session records shown there are labeled fictional browser-local fixtures; nothing
is retrieved from the framework or persisted by Storage.

Add or drag whole Sessions into the collection bucket, remove them, or use Collect
everything pending. Store reviews the complete selection and the unchecked
conditional-original-deletion option; proceeding reports that integration is
unavailable, not successful preservation. Transfer, verification and durable
preservation are distinct. Unknown counts, sizes, capacity and progress remain
unavailable rather than estimated.

Delete originals independently selects Experiments or all Experiments of a Session,
including original scientific timing/index files on AcquisitionNodes. It never
selects individual recordings or removes StorageManager/global copies, historical
metadata or evidence. Manual deletion can be reviewed before or after collection.
Every review requires confirmation; missing verified copies or incomplete/uncertain
collection additionally requires the loss-risk acknowledgment. Cancel, Escape and
backdrop dismissal do nothing. Proceeding sends no request and deletes no files.
Red is confined to deletion controls/warnings in Storage; ordinary uncertainty is
amber or neutral in both themes.

History defaults to unresolved/pending/active/failed/incomplete entries plus
successful collections completed within 30 days, independently of recording date.
Search or Include older successful collections exposes older successes. Fields
search Session identity, experimenter, project, animal and recording/collection
dates. Real historical queries and capacity readback remain unavailable.

The Setup experimenter selection filters fixtures by recorded owner. Existing
Services administrator mode (with its Danger Zone confirmation) shows all fixture
Sessions; returning to Experimenter mode restores filtering. This is presentation,
not backend authorization. Controller-mediated readback/requests, authoritative
access enforcement, exact target resolution, local safety/durable deletion records
and evidence preservation remain framework integration dependencies under Q034.
The existing Q034 backend interfaces are not connected by this visual slice;
their software validation does not establish GUI integration or deployment.

Focused Storage/navigation checks:

```powershell
node --test gui/tests/test_storage_demo.mjs gui/tests/test_navigation_menu.mjs
python -B -m unittest discover -s gui/tests -p test_gui_shell.py -v
```

## Checks

```powershell
python -m unittest discover -s gui/tests -v
node --check gui/src/miceball_gui/static/app.js
node --test gui/tests/test_protocol_demo.mjs
```

Setup includes a fictional CaBMI protocol, protocol-filtered templates, optional
Session steps, independent device selection and declared-capability coverage.
New/Edit/Copy opens the temporary Option A Protocol Editor. Saved demonstration
protocols and unsaved drafts remain only in page memory; refreshing resets them.
Coverage and the sample connection labels do not constitute runtime readiness.

Protocol steps can be reordered with their six-dot handles or the Move Up / Move
Down buttons. Reordering keeps the selected step and its configuration together;
Save applies the order to Setup and Cancel discards the draft after confirmation.
Required and optional capabilities use multi-selection dropdowns with removable
chips. Assigning a capability to either list removes it from the other list.
Saved reusable steps (shared or personal) are read-only. Use **Copy to edit** or
choose **Blank step** in the existing Add step selector. **Save as reusable step**
explicitly saves a uniquely named personal definition for the selected demonstration
experimenter; Save Protocol does not implicitly add definitions to that selector.
Repeated occurrences keep independent identities and refer to the same definition.
Reusable saves survive cancelling a protocol draft, but all demonstration records
reset on refresh. Protocol Save/Cancel actions are at the editor's bottom-right.
Optional capabilities show selected-device coverage separately in Setup; enabling them for an
individual Session is not implemented in this demonstration.

## Session preview

Session reads the selected protocol, Session identity and device declarations from
Setup. It shows a scrollable step list and selected-step information, simulated
readiness, state-dependent demonstration actions, output summaries and history.
The first two included steps have explicitly illustrative existing results.
Run/Repeat starts an indeterminate simulation; Complete simulation or Simulate
error ends it. No acquisition, computation, file loading or framework commands occur.

Completing, repeating or loading a replacement result for an earlier step marks
later completed mock results Needs review without
removing them. Validate existing result confirms only the local example. This is
a design proposal, not accepted framework dependency policy or Controller acceptance.
Previous-result examples are offered only for the illustrative ROI/calibration
operations; optional steps can be skipped locally. View parameters and the contextual
workspace buttons navigate to the corresponding full-width views. Progress/results/
history reset on refresh. Switching tabs does not stop the local simulation.

Experiment steps show balanced template/current-configuration cards and a working
parameter summary. Capability-grouped checkboxes in Session select participating
Setup devices, allowing multiple providers and one consistent state per physical
device. Missing required coverage blocks simulated launch; unused optional
capabilities do not. Template loading confirms replacement of modified working
values. Retained results/history remain accessible without empty Experiment cards.
View / Edit Parameters opens contextual collapsible timing and participating-device
settings with fictional control definitions, plus Expand all /
Collapse all and optional Save as personal template. There is no step selector in
Parameters, and no device-participation controls there. Edits survive navigation without requiring a template save. Launch
Experiment exists only in Session and is explicitly simulated. It checks example
duration, participant inclusion/availability, acquisition-device presence and exact
declared capability coverage, not real Controller readiness or storage capacity.
Running/completed mock configurations are read-only; Prepare repeat makes a new
working copy while retaining previous immutable attempt configurations.

Experiment shows information and a fixed synthetic image on the left and two plots
on the right. Analysis uses a 2×2 grid of illustrative traces, image/selection,
metrics/table and distribution outputs. Neither calculates scientific results.
Each output panel supports Expand/Restore and Escape within the workspace, without
browser fullscreen or replacing the panel contents. Legend choices and example ROI
selection survive expansion and tab navigation. Dark mode changes plot presentation,
not image content or underlying data. No live streams are implemented. All records
remain page-local; only the existing theme preference persists in browser storage.

Only a running example shows the red **Stop Experiment** button in Experiment,
not Session. It starts a pending Normal Stop preview; **Complete stop simulation**
explicitly finishes the local scenario using the existing mock completion path.
This is not Kill and confirms no real distributed cleanup or preservation. Earlier
results, immutable attempt configurations and output-panel state are retained.

## Services and Session closeout previews

Services presents six fictional configured services in compact wrapping rows,
inline expandable status/dependency/history details, per-service readiness-check
affordances and warning history showing the latest three entries by default, with
Show more / Show less expanding within normal page flow (no nested scrolling).
The standalone obligations, startup-guidance and readiness panels are removed;
accepted functional requirements and obligation fixtures remain unchanged.
The existing bottom-left indicator and Services
share acknowledgment state: acknowledgment removes the current alert but retains
its historical entry. Restore demonstration resets those local acknowledgments.
All fixture reports and history reset on refresh; there is no notification database.
Ten older acknowledged fixtures exercise scrolling without changing the original
three active notifications. History expansion survives acknowledgment and repaint.

Automatic refresh defaults to 10 seconds (configurable or Off), repaints only while
Services is visible and idle, and never advances a fixture's confirmation timestamp
or promotes unknown/stale reports to readiness. Manual checks send no commands.
Services start independently; no process launch, live polling or discovery exists.

Administrative controls are **hidden** in Experimenter mode (Decision 415).
Entering Administrator mode requires Danger Zone confirmation; returning is immediate.
This is a trust-based presentation safeguard, not authentication. Each administrative
affordance opens a scope/risk/limitation preview only. Execution remains unavailable
because service authorization, prerequisites and supported recovery contracts are
not connected. No shutdown, service Kill, recovery or abandonment is performed.

Session has a prominent red Stop Session button beneath its protocol list. The
ordinary GUI has no outcome selector; it uses a fixed browser-local blocker example.
Other outcome branches remain covered by model tests. Only the reported-blocker modal offers a Kill
preview, with a second forced-termination warning. Cancel/Escape leave the demo run
unchanged. Unknown results never authorize Kill. These dialogs do not stop a real
Session, mutate operation results, or claim real cleanup/preservation. They are
distinct from Stop Experiment and service-level administration.

Click a service row (or press Enter/Space) to expand its details inline. Administrator
mode adds Stop Service, recovery-availability and abandonment-review controls there,
plus a separate Shutdown Framework action below warning history. Stop previews require
confirmation, show pending progress, and then explicit fictional reports. Only a
reported blocked participant exposes Kill; each Kill needs a target-specific risk
warning and authorization checkbox. Forced outcomes remain unconfirmed, not success.
Fixtures never mutate live service reports or obligations. Framework participants'
outcomes are retained separately; no whole-framework completion is inferred.

Every configured service uses the same explicit blocked-stop presentation scenario;
service identity no longer selects the outcome or Kill eligibility. Model tests pass
completed, failed and unknown reports for every service without an ordinary GUI
fixture selector. Decision 315 permits forced continuation of a retained blocked
attempt, not a new Kill after an arbitrary terminal failed attempt. Failed examples
explain this limitation and require service-owned assessment/manual intervention.

Independent individual service maintenance is accepted in Decision 314 and implemented
by the existing service-owned maintenance interface, not necessarily Controller
orchestration. This demo does not connect that interface or establish the GUI transport,
authorization or readback contracts. It does not simulate actual dependency ordering,
restart, supported recovery execution or preservation confirmation.

## GitHub Pages demonstration

The intended public URL is <https://nvl-lab.github.io/miceball_setup/>. The workflow
is prepared locally; adding it does not enable Pages or establish a live deployment.
This project site belongs to `NVL-Lab/miceball_setup` and is independent of the
organization homepage in `NVL-Lab/NVL-Lab.github.io`. No homepage repository,
custom domain, DNS setting, or separate deployment branch is involved.

After owner review, approved changes are committed and pushed through the normal
project workflow. `.github/workflows/deploy-gui-pages.yml` runs on pushes to `main`
that change any of:

- `gui/src/miceball_gui/static/**`
- `gui/tests/**`
- `.github/workflows/deploy-gui-pages.yml`

It runs the existing GUI-only Python and Node tests and JavaScript syntax checks,
then uses GitHub's `configure-pages`, `upload-pages-artifact` and `deploy-pages`
actions. There is no build or dependency-installation step. Only the contents of
`gui/src/miceball_gui/static/` are uploaded, with `index.html` at the artifact root;
framework sources, configuration, tests, and data are outside that artifact.
Relative asset URLs and module imports support the `/miceball_setup/` project path.

### One-time owner settings

Configure these only in **NVL-Lab/miceball_setup**, after approval:

1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   Leave the custom-domain field empty. The workflow intentionally does not enable
   Pages automatically.
2. Check **Settings → Actions → General** allows the workflow and the official
   GitHub `actions/*` used by it. Organization policies must allow its requested
   `contents: read`, `pages: write`, and `id-token: write` job permissions.
   No personal access token or repository secret is needed.
3. Check the `github-pages` environment permits deployment from `main`. If required
   reviewers are configured, the owner must approve each pending deployment.
   The workflow itself rejects other branches and repositories.

Do not change the organization homepage's Pages settings or workflows.

### Manual deployment and published-version checks

After the reviewed workflow exists on `main`, open **Actions → Deploy GUI demo to
GitHub Pages → Run workflow**, select **main**, and run it. Manual runs from other
branches are skipped. An initial manual run can publish the site after enabling
Pages if no subsequent relevant push has triggered the workflow.

Inspect the run's test, upload, and deployment steps, its `github-pages` environment
link, and **Settings → Pages** for the published URL. A successful local check is
not confirmation of a successful public deployment.

To verify the version, match the successful deployment run's commit SHA against
the reviewed `main` commit. Hard-refresh the public URL and check the changed
feature. In browser developer tools, confirm the CSS, JavaScript and `.mjs` module
load successfully from `/miceball_setup/`, with no console errors or backend
requests. Check all six sections, Protocol Editor, and theme switching. The URL
stays the same across deployments while the repository name/domain stays the same.

Protocol edits, acknowledgments and catalog examples remain page-local and reset
on refresh. Only the theme preference uses browser-local storage, per origin; it
is not a framework record. GitHub Pages does not host an operational GUI backend.

### Active Session demonstration

**Navigation:** Use the top-left logo button (**Open navigation**) to expand the
unpinned menu. Selecting a tab closes it; hover/focus does not reopen it. The same
toggle, clicking outside, or Escape dismisses it. Pinning retains the expanded
workspace layout; the toggle can unpin and close it. Existing keyboard navigation
among tabs is preserved.

**Operation categories:** Session reports the available application definitions
for Experiment, Analysis, scientific Validation and operator interaction. The last
two remain unpopulated: no procedures, bounds, decisions or acknowledgment/outcome
fixtures have been supplied. Slice 6 adds no scientific examples or execution
semantics for them. This is deferred application work, not an architectural blocker.

**Device Validation:** Before Session launch, enter a positive **Device Validation
maximum (seconds)** in Setup. No default is assumed. This field is needed only
for Validation; a missing value does not prevent normal Session/Experiment demos.
The captured limit cannot be changed by editing future Setup preparation.

In Session, participating Experiment devices have **Validate** controls even when
their configuration is read-only. Validate opens the separate Device Validation
view in Experiment. **Stop Validation** immediately returns to normal monitoring,
without Session/Experiment Stop confirmation or history. The configured maximum
also ends the demonstration and reports its reason. Camera and position examples
reuse fixed synthetic output with an elapsed/update counter; water-delivery
actuators need only status. All activity is simulated; no physical actions occur.

Unavailable/unsupported cases or unverified concurrent device use show an
explanation rather than simulated activation. Stop a running device's activity
before trying the conflicting demo. These are not real authorization/readiness
decisions. Browser clocks can be throttled or suspended, so this timer is not a
hardware safety mechanism. Real activation, device ownership/compatibility,
autonomous deadline enforcement, cleanup and evidence remain future integration.
Device Validation does not count as a scientific Validation operation or alter
protocol/Free Mode history, configurations, results or recorded inputs.

Run focused checks with `node --test gui/tests/test_device_validation.mjs`.

**Previous recordings:** ROI identification and cursor calibration offer **Load
previous recording**, alongside their normal execution action. These are the
existing Analysis fixtures with recorded-input support; other operations do not
gain inferred support. Choose a file or, in supporting browsers, a nonempty folder
from any accessible Session/project. **Use selection** stages metadata only.
Choose an explicitly labeled simulated acceptance/rejection afterward; selecting
a file alone never satisfies the occurrence. Acceptance shows **Satisfied using
previous recording**, not new execution or acquisition. Prior results and input
decisions remain in history. Cancel/Escape preserves the old selection and adds
no history. Clear selection removes the staged input, not earlier decisions.

Only browser-provided names, relative paths (when available), sizes and timestamps
are retained in page memory. No absolute path, content reading, upload, import,
scientific suitability check or processing is performed. Folder support and empty
folder selection depend on the browser. Reload discards selection metadata.
Run focused checks with `node --test gui/tests/test_recording_selection.mjs`.

Choose an existing protocol for Protocol Mode or **None — Free Mode** before
launch. None is stored as an absent protocol (`null` in this JavaScript demo),
without creating a protocol definition. In Free Mode, use **Prepare operation**
in Session to choose from the existing Experiment/Analysis fixtures. Configure
Experiments in Parameters and launch them explicitly from Session. Operation
history retains separate occurrences, attempts and results; there is no required
next step or protocol-completion condition. Missing capabilities disable choices;
compatible does not mean ready. Both modes retain the launched physical device
pool despite subsequent Setup edits, and use the same Stop confirmations.

Run Free Mode model regressions with `node --test gui/tests/test_free_mode.mjs`.

Animal selections now restore their own summary metadata, including newly created
examples, in page memory only. Reload discards added animals. Setup animal changes
after launch do not change the active Session's captured animal identity.

Both Stop controls first require **Confirm Stop**. **Keep Running** or Escape
dismisses the dialog without starting any Stop or adding execution history.
After confirmation, the existing Stop/blocked-Stop/Kill previews are unchanged.

Setup's **Launch Session** captures a fixed browser-memory Session context and
opens Session; it does not start an Experiment. Subsequent Setup edits prepare a
future Session without changing the active procedure, identity, included steps or
device pool. Session, Parameters and Experiment use that captured context.
Existing illustrative results remain explicitly fictional. Finish any running
pre-launch preview before launching. Only one active demonstration Session is
supported; reload resets it. No Controller acceptance, reservations or durable
Session persistence are simulated by launch.

Run the focused active-context checks with
`node --test gui/tests/test_active_session.mjs` from the repository root.
