import { state } from './protocol-setup.js';
import { devices } from './protocol-demo.mjs';
import { activeParameterSnapshot } from './experiment-parameters.mjs';
import { deviceExamples } from './experiment-demo.mjs';
import { escapeText as escape } from './gui-presentation.js';
import { formatCalendarDate } from './calendar-date.mjs';

const setup = document.querySelector('#panel-setup');
const toolbar = document.createElement('div');
toolbar.className = 'setup-disclosures-toolbar';
toolbar.innerHTML = '<button type="button" data-open-setup>Expand All</button><button type="button" data-close-setup>Collapse All</button>';
setup.querySelector('.setup-demo-note').after(toolbar);
for (const card of setup.querySelectorAll('.setup-card')) {
  const heading = card.querySelector('h3');
  if (!heading) continue;
  const disclosure = document.createElement('details'); disclosure.className = 'setup-disclosure'; disclosure.open = true;
  const summary = document.createElement('summary'); summary.append(heading); disclosure.append(summary);
  const body = document.createElement('div'); body.className = 'setup-disclosure-body';
  for (const child of [...card.childNodes]) body.append(child);
  disclosure.append(body); card.append(disclosure);
}
toolbar.addEventListener('click', event => {
  if (!event.target.closest('button')) return;
  setup.querySelectorAll('.setup-disclosure').forEach(section => { section.open = !!event.target.closest('[data-open-setup]'); });
});

// Keep the native calendar picker and ISO input value; display the owner's canonical format alongside it.
function attachDateReadout(input) {
  if (input.dataset.canonicalDate) return;
  input.dataset.canonicalDate = 'true';
  const output = document.createElement('small'); output.className = 'calendar-date-readout';
  output.setAttribute('aria-live', 'polite'); input.after(output);
  const update = () => { output.textContent = `YYYYMMDD: ${formatCalendarDate(input.value) || 'Not set'}`; };
  input.addEventListener('input', update); input.addEventListener('change', update); update();
}
setup.querySelectorAll('input[type="date"]').forEach(attachDateReadout);
const catalogFields = document.querySelector('#catalog-fields');
new MutationObserver(() => catalogFields.querySelectorAll('input[name="date_of_birth"]').forEach(attachDateReadout))
  .observe(catalogFields, { childList: true });

const experiment = document.querySelector('#panel-experiment');
let drawerOpen = false;
function renderDrawer() {
  const heading = experiment.querySelector('.view-heading');
  if (!heading) return;
  let actions = heading.querySelector('.experiment-heading-actions');
  if (!actions) {
    actions = document.createElement('div'); actions.className = 'experiment-heading-actions';
    const back = heading.querySelector('[data-science-session]');
    if (back) actions.append(back);
    heading.append(actions);
  }
  let button = actions.querySelector('[data-show-experiment-parameters]');
  if (!button) {
    button = document.createElement('button'); button.type = 'button'; button.dataset.showExperimentParameters = '';
    button.setAttribute('aria-controls', 'experiment-parameters-drawer'); actions.append(button);
    button.addEventListener('click', () => { drawerOpen = !drawerOpen; renderDrawer(); });
  }
  button.textContent = drawerOpen ? 'Hide Parameters' : 'Show Parameters'; button.setAttribute('aria-expanded', String(drawerOpen));
  let drawer = experiment.querySelector('#experiment-parameters-drawer');
  if (!drawer) { drawer = document.createElement('aside'); drawer.id = 'experiment-parameters-drawer'; drawer.className = 'experiment-parameter-drawer setup-card'; drawer.setAttribute('aria-label', 'Read-only Experiment parameters'); experiment.append(drawer); }
  const snapshot = activeParameterSnapshot(state);
  drawer.innerHTML = snapshot ? `<h3>Parameters · ${escape(snapshot.name)}</h3><p class="prototype-caption">${escape(snapshot.source)} · read-only browser demonstration</p><dl><dt>Planned duration (seconds)</dt><dd>${escape(snapshot.configuration.durationSeconds ?? 'Unavailable')}</dd>${snapshot.configuration.participants.map(id => `<dt>${escape(devices.find(device => device.id === id)?.name || id)}</dt><dd>${(deviceExamples[id]?.fields || []).map(field => `${escape(field.label)}: ${escape(snapshot.configuration.values[field.id] ?? 'Unavailable')}`).join('<br>') || 'No parameter definitions available for this device.'}</dd>`).join('')}</dl>` : '<h3>Experiment Parameters</h3><p>No prepared or executed parameter configuration is available for this scientific step in an active Session. No defaults are invented.</p>';
  drawer.hidden = !drawerOpen; experiment.classList.toggle('has-parameters-drawer', drawerOpen);
}
document.addEventListener('gui-section-changed', event => { if (event.detail === 'experiment') renderDrawer(); });
renderDrawer();