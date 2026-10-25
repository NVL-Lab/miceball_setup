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
