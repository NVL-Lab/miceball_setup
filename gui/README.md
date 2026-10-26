# Miceball GUI

This separately packaged browser interface is a demonstration with fictional
Setup information, a Protocol Editor, and six permanent sections. It runs entirely
in the browser. Launch Session and other operational-looking controls do not
start or contact scientific framework services or execute scientific algorithms.

## Local preview

From the repository root:

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory gui/src/miceball_gui/static
```

Then open <http://127.0.0.1:8000/>.

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
