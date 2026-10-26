import { state } from './protocol-setup.js';
import { devices, operations } from './protocol-demo.mjs';
import { selectedStepContext } from './session-demo.mjs';
import { deviceExamples, experimentView, updateExperiment, saveExperimentTemplate } from './experiment-demo.mjs';
import { escapeText as escape, sessionIdentity, navigate } from './gui-presentation.js';

const panel = document.querySelector('#panel-parameters');
let message = '';

function parameterField(field, value) {
  const attributes = `data-example-value="${escape(field.id)}"`;
  if (field.type === 'select') return `<label>${escape(field.label)}<select ${attributes}>${field.options.map(option => `<option ${option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  if (field.type === 'checkbox') return `<label class="parameter-checkbox"><input type="checkbox" ${attributes} ${value ? 'checked' : ''}>${escape(field.label)}</label>`;
  return `<label>${escape(field.label)}<input type="${field.type}" ${attributes} value="${escape(value)}" min="${field.min}" max="${field.max}" step="any" required></label>`;
}

function renderParameters() {
  const { step, record } = selectedStepContext(state);
  if (!step || operations.find(operation => operation.id === step.operation)?.type !== 'Experiment') {
    panel.innerHTML = '<div class="context-empty"><h2 id="heading-parameters">Parameters</h2><p>Select an Experiment step in Session to inspect its configuration.</p><button type="button" data-return-session>Go to Session</button></div>';
    return;
  }
  const view = experimentView(state, step, record);
  const { configuration, readOnly } = view;
  const participants = devices.filter(device => configuration.participants.includes(device.id));
  panel.innerHTML = `<div class="view-heading"><div><p class="prototype-caption">Experiment selected in Session</p><h2 id="heading-parameters">${escape(step.name)} · Parameters</h2><p>${readOnly ? 'Executed demonstration configuration · read-only' : 'Working configuration · changes remain in page memory'}</p></div><button type="button" data-return-session>Return to Session</button></div>
    <p class="view-notice">Illustrative controls only — these are not authoritative SDK parameter definitions. Choose participating devices in Session; configure them here. No device communication or persistence. Template saving is optional.</p>
    <div class="parameter-toolbar"><button type="button" data-parameter-expand>Expand all</button><button type="button" data-parameter-collapse>Collapse all</button></div>
    <fieldset class="parameter-fields" id="parameter-fields" ${readOnly ? 'disabled' : ''}>
      <details class="parameter-section" open><summary>Experiment timing</summary><div class="parameter-section-body"><label>Planned duration (seconds)<input type="number" id="experiment-duration" value="${escape(configuration.durationSeconds)}" min="1" step="any" required></label><p>Explicit demonstration duration, not a real acquisition deadline.</p></div></details>
      ${participants.map(device => `<details class="parameter-section" open><summary>${escape(device.name)} <small>Illustrative settings</small></summary><div class="parameter-section-body">${(deviceExamples[device.id]?.fields || []).map(field => parameterField(field, configuration.values[field.id])).join('') || '<p>No example parameters supplied for this device.</p>'}</div></details>`).join('')}
    </fieldset>
    <section class="personal-template-area"><h3>Save as personal template <small>Optional</small></h3><p>A new name creates an independent Experiment template for ${escape(sessionIdentity().experimenter)}. Laboratory templates are never overwritten.</p><form id="personal-experiment-template"><label>New personal template name<input name="templateName" required ${readOnly ? 'disabled' : ''} placeholder="My baseline configuration"></label><button type="submit" ${readOnly ? 'disabled' : ''}>Save as personal template</button></form></section>
    <p id="parameter-feedback" role="status">${escape(message)}</p>`;
}

panel.addEventListener('click', event => {
  if (event.target.closest('[data-return-session]')) navigate('session');
  if (event.target.closest('[data-parameter-expand], [data-parameter-collapse]')) {
    const open = !!event.target.closest('[data-parameter-expand]');
    panel.querySelectorAll('.parameter-section').forEach(section => { section.open = open; });
  }
});
function updateParameterWorking(event) {
  const control = event.target;
  if (!control.matches('#experiment-duration, [data-example-value]')) return;
  const { step, record } = selectedStepContext(state);
  const view = experimentView(state, step, record);
  try {
    if (control.id === 'experiment-duration') updateExperiment(state, step, record, { durationSeconds: control.valueAsNumber });
    else if (control.dataset.exampleValue) updateExperiment(state, step, record, { values: { ...view.configuration.values, [control.dataset.exampleValue]: control.type === 'checkbox' ? control.checked : control.type === 'number' ? control.valueAsNumber : control.value } });
    message = 'Working values updated. Return to Session to inspect the summary or launch the simulation; no template save is required.';
  } catch (error) { message = error.message; }
  panel.querySelector('#parameter-feedback').textContent = message;
}
panel.addEventListener('input', updateParameterWorking);
panel.addEventListener('submit', event => {
  if (event.target.id !== 'personal-experiment-template') return;
  event.preventDefault();
  const invalid = [...panel.querySelectorAll('#parameter-fields input, #parameter-fields select')].find(control => !control.checkValidity());
  if (invalid) { invalid.reportValidity(); return; }
  const { step, record } = selectedStepContext(state);
  try {
    const template = saveExperimentTemplate(state, step, record, event.target.elements.templateName.value, sessionIdentity().owner);
    message = `Saved personal Experiment template “${template.name}” in page memory. No shared template or previous attempt changed.`;
  } catch (error) { message = error.message; }
  panel.querySelector('#parameter-feedback').textContent = message;
});
document.addEventListener('gui-section-changed', event => { if (event.detail === 'parameters') renderParameters(); });
renderParameters();
