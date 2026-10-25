# Miceball GUI

This separately packaged browser interface is currently presentation-only: it
provides the application shell and six placeholder workspaces, with no framework
connection or scientific behavior.

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
Optional capabilities are displayed separately in Setup; enabling them for an
individual Session is not implemented in this demonstration.
