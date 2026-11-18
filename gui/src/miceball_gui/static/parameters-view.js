import { state } from './protocol-setup.js';
import { devices, operations } from './protocol-demo.mjs';
import { deviceExamples, saveExperimentTemplate } from './experiment-demo.mjs';
import { escapeText as escape, executionIdentity, navigate, configurationStringEditor, readConfigurationString } from './gui-presentation.js';
import { configurationNumber, scientificOutputIdentity, configurationStringText, parseConfigurationString } from './configuration-values.mjs';
import { clone } from './protocol-demo.mjs';
import { catalogClient, putCatalog } from './catalog-client.mjs';
import { resolveParameterContext } from './parameter-context.mjs';
import { parameterIssue } from './parameter-constraints.mjs';
import { recordInvalidControl } from './activity-history.mjs';

const panel = document.querySelector('#panel-parameters');
panel.addEventListener('invalid', event => recordInvalidControl(event.target.closest('#personal-experiment-template') ? 'save_catalog' : 'validate_parameters', event.target), true);
panel.addEventListener('focusout', event => {
  if (event.target.matches('#parameter-fields input, #parameter-fields select, #parameter-fields textarea')) recordInvalidControl('validate_parameters', event.target);
});
let message = '';

function stringField(attributes, value) {
  return `<textarea ${attributes} data-string-value ${value?.invalidString !== undefined ? 'data-invalid-string' : ''} rows="1">${escape(configurationStringText(value))}</textarea>`;
}

function parameterField(field, value, present) {
  const attributes = `data-example-value="${escape(field.id)}" aria-label="${escape(field.label)}"`;
  let control;
  const undeclaredChoice = field.allowedValues && present && value !== null && !field.allowedValues.includes(value);
  if (field.allowedValues) control = `<label>${escape(field.label)}<select ${attributes}><option value="" ${!present || value === null ? 'selected' : ''}>${value === null && present ? 'Explicit null' : 'Use configured default'}</option>${undeclaredChoice ? `<option value="__current__" selected disabled>${escape(configurationStringText(value))} · not in current declared choices</option>` : ''}${field.allowedValues.map((option, index) => `<option value="${index}" ${present && option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  else if (field.type === 'select') control = `<label>${escape(field.label)}<select ${attributes}>${field.options.map(option => `<option ${option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  else if (field.type === 'checkbox') control = `<label class="parameter-checkbox"><input type="checkbox" ${attributes} ${value ? 'checked' : ''}>${escape(field.label)}</label>`;
  else if (state.connected && field.type === 'text') control = `<label>${escape(field.label)}${stringField(attributes, value)}</label>`;
  else control = `<label>${escape(field.label)}<input type="${escape(field.type)}" ${attributes} value="${escape(value ?? '')}" ${field.min !== undefined ? `min="${escape(field.min)}"` : ''} ${field.max !== undefined ? `max="${escape(field.max)}"` : ''} step="${field.integer ? '1' : 'any'}" ${state.connected || field.nullable ? '' : 'required'}></label>`;
  if (!state.connected) return control;
  return `<div class="parameter-override">${control}<div class="parameter-toolbar"><small>${present ? value === null ? 'Explicit null' : 'Explicit override' : 'Use configured default'}</small><button type="button" data-unset-parameter="${escape(field.id)}" ${present ? '' : 'disabled'}>Use configured default</button>${field.nullable ? `<button type="button" data-null-parameter="${escape(field.id)}">Set null</button>` : ''}</div></div>`;
}

export function renderParameters() {
  const context = resolveParameterContext(state);
  if (!context) {
    panel.innerHTML = '<div class="context-empty"><h2 class="visually-hidden" id="heading-parameters">Parameters</h2><p>No supported parameter configuration is available in this context. Select an Experiment operation in Setup or Session. Saved Steps without explicit settings must be copied in Protocol Editor before editing.</p><button type="button" data-return-session>Return</button></div>';
    return;
  }
  const {step, record} = context;
  const view = context;
  const { configuration, readOnly } = view;
  const participants = devices.filter(device => configuration.participants.includes(device.id));
  panel.innerHTML = `<div class="view-heading"><div><p class="prototype-caption">${escape(context.source)}</p><h2 class="visually-hidden" id="heading-parameters">Parameters</h2><h3>${escape(step.name)}</h3><p>${readOnly ? 'Read-only configuration' : 'Working configuration · not Controller acceptance'}</p></div><button type="button" data-return-session>Return to ${escape(context.origin === 'protocol-editor' ? 'Protocol Editor' : context.origin)}</button></div>
    <p class="view-notice">${state.connected ? 'Unsent working values; Controller confirms execution.' : 'Illustrative controls only — these are not authoritative SDK parameter definitions. Choose participating devices in Session; configure them here. No device communication or persistence. Template saving is optional.'}</p>
    <div class="parameter-toolbar"><button type="button" data-parameter-expand>Expand all</button><button type="button" data-parameter-collapse>Collapse all</button></div>
    ${!['session', 'experiment'].includes(context.kind) ? `<div class="parameter-toolbar">${[...new Set([...context.devices, ...configuration.participants])].map(id => ({id, name: devices.find(device => device.id === id)?.name || id})).map(device => `<label><input type="checkbox" data-parameter-participant="${escape(device.id)}" ${configuration.participants.includes(device.id) ? 'checked' : ''} ${readOnly ? 'disabled' : ''}>${escape(device.name)}${context.devices.includes(device.id) ? '' : ' · outside selected pool'}</label>`).join('') || '<p>Select Session devices in Setup to configure their supported parameters.</p>'}</div>` : ''}
    <fieldset class="parameter-fields" id="parameter-fields" ${readOnly ? 'disabled' : ''}>
      <details class="parameter-section" open><summary>Experiment timing</summary><div class="parameter-section-body"><label>Planned duration (seconds)<input type="number" id="experiment-duration" value="${escape(configuration.durationSeconds ?? '')}" min="1" step="any" required></label><p>${state.connected ? 'Requested autonomous acquisition duration.' : 'Explicit demonstration duration, not a real acquisition deadline.'}</p></div></details>
      ${devices.filter(device => context.devices.includes(device.id) || configuration.participants.includes(device.id)).map(device => `<details class="parameter-section" ${configuration.participants.includes(device.id) ? 'open' : ''}><summary>${escape(device.name)} <small>${state.connected ? 'Declared settings' : 'Illustrative settings'}</small></summary><fieldset class="parameter-section-body" ${configuration.participants.includes(device.id) ? '' : 'disabled'}>${(deviceExamples[device.id]?.fields || []).map(field => parameterField(field, configuration.values[field.id], Object.hasOwn(configuration.values, field.id))).join('') || '<p>No supported parameter definitions supplied for this device.</p>'}</fieldset></details>`).join('')}
      ${state.connected ? `<details class="parameter-section" open><summary>Framework recording configuration</summary><div class="parameter-section-body"><label>Experiment ID${stringField('data-framework-field="experimentId"', configuration.experimentId)}</label><label>Preservation budget (bytes)<input type="number" min="1" step="1" data-framework-field="preservationBudget" value="${escape(configuration.preservationBudget ?? '')}" required></label>${[...new Set(participants.map(device => device.nodeId))].map(node => `<label>${escape(node)} recording budget (bytes)<input type="number" min="1" step="1" data-recording-budget="${escape(node)}" value="${escape(configuration.recordingBudgets?.[node] ?? '')}" required></label>`).join('')}<h4>Scientific outputs</h4>${participants.flatMap(device => (device.declaration?.scientific_products || []).map(product => { const output = {source_node_id: device.nodeId, source_device_id: device.deviceId, data_product_id: product.data_product_id}; return `<label class="parameter-checkbox"><input type="checkbox" data-scientific-output="${escape(JSON.stringify(output))}" ${configuration.outputs?.some(item => scientificOutputIdentity(item) === scientificOutputIdentity(output)) ? 'checked' : ''}>${escape(device.name)} / ${escape(product.data_product_id)}</label>`; })).join('') || '<p>No declared scientific products available.</p>'}</div></details>` : ''}
    </fieldset>
    <section class="personal-template-area"><h3>Save as personal template <small>Optional</small></h3><p>${state.connected ? "A new name creates an independent template; an existing personal name overwrites only your own template." : "A new name creates an independent Experiment template."} Laboratory templates are never overwritten.</p><form id="personal-experiment-template"><label>Personal template name<input name="templateName" value="${escape(view.bundle?.personalTemplateName || '')}" required ${readOnly ? 'disabled' : ''} placeholder="My baseline configuration"></label><button type="submit" ${readOnly ? 'disabled' : ''}>Save as personal template</button></form></section>
    <p id="parameter-feedback" role="status">${escape(message)}</p>`;
  for (const control of panel.querySelectorAll('[data-string-value]')) {
    configurationStringEditor(control, control.hasAttribute('data-invalid-string')
      ? {invalidString: control.value} : control.value ? parseConfigurationString(control.value) : '');
  }
  for (const control of panel.querySelectorAll('[data-example-value]')) {
    const field = Object.values(deviceExamples).flatMap(device => device.fields).find(item => item.id === control.dataset.exampleValue);
    if (field && Object.hasOwn(configuration.values, field.id)) control.setCustomValidity(parameterIssue(field, configuration.values[field.id]));
  }
}

panel.addEventListener('click', event => {
  const override = event.target.closest('[data-unset-parameter], [data-null-parameter]');
  if (override) {
    const context = resolveParameterContext(state);
    if (!context || context.readOnly) return;
    const values = {...context.configuration.values};
    if (override.hasAttribute('data-unset-parameter')) delete values[override.dataset.unsetParameter];
    else values[override.dataset.nullParameter] = null;
    context.update({values}); message = ''; renderParameters(); return;
  }
  if (event.target.closest('[data-return-session]')) navigate(resolveParameterContext(state)?.origin || state.parameterContext?.origin || 'setup');
  if (event.target.closest('[data-parameter-expand], [data-parameter-collapse]')) {
    const open = !!event.target.closest('[data-parameter-expand]');
    panel.querySelectorAll('.parameter-section').forEach(section => { section.open = open; });
  }
});
function updateParameterWorking(event) {
  const control = event.target;
  const view = resolveParameterContext(state);
  if (!view || view.readOnly) return;
  if (control.matches('#personal-experiment-template [name="templateName"]')) {
    if (view.bundle) view.bundle.personalTemplateName = control.value;
    return;
  }
  if (control.matches('[data-parameter-participant]')) {
    const participants = view.configuration.participants.filter(id => id !== control.dataset.parameterParticipant);
    if (control.checked && view.devices.includes(control.dataset.parameterParticipant)) participants.push(control.dataset.parameterParticipant);
    view.update({participants}); renderParameters(); return;
  }
  if (!control.matches('#experiment-duration, [data-example-value], [data-framework-field], [data-recording-budget], [data-scientific-output]')) return;
  try {
    const definition = control.dataset.exampleValue
      ? Object.values(deviceExamples).flatMap(device => device.fields).find(field => field.id === control.dataset.exampleValue) : null;
    let numeric = null, inputError = null, stringValue;
    if (control.hasAttribute('data-configuration-string')) {
      try { stringValue = readConfigurationString(control); }
      catch (error) { stringValue = {invalidString: control.value}; inputError = error; }
      control.setCustomValidity(inputError ? 'Invalid exact-character representation.' : '');
    }
    if (control.type === 'number' && control.validity.badInput) {
      numeric = 'Invalid numeric input';
      inputError = new Error('Invalid numeric input. Enter a finite value representable by this GUI.');
    } else if (control.type === 'number' && control.value !== '') {
      const integer = Boolean(definition?.integer || control.dataset.recordingBudget || control.dataset.frameworkField === 'preservationBudget');
      try { numeric = configurationNumber(control.value, integer); }
      catch (error) { numeric = control.value; inputError = error; }
    }
    if (control.id === 'experiment-duration') view.update({ durationSeconds: numeric });
    else if (control.dataset.frameworkField) view.update({ [control.dataset.frameworkField]: control.type === 'number' ? numeric : stringValue });
    else if (control.dataset.recordingBudget) view.update({ recordingBudgets: { ...view.configuration.recordingBudgets, [control.dataset.recordingBudget]: numeric } });
    else if (control.dataset.scientificOutput) {
      const output = JSON.parse(control.dataset.scientificOutput);
      const outputs = view.configuration.outputs.filter(item => scientificOutputIdentity(item) !== scientificOutputIdentity(output));
      if (control.checked) outputs.push(output);
      view.update({ outputs });
    }
    else if (control.dataset.exampleValue) {
      const values = { ...view.configuration.values };
      if (definition?.allowedValues) {
        if (control.value === '') delete values[control.dataset.exampleValue];
        else values[control.dataset.exampleValue] = definition.allowedValues[Number(control.value)];
      }
      else if (state.connected && control.type === 'number' && control.value === '' && !definition?.nullable && !inputError) delete values[control.dataset.exampleValue];
      else values[control.dataset.exampleValue] = control.hasAttribute('data-configuration-string') ? stringValue : control.type === 'checkbox' ? control.checked : control.type === 'number' ? numeric : control.value;
      const issue = Object.hasOwn(values, control.dataset.exampleValue) ? parameterIssue(definition, values[control.dataset.exampleValue]) : '';
      control.setCustomValidity(inputError?.message || issue);
      if (issue && !inputError) inputError = new Error(issue);
      view.update({ values });
      if (state.connected) {
        const toolbar = control.closest('label').nextElementSibling;
        toolbar.querySelector('small').textContent = Object.hasOwn(values, control.dataset.exampleValue) ? values[control.dataset.exampleValue] === null ? 'Explicit null' : 'Explicit override' : 'No explicit override';
        toolbar.querySelector('[data-unset-parameter]').disabled = !Object.hasOwn(values, control.dataset.exampleValue);
      }
    }
    message = inputError ? `Invalid configuration value: ${inputError.message}` : (state.connected ? 'Unsent working values updated. Controller validates the submitted configuration.' : 'Working values updated. Return to Session to inspect the summary or launch the simulation; no template save is required.');
    state.actions.syncControls?.();
  } catch (error) { message = error.message; state.actions.recordActivity?.('validate_parameters', error.message); }
  panel.querySelector('#parameter-feedback').textContent = message;
}
panel.addEventListener('input', updateParameterWorking);
panel.addEventListener('change', event => { if (event.target.type === 'checkbox' || event.target.tagName === 'SELECT') updateParameterWorking(event); });
panel.addEventListener('submit', async event => {
  if (event.target.id !== 'personal-experiment-template') return;
  event.preventDefault();
  const invalid = [...panel.querySelectorAll('#parameter-fields input, #parameter-fields select, #parameter-fields textarea')].find(control => !control.checkValidity());
  if (invalid) { invalid.reportValidity(); return; }
  const context = resolveParameterContext(state);
  if (!context || context.readOnly || !context.record) return;
  const {step, record} = context;
  const button = event.target.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const owner = context.origin === 'session' ? executionIdentity(state).owner : document.querySelector('#experimenter-select').value;
    const templateRecord = {status: 'ready', experiment: clone(context.bundle)};
    let template;
    if (state.connected) {
      const working = {connected: true, selectedDevices: state.activeSession?.selectedDevices || state.selectedDevices,
        experimentTemplates: clone(state.experimentTemplates || [])};
      template = saveExperimentTemplate(working, step, templateRecord, event.target.elements.templateName.value, owner);
      await putCatalog('experimentTemplates', template, owner, record.experiment.catalogRevision);
      record.experiment.catalogRevision = catalogClient.snapshot.revision;
      state.experimentTemplates = clone(catalogClient.snapshot.catalog.experimentTemplates);
      // Saving a reusable template never rewrites this attempt's configuration.
      state.actions.recordActivity?.('save_catalog');
      message = `Saved personal Experiment template “${template.name}”.`;
    } else {
      template = saveExperimentTemplate(state, step, templateRecord, event.target.elements.templateName.value, owner);
      message = `Saved personal Experiment template “${template.name}” in page memory. No shared template or previous attempt changed.`;
    }
  } catch (error) { message = error.message; state.actions.recordActivity?.('save_catalog', error.message, error.catalogStatus); }
  finally { button.disabled = false; }
  panel.querySelector('#parameter-feedback').textContent = message;
});
document.addEventListener('gui-section-changed', event => { if (event.detail === 'parameters') renderParameters(); });
renderParameters();
