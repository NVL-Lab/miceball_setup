import { state } from './protocol-setup.js';
import { devices, operations } from './protocol-demo.mjs';
import { selectedStepContext } from './session-demo.mjs';
import { deviceExamples, experimentView, updateExperiment, saveExperimentTemplate } from './experiment-demo.mjs';
import { escapeText as escape, executionIdentity, navigate } from './gui-presentation.js';
import { configurationNumber, scientificOutputIdentity } from './configuration-values.mjs';

const panel = document.querySelector('#panel-parameters');
let message = '';

function parameterField(field, value, present) {
  const attributes = `data-example-value="${escape(field.id)}"`;
  let control;
  if (field.type === 'select') control = `<label>${escape(field.label)}<select ${attributes}>${field.options.map(option => `<option ${option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  else if (field.type === 'checkbox') control = `<label class="parameter-checkbox"><input type="checkbox" ${attributes} ${value ? 'checked' : ''}>${escape(field.label)}</label>`;
  else control = `<label>${escape(field.label)}<input type="${escape(field.type)}" ${attributes} value="${escape(value ?? '')}" ${field.min !== undefined ? `min="${escape(field.min)}"` : ''} ${field.max !== undefined ? `max="${escape(field.max)}"` : ''} step="${field.integer ? '1' : 'any'}" ${state.connected || field.nullable ? '' : 'required'}></label>`;
  if (!state.connected) return control;
  return `<div class="parameter-override">${control}<div class="parameter-toolbar"><small>${present ? value === null ? 'Explicit null' : 'Explicit override' : 'No explicit override'}</small><button type="button" data-unset-parameter="${escape(field.id)}" ${present ? '' : 'disabled'}>Use default</button>${field.nullable ? `<button type="button" data-null-parameter="${escape(field.id)}">Set null</button>` : ''}</div></div>`;
}

export function renderParameters() {
  const { step, record } = selectedStepContext(state);
  if (!step || operations.find(operation => operation.id === step.operation)?.type !== 'Experiment') {
    panel.innerHTML = '<div class="context-empty"><h2 id="heading-parameters">Parameters</h2><p>Select an Experiment step in Session to inspect its configuration.</p><button type="button" data-return-session>Go to Session</button></div>';
    return;
  }
  const view = experimentView(state, step, record);
  const { configuration, readOnly } = view;
  const participants = devices.filter(device => configuration.participants.includes(device.id));
  panel.innerHTML = `<div class="view-heading"><div><p class="prototype-caption">Experiment selected in Session</p><h2 id="heading-parameters">${escape(step.name)} · Parameters</h2><p>${readOnly ? 'Executed configuration · read-only' : 'Working configuration · changes remain in page memory'}</p></div><button type="button" data-return-session>Return to Session</button></div>
    <p class="view-notice">${state.connected ? 'Supported adapter settings; unsent values remain local until Controller admission. Templates remain page-local.' : 'Illustrative controls only — these are not authoritative SDK parameter definitions. Choose participating devices in Session; configure them here. No device communication or persistence. Template saving is optional.'}</p>
    <div class="parameter-toolbar"><button type="button" data-parameter-expand>Expand all</button><button type="button" data-parameter-collapse>Collapse all</button></div>
    <fieldset class="parameter-fields" id="parameter-fields" ${readOnly ? 'disabled' : ''}>
      <details class="parameter-section" open><summary>Experiment timing</summary><div class="parameter-section-body"><label>Planned duration (seconds)<input type="number" id="experiment-duration" value="${escape(configuration.durationSeconds ?? '')}" min="1" step="any" required></label><p>${state.connected ? 'Requested autonomous acquisition duration.' : 'Explicit demonstration duration, not a real acquisition deadline.'}</p></div></details>
      ${participants.map(device => `<details class="parameter-section" open><summary>${escape(device.name)} <small>${state.connected ? 'Declared settings' : 'Illustrative settings'}</small></summary><div class="parameter-section-body">${(deviceExamples[device.id]?.fields || []).map(field => parameterField(field, configuration.values[field.id], Object.hasOwn(configuration.values, field.id))).join('') || '<p>No example parameters supplied for this device.</p>'}</div></details>`).join('')}
      ${state.connected ? `<details class="parameter-section" open><summary>Framework recording configuration</summary><div class="parameter-section-body"><label>Experiment ID<input data-framework-field="experimentId" value="${escape(configuration.experimentId || '')}" required></label><label>Preservation budget (bytes)<input type="number" min="1" step="1" data-framework-field="preservationBudget" value="${escape(configuration.preservationBudget ?? '')}" required></label>${[...new Set(participants.map(device => device.nodeId))].map(node => `<label>${escape(node)} recording budget (bytes)<input type="number" min="1" step="1" data-recording-budget="${escape(node)}" value="${escape(configuration.recordingBudgets?.[node] ?? '')}" required></label>`).join('')}<h4>Scientific outputs</h4>${participants.flatMap(device => (device.declaration?.scientific_products || []).map(product => { const output = {source_node_id: device.nodeId, source_device_id: device.deviceId, data_product_id: product.data_product_id}; return `<label class="parameter-checkbox"><input type="checkbox" data-scientific-output="${escape(JSON.stringify(output))}" ${configuration.outputs?.some(item => scientificOutputIdentity(item) === scientificOutputIdentity(output)) ? 'checked' : ''}>${escape(device.name)} / ${escape(product.data_product_id)}</label>`; })).join('') || '<p>No declared scientific products available.</p>'}</div></details>` : ''}
    </fieldset>
    <section class="personal-template-area"><h3>Save as personal template <small>Optional</small></h3><p>A new name creates an independent Experiment template for ${escape(executionIdentity(state).experimenter)}. Laboratory templates are never overwritten.</p><form id="personal-experiment-template"><label>New personal template name<input name="templateName" required ${readOnly ? 'disabled' : ''} placeholder="My baseline configuration"></label><button type="submit" ${readOnly ? 'disabled' : ''}>Save as personal template</button></form></section>
    <p id="parameter-feedback" role="status">${escape(message)}</p>`;
}

panel.addEventListener('click', event => {
  const override = event.target.closest('[data-unset-parameter], [data-null-parameter]');
  if (override) {
    const {step, record} = selectedStepContext(state);
    const values = {...experimentView(state, step, record).configuration.values};
    if (override.hasAttribute('data-unset-parameter')) delete values[override.dataset.unsetParameter];
    else values[override.dataset.nullParameter] = null;
    updateExperiment(state, step, record, {values}); renderParameters(); return;
  }
  if (event.target.closest('[data-return-session]')) navigate('session');
  if (event.target.closest('[data-parameter-expand], [data-parameter-collapse]')) {
    const open = !!event.target.closest('[data-parameter-expand]');
    panel.querySelectorAll('.parameter-section').forEach(section => { section.open = open; });
  }
});
function updateParameterWorking(event) {
  const control = event.target;
  if (!control.matches('#experiment-duration, [data-example-value], [data-framework-field], [data-recording-budget], [data-scientific-output]')) return;
  const { step, record } = selectedStepContext(state);
  const view = experimentView(state, step, record);
  try {
    const definition = control.dataset.exampleValue
      ? Object.values(deviceExamples).flatMap(device => device.fields).find(field => field.id === control.dataset.exampleValue) : null;
    let numeric = null, numericError = null;
    if (control.type === 'number' && control.validity.badInput) {
      numeric = 'Invalid numeric input';
      numericError = new Error('Invalid numeric input. Enter a finite value representable by this GUI.');
    } else if (control.type === 'number' && control.value !== '') {
      const integer = Boolean(definition?.integer || control.dataset.recordingBudget || control.dataset.frameworkField === 'preservationBudget');
      try { numeric = configurationNumber(control.value, integer); }
      catch (error) { numeric = control.value; numericError = error; }
    }
    if (control.id === 'experiment-duration') updateExperiment(state, step, record, { durationSeconds: numeric });
    else if (control.dataset.frameworkField) updateExperiment(state, step, record, { [control.dataset.frameworkField]: control.type === 'number' ? numeric : control.value });
    else if (control.dataset.recordingBudget) updateExperiment(state, step, record, { recordingBudgets: { ...view.configuration.recordingBudgets, [control.dataset.recordingBudget]: numeric } });
    else if (control.dataset.scientificOutput) {
      const output = JSON.parse(control.dataset.scientificOutput);
      const outputs = view.configuration.outputs.filter(item => scientificOutputIdentity(item) !== scientificOutputIdentity(output));
      if (control.checked) outputs.push(output);
      updateExperiment(state, step, record, { outputs });
    }
    else if (control.dataset.exampleValue) {
      const values = { ...view.configuration.values };
      if (state.connected && control.type === 'number' && control.value === '' && !definition?.nullable && !numericError) delete values[control.dataset.exampleValue];
      else values[control.dataset.exampleValue] = control.type === 'checkbox' ? control.checked : control.type === 'number' ? numeric : control.value;
      updateExperiment(state, step, record, { values });
      if (state.connected) {
        const toolbar = control.closest('label').nextElementSibling;
        toolbar.querySelector('small').textContent = Object.hasOwn(values, control.dataset.exampleValue) ? values[control.dataset.exampleValue] === null ? 'Explicit null' : 'Explicit override' : 'No explicit override';
        toolbar.querySelector('[data-unset-parameter]').disabled = !Object.hasOwn(values, control.dataset.exampleValue);
      }
    }
    message = numericError?.message || (state.connected ? 'Unsent working values updated. Controller validates the submitted configuration.' : 'Working values updated. Return to Session to inspect the summary or launch the simulation; no template save is required.');
    state.actions.syncControls?.();
  } catch (error) { message = error.message; }
  panel.querySelector('#parameter-feedback').textContent = message;
}
panel.addEventListener('input', updateParameterWorking);
panel.addEventListener('change', event => { if (event.target.type === 'checkbox' || event.target.tagName === 'SELECT') updateParameterWorking(event); });
panel.addEventListener('submit', event => {
  if (event.target.id !== 'personal-experiment-template') return;
  event.preventDefault();
  const invalid = [...panel.querySelectorAll('#parameter-fields input, #parameter-fields select')].find(control => !control.checkValidity());
  if (invalid) { invalid.reportValidity(); return; }
  const { step, record } = selectedStepContext(state);
  try {
    const template = saveExperimentTemplate(state, step, record, event.target.elements.templateName.value, executionIdentity(state).owner);
    message = `Saved personal Experiment template “${template.name}” in page memory. No shared template or previous attempt changed.`;
  } catch (error) { message = error.message; }
  panel.querySelector('#parameter-feedback').textContent = message;
});
document.addEventListener('gui-section-changed', event => { if (event.detail === 'parameters') renderParameters(); });
renderParameters();
