import { devices } from './protocol-demo.mjs';
import { activeParameterSnapshot } from './experiment-parameters.mjs';
import { deviceExamples } from './experiment-demo.mjs';
import { escapeText as escape } from './gui-presentation.js';
export function createExperimentParameterDrawer(experiment, state) {
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
  return renderDrawer;
}
