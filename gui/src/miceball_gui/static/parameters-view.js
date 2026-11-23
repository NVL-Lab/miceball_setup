import { state } from './protocol-setup.js';
import { devices, operations } from './protocol-demo.mjs';
import { deviceExamples, saveExperimentTemplate } from './experiment-demo.mjs';
import { escapeText as escape, executionIdentity, navigate, configurationStringEditor, readConfigurationString } from './gui-presentation.js';
import { configurationNumber, scientificOutputIdentity, configurationStringText, parseConfigurationString } from './configuration-values.mjs';
import { clone } from './protocol-demo.mjs';
import { catalogClient, putCatalog, putSynchronization } from './catalog-client.mjs';
import { resolveParameterContext } from './parameter-context.mjs';
import { parameterIssue, configuredParameterValue } from './parameter-constraints.mjs';
import { recordInvalidControl, recordActivity, updateActivity } from './activity-history.mjs';
import { servicesAdministrator, servicesAdministratorName } from './services-view.js';
import { confirmCatalogRemoval } from './catalog-removal.js';

const panel = document.querySelector('#panel-parameters');
function removableExperimentTemplate() {
  const context = resolveParameterContext(state);
  const input = panel.querySelector('[name="templateName"]');
  if (!state.connected || !context || context.readOnly || !input) return null;
  const owner = context.origin === 'session' ? executionIdentity(state).owner : document.querySelector('#experimenter-select').value;
  return state.experimentTemplates.find(item => item.owner === owner && item.operation === context.step.operation && item.name === input.value);
}
function updateTemplateRemoval() {
  const button = panel.querySelector('[data-remove-experiment-template]');
  if (button) button.disabled = !removableExperimentTemplate();
}
panel.addEventListener('click', event => {
  if (!event.target.closest('[data-remove-experiment-template]')) return;
  const target = removableExperimentTemplate();
  if (target) confirmCatalogRemoval('experimentTemplates', target.id, target.owner);
});
panel.addEventListener('input', updateTemplateRemoval);
document.addEventListener('gui-catalog-changed', updateTemplateRemoval);
panel.addEventListener('invalid', event => recordInvalidControl(event.target.closest('#personal-experiment-template') ? 'save_catalog' : 'validate_parameters', event.target), true);
panel.addEventListener('focusout', event => {
  if (event.target.matches('#parameter-fields input, #parameter-fields select, #parameter-fields textarea')) recordInvalidControl('validate_parameters', event.target);
});
let message = '';
let synchronizationSection, synchronizationDirty = false, administrativeSection;

function administrativeParameters(form) {
  const parameters = Object.create(null);
  for (const field of form.parameterDefinitions) {
    const input = [...form.querySelectorAll('[data-example-value]')].find(input => input.dataset.exampleValue === field.id);
    const nullControl = [...form.querySelectorAll('[data-administrative-null]')].find(input => input.dataset.administrativeNull === field.id);
    const value = nullControl?.checked ? null : field.allowedValues ? input.value === '' ? null : field.allowedValues[Number(input.value)]
      : field.type === 'checkbox' ? input.checked : field.type === 'number'
      ? input.value === '' && field.nullable ? null : configurationNumber(input.value, Boolean(field.integer))
      : readConfigurationString(input);
    const issue = parameterIssue(field, value);
    if (issue) throw new Error(issue);
    parameters[field.name] = value;
  }
  return parameters;
}

function renderAdministrativeSettings() {
  if (!state.connected || !servicesAdministrator()) return;
  administrativeSection ||= document.createElement('section');
  administrativeSection.className = 'parameter-fields administrative-device-parameters';
  if (!administrativeSection.firstChild) administrativeSection.innerHTML = '<h3>Device Parameters</h3>';
  const currentDevices = new Set();
  for (const device of devices) {
    const fields = (deviceExamples[device.id]?.fields || []).filter(field => field.adjustmentScope === 'administrator');
    if (!fields.length) continue;
    currentDevices.add(device.id);
    let form = [...administrativeSection.querySelectorAll('form')].find(item => item.dataset.administrativeDevice === device.id);
    if (!form) {
      form = document.createElement('form'); form.dataset.administrativeDevice = device.id;
      form.className = 'setup-card';
      form.innerHTML = `<h4>${escape(device.nodeId)} / ${escape(device.deviceId)}</h4><p data-administrative-values></p><fieldset class="parameter-section-body" data-administrative-fields></fieldset><button type="submit" class="dialog-button">Save device settings</button><button type="button" data-administrative-reload>Reload saved values</button><p role="status" data-administrative-feedback></p>`;
      form.addEventListener('input', () => { form.dataset.dirty = 'true'; renderAdministrativeSettings(); });
      form.addEventListener('change', () => { form.dataset.dirty = 'true'; renderAdministrativeSettings(); });
      form.querySelector('[data-administrative-reload]').onclick = () => {
        form.dataset.dirty = ''; form.querySelector('[data-administrative-feedback]').textContent = '';
        renderAdministrativeSettings();
      };
      form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!servicesAdministrator() || !state.actions.canControl?.() || form.dataset.available !== 'true'
            || form.dataset.pending || form.dataset.metadataChanged || !form.reportValidity()) return;
        const parameters = Object.create(null);
        try {
          Object.assign(parameters, administrativeParameters(form));
          form.dataset.pending = 'true'; renderAdministrativeSettings();
          const entry = await state.actions.updateDeviceConfiguration(device.nodeId, device.deviceId,
            parameters, form.dataset.revision, servicesAdministratorName());
          if (entry.status === 'succeeded') form.dataset.dirty = '';
          form.querySelector('[data-administrative-feedback]').textContent = entry.status === 'succeeded'
            ? 'Saved durably. Loaded settings are unchanged until normal AcquisitionNode restart.'
            : `${entry.status}: ${entry.error || 'Save not confirmed'}. Review authoritative saved values before another attempt.`;
        } catch (error) { form.querySelector('[data-administrative-feedback]').textContent = error.message; }
        finally { form.dataset.pending = ''; renderAdministrativeSettings(); }
      });
      administrativeSection.append(form);
    }
    const report = state.inventory[device.nodeId]?.administrative_configuration;
    const signature = JSON.stringify(fields);
    const changed = Boolean(form.dataset.definitions && form.dataset.definitions !== signature);
    let retainedDraft = null;
    if (changed && form.dataset.dirty && !form.dataset.pending) {
      try {
        const draft = administrativeParameters(form);
        if (Object.keys(draft).length === fields.length && fields.every(field =>
          Object.hasOwn(draft, field.name) && !parameterIssue(field, draft[field.name]))) retainedDraft = draft;
      } catch (_) { /* Keep invalid or incomplete drafts intact for explicit review. */ }
    }
    form.dataset.metadataChanged = changed && !retainedDraft && (form.dataset.dirty || form.dataset.pending) ? 'true' : '';
    const loaded = report?.loaded?.[device.deviceId], saved = report?.saved?.[device.deviceId];
    const comparable = report?.available && loaded && saved
      && fields.every(field => Object.hasOwn(loaded, field.name) && Object.hasOwn(saved, field.name));
    const restart = comparable ? fields.some(field => JSON.stringify(loaded[field.name]) !== JSON.stringify(saved[field.name])) : null;
    form.querySelector('[data-administrative-values]').textContent = `Loaded: ${JSON.stringify(loaded) ?? 'unavailable'}; Saved: ${report?.available ? JSON.stringify(saved) ?? 'unavailable' : 'unavailable'}. ${restart === null ? 'Restart requirement unknown.' : restart ? 'Normal AcquisitionNode restart required.' : 'Saved and loaded values match.'} ${report?.reason || ''} ${(report?.blockers || []).join('; ')}`;
    if (form.dataset.metadataChanged) form.querySelector('[data-administrative-feedback]').textContent = 'Parameter definitions changed. Unsaved values are retained; reload saved values to use the current definitions.';
    else if (retainedDraft) form.querySelector('[data-administrative-feedback]').textContent = 'Current definitions applied; unsaved values and the original saved revision are retained.';
    if (retainedDraft || !form.dataset.dirty && !form.dataset.pending) {
      form.parameterDefinitions = fields;
      form.dataset.definitions = signature;
      if (!retainedDraft) form.dataset.revision = report?.available ? report.revision : '';
      const values = retainedDraft || saved;
      form.querySelector('[data-administrative-fields]').innerHTML = fields.map(field => parameterField(field,
        values?.[field.name], values && Object.hasOwn(values, field.name), {available: false}, true)).join('');
      for (const input of form.querySelectorAll('[data-string-value]')) {
        const field = fields.find(field => field.id === input.dataset.exampleValue);
        configurationStringEditor(input, values && Object.hasOwn(values, field.name) ? values[field.name] ?? '' : '');
      }
    }
    const allowed = Boolean(report?.available && !report.blockers.length && device.available && state.actions.canControl?.() && !form.dataset.metadataChanged);
    form.dataset.available = String(allowed);
    form.querySelector('fieldset').disabled = !allowed || Boolean(form.dataset.pending);
    form.querySelector('[type="submit"]').disabled = !allowed || !form.dataset.dirty || Boolean(form.dataset.pending);
    form.querySelector('[data-administrative-reload]').disabled = !report?.available || Boolean(form.dataset.pending);
  }
  for (const form of administrativeSection.querySelectorAll('form')) if (!currentDevices.has(form.dataset.administrativeDevice)) {
    if (!form.dataset.dirty && !form.dataset.pending) { form.remove(); continue; }
    form.querySelector('fieldset').disabled = true;
    form.dataset.available = 'false';
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    form.querySelector('[data-administrative-feedback]').textContent = 'Device or administrative definitions unavailable. Unsaved values are retained; saving is disabled.';
  }
  panel.append(administrativeSection);
}
function renderSynchronizationSettings() {
  if (!servicesAdministrator()) return;
  if (!synchronizationSection) {
    synchronizationSection = document.createElement('section');
    synchronizationSection.className = 'setup-card'; synchronizationSection.dataset.synchronizationSettings = '';
    const labels = {exchanges: 'Measured exchanges', initial_scale: 'Initial scale (ratio)', clock_rate_error_bound: 'Clock-rate error bound (ratio)', max_uncertainty_s: 'Maximum uncertainty (s)', max_mapping_age_s: 'Maximum mapping age (s)', assessment_interval_s: 'Assessment interval (s)', result_window_s: 'Result window (s)'};
    synchronizationSection.innerHTML = `<h3>Synchronization defaults</h3><form data-synchronization-form><div class="catalog-fields">${Object.entries(labels).map(([name, label]) => `<label>${label}<input type="number" name="${name}" required min="${name === 'exchanges' ? 2 : 0}" step="${name === 'exchanges' ? 1 : 'any'}"></label>`).join('')}<label>Timing-quality interpretation<select name="quality_interpretation">${['informational', 'warning', 'recoverable_failure', 'experiment_failure', 'session_failure', 'operator_required', 'uninterpreted'].map(value => `<option value="${value}">${value.replaceAll('_', ' ')}</option>`).join('')}</select></label></div><button type="submit" class="dialog-button">Save</button><small role="status" data-synchronization-feedback></small></form>`;
    const form = synchronizationSection.querySelector('form');
    form.addEventListener('input', () => { synchronizationDirty = true; });
    form.addEventListener('change', () => { synchronizationDirty = true; });
    form.addEventListener('invalid', event => recordInvalidControl('save_synchronization', event.target), true);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!state.connected || !servicesAdministrator()) return;
      if (!form.reportValidity()) return;
      const activity = recordActivity('save_synchronization');
      const button = form.querySelector('button'); button.disabled = true;
      try {
        const submittedValues = JSON.stringify([...new FormData(form)]);
        const configuration = Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, key === 'quality_interpretation' ? value : configurationNumber(value)]));
        await putSynchronization(configuration, servicesAdministratorName(), Number(form.dataset.revision));
        synchronizationDirty = JSON.stringify([...new FormData(form)]) !== submittedValues;
        form.dataset.revision = String(catalogClient.snapshot.revision);
        updateActivity(activity, {status: 'succeeded'});
        form.querySelector('[role="status"]').textContent = synchronizationDirty ? 'Saved; newer edits remain unsaved.' : 'Saved for subsequent Sessions.';
        renderSynchronizationSettings();
      } catch (error) {
        form.querySelector('[role="status"]').textContent = error.message;
        updateActivity(activity, {status: error.catalogStatus || 'failed', error: error.message});
      } finally { button.disabled = false; }
    });
  }
  const form = synchronizationSection.querySelector('form');
  const configuration = state.connected && catalogClient.snapshot?.synchronization_configuration;
  if (!synchronizationDirty && configuration) {
    for (const [key, value] of Object.entries(configuration)) form.elements[key].value = value;
    form.dataset.revision = String(catalogClient.snapshot.revision);
  }
  for (const control of form.elements) control.disabled = !configuration;
  if (!configuration) form.querySelector('[role="status"]').textContent = 'Backend synchronization settings unavailable.';
  panel.prepend(synchronizationSection);
}
document.addEventListener('gui-catalog-changed', () => {
  if (panel.classList.contains('is-active')) renderSynchronizationSettings();
});

function stringField(attributes, value) {
  return `<textarea ${attributes} data-string-value ${value?.invalidString !== undefined ? 'data-invalid-string' : ''} rows="1">${escape(configurationStringText(value))}</textarea>`;
}

function parameterField(field, value, present, inherited = {available: false}, administrative = false) {
  if (state.connected && field.adjustmentScope === 'administrator' && !administrative) {
    if (!present) return '';
    return `<div class="parameter-override"><p>${escape(field.label)}: ${escape(JSON.stringify(value))} — retained administrator-only override; future ordinary execution is refused.</p><button type="button" data-unset-parameter="${escape(field.id)}">Remove retained override</button></div>`;
  }
  if (state.connected && !present && inherited.available) value = inherited.value;
  const displayed = present || state.connected && inherited.available;
  const attributes = `data-example-value="${escape(field.id)}" aria-label="${escape(field.label)}"`;
  let control;
  const undeclaredChoice = field.allowedValues && present && value !== null && !field.allowedValues.includes(value);
  if (field.allowedValues) control = `<label>${escape(field.label)}<select ${attributes}><option value="" ${!displayed || value === null ? 'selected' : ''}>${value === null && displayed ? 'Adapter-defined empty value' : 'No override'}</option>${undeclaredChoice ? `<option value="__current__" selected disabled>${escape(configurationStringText(value))} · not in current declared choices</option>` : ''}${field.allowedValues.map((option, index) => `<option value="${index}" ${displayed && option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  else if (field.type === 'select') control = `<label>${escape(field.label)}<select ${attributes}>${field.options.map(option => `<option ${option === value ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select></label>`;
  else if (field.type === 'checkbox') control = `<label class="parameter-checkbox"><input type="checkbox" ${attributes} ${value ? 'checked' : ''}>${escape(field.label)}</label>`;
  else if (state.connected && field.type === 'text') control = `<label>${escape(field.label)}${stringField(attributes, value)}</label>`;
  else control = `<label>${escape(field.label)}<input type="${escape(field.type)}" ${attributes} value="${escape(value ?? '')}" ${field.min !== undefined ? `min="${escape(field.min)}"` : ''} ${field.max !== undefined ? `max="${escape(field.max)}"` : ''} step="${field.integer ? '1' : 'any'}" ${state.connected || field.nullable ? '' : 'required'}></label>`;
  if (administrative) return `${control}${field.nullable ? `<label class="parameter-checkbox"><input type="checkbox" data-administrative-null="${escape(field.id)}" ${value === null ? 'checked' : ''}>${escape(field.nullDescription)}</label>` : ''}`;
  if (!state.connected) return control;
  return `<div class="parameter-override">${control}<div class="parameter-toolbar"><small>${present ? value === null ? 'Adapter-defined empty value requested' : 'Explicit override' : inherited.available ? value === null ? 'Inherited configuration: no value requested' : 'Inherited requested configuration' : 'Configured value unavailable; no explicit override'}</small>${field.type !== 'number' ? `<button type="button" data-unset-parameter="${escape(field.id)}" title="Remove draft override" aria-label="Remove draft override" ${present ? '' : 'hidden'}>×</button>` : ''}${field.nullable ? `<label class="parameter-checkbox"><input type="checkbox" data-null-parameter="${escape(field.id)}" ${present && value === null ? 'checked' : ''}>${escape(field.nullDescription)}</label>` : ''}</div></div>`;
}

export function renderParameters() {
  const context = resolveParameterContext(state);
  if (!context) {
    panel.innerHTML = '<div class="context-empty"><h2 class="visually-hidden" id="heading-parameters">Parameters</h2><p>No supported parameter configuration is available in this context. Select an Experiment operation in Setup or Session. Saved Steps without explicit settings must be copied in Protocol Editor before editing.</p><button type="button" data-return-session>Return</button></div>';
    renderSynchronizationSettings();
    renderAdministrativeSettings();
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
      ${devices.filter(device => context.devices.includes(device.id) || configuration.participants.includes(device.id)).map(device => `<details class="parameter-section" ${configuration.participants.includes(device.id) ? 'open' : ''}><summary>${escape(device.name)} <small>${state.connected ? 'Declared settings' : 'Illustrative settings'}</small></summary><fieldset class="parameter-section-body" ${configuration.participants.includes(device.id) ? '' : 'disabled'}>${(deviceExamples[device.id]?.fields || []).map(field => parameterField(field, configuration.values[field.id], Object.hasOwn(configuration.values, field.id), configuredParameterValue(state, device, field, ['session', 'experiment'].includes(context.kind) ? state.activeSession?.sessionId : null))).join('') || '<p>No supported parameter definitions supplied for this device.</p>'}</fieldset></details>`).join('')}
      ${state.connected ? `<details class="parameter-section" open><summary>Framework recording configuration</summary><div class="parameter-section-body"><label>Experiment ID${stringField('data-framework-field="experimentId"', configuration.experimentId)}</label><label>Preservation budget (bytes)<input type="number" min="1" step="1" data-framework-field="preservationBudget" value="${escape(configuration.preservationBudget ?? '')}" required></label>${[...new Set(participants.map(device => device.nodeId))].map(node => `<label>${escape(node)} recording budget (bytes)<input type="number" min="1" step="1" data-recording-budget="${escape(node)}" value="${escape(configuration.recordingBudgets?.[node] ?? '')}" required></label>`).join('')}<section class="parameter-section scientific-outputs"><h4>Scientific Outputs</h4><div class="parameter-section-body">${participants.flatMap(device => (device.declaration?.scientific_products || []).map(product => { const output = {source_node_id: device.nodeId, source_device_id: device.deviceId, data_product_id: product.data_product_id}; return `<label class="parameter-checkbox"><input type="checkbox" data-scientific-output="${escape(JSON.stringify(output))}" ${configuration.outputs?.some(item => scientificOutputIdentity(item) === scientificOutputIdentity(output)) ? 'checked' : ''}>${escape(device.name)} / ${escape(product.data_product_id)}</label>`; })).join('') || '<p>No declared scientific products available.</p>'}</div></section></div></details>` : ''}
    </fieldset>
    <section class="personal-template-area"><h3>Save as personal template <small>Optional</small></h3><p>${state.connected ? "A new name creates an independent template; an existing personal name overwrites only your own template." : "A new name creates an independent Experiment template."} Laboratory templates are never overwritten.</p><form id="personal-experiment-template"><label>Personal template name<input name="templateName" value="${escape(view.bundle?.personalTemplateName || '')}" required ${readOnly ? 'disabled' : ''} placeholder="My baseline configuration"></label><button type="submit" ${readOnly ? 'disabled' : ''}>Save as personal template</button><button type="button" data-remove-experiment-template ${!state.connected || readOnly ? 'hidden' : ''}>Remove</button></form></section>
    <p id="parameter-feedback" role="status">${escape(message)}</p>`;
  for (const control of panel.querySelectorAll('[data-string-value]')) {
    configurationStringEditor(control, control.hasAttribute('data-invalid-string')
      ? {invalidString: control.value} : control.value ? parseConfigurationString(control.value) : '');
  }
  for (const control of panel.querySelectorAll('[data-example-value]')) {
    const field = Object.values(deviceExamples).flatMap(device => device.fields).find(item => item.id === control.dataset.exampleValue);
    if (field && Object.hasOwn(configuration.values, field.id)) control.setCustomValidity(parameterIssue(field, configuration.values[field.id]));
  }
  renderSynchronizationSettings();
  renderAdministrativeSettings();
  updateTemplateRemoval();
}

panel.addEventListener('click', event => {
  const override = event.target.closest('[data-unset-parameter], [data-null-parameter]');
  if (override) {
    const context = resolveParameterContext(state);
    if (!context || context.readOnly) return;
    const values = {...context.configuration.values};
    if (override.hasAttribute('data-unset-parameter')) delete values[override.dataset.unsetParameter];
    else if (override.checked) values[override.dataset.nullParameter] = null;
    else delete values[override.dataset.nullParameter];
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
  if (control.closest('[data-administrative-device]')) return;
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
      else if (state.connected && control.type === 'number' && control.value === '' && !inputError) delete values[control.dataset.exampleValue];
      else values[control.dataset.exampleValue] = control.hasAttribute('data-configuration-string') ? stringValue : control.type === 'checkbox' ? control.checked : control.type === 'number' ? numeric : control.value;
      const issue = Object.hasOwn(values, control.dataset.exampleValue) ? parameterIssue(definition, values[control.dataset.exampleValue]) : '';
      control.setCustomValidity(inputError?.message || issue);
      if (issue && !inputError) inputError = new Error(issue);
      view.update({ values });
      if (state.connected) {
        const toolbar = control.closest('label').nextElementSibling;
        toolbar.querySelector('small').textContent = Object.hasOwn(values, control.dataset.exampleValue) ? values[control.dataset.exampleValue] === null ? 'Adapter-defined empty value requested' : 'Explicit override' : 'No explicit override';
        const unset = toolbar.querySelector('[data-unset-parameter]');
        if (unset) unset.hidden = !Object.hasOwn(values, control.dataset.exampleValue);
        const empty = toolbar.querySelector('[data-null-parameter]');
        if (empty) empty.checked = Object.hasOwn(values, control.dataset.exampleValue) && values[control.dataset.exampleValue] === null;
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
document.addEventListener('gui-administrator-changed', renderParameters);
