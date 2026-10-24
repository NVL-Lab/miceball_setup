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
```
