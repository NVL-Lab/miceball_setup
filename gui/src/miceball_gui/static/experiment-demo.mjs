// Explicitly fictional fixtures, not device SDK definitions or a framework schema.
import { clone, devices, declaredCoverage } from './protocol-demo.mjs';

export const deviceExamples = {
  orca: { acquisition: true, fields: [{ id: 'orca.exposure', label: 'Example exposure (ms)', type: 'number', value: 10, min: 1, max: 1000 }, { id: 'orca.trigger', label: 'Example trigger mode', type: 'select', value: 'Internal', options: ['Internal', 'External'] }] },
  logitech: { acquisition: true, fields: [{ id: 'logitech.rate', label: 'Example frame rate (Hz)', type: 'number', value: 30, min: 1, max: 60 }] },
  extra: { acquisition: true, fields: [{ id: 'extra.rate', label: 'Example frame rate (Hz)', type: 'number', value: 20, min: 1, max: 60 }] },
  display: { acquisition: false, fields: [{ id: 'display.pattern', label: 'Example stimulus', type: 'select', value: 'Uniform', options: ['Uniform', 'Grating'] }] },
  reward: { acquisition: false, fields: [{ id: 'reward.pulse', label: 'Example pulse duration (ms)', type: 'number', value: 15, min: 1, max: 100 }] },
  holograph: { acquisition: false, fields: [{ id: 'holograph.enabled', label: 'Example stimulation enabled', type: 'checkbox', value: true }] },
};
const operationExamples = {
  initial: { name: 'Standard initial imaging', durationSeconds: 120, participants: ['orca'] },
  baseline: { name: 'Standard baseline', durationSeconds: 900, participants: ['orca', 'logitech'] },
  holo: { name: 'Standard stimulation', durationSeconds: 60, participants: ['orca', 'holograph'] },
  loop: { name: 'Standard closed-loop', durationSeconds: 1800, participants: ['orca', 'display', 'reward'] },
};
function exampleConfiguration(operation) {
  const example = operationExamples[operation];
  if (!example) throw new Error('No Experiment demonstration configuration for this operation.');
  return { durationSeconds: example.durationSeconds, participants: [...example.participants], values: Object.fromEntries(Object.values(deviceExamples).flatMap(device => device.fields.map(field => [field.id, field.value]))) };
}
function freezeConfiguration(configuration) {
  const copy = clone(configuration);
  Object.freeze(copy.participants);
  Object.freeze(copy.values);
  return Object.freeze(copy);
}
export function experimentTemplates(state, operation, owner) {
  state.experimentTemplates ??= Object.entries(operationExamples).map(([id, example]) => Object.freeze({ id: `experiment-${id}`, operation: id, owner: null, name: example.name, configuration: freezeConfiguration(exampleConfiguration(id)) }));
  return state.experimentTemplates.filter(template => template.operation === operation && (template.owner === null || template.owner === owner));
}
export function experimentView(state, step, record) {
  if (!record.experiment) {
    const working = exampleConfiguration(step.operation);
    working.participants = working.participants.filter(id => state.selectedDevices.includes(id));
    const historical = ['completed', 'needs-review'].includes(record.status);
    record.experiment = { working, startingConfiguration: clone(working), templateId: '', editing: !historical, attempts: historical ? [freezeConfiguration(working)] : [] };
  }
  const bundle = record.experiment;
  const readOnly = record.status === 'running' || (!bundle.editing && bundle.attempts.length > 0);
  const configuration = readOnly ? bundle.attempts.at(-1) : bundle.working;
  const template = state.experimentTemplates?.find(item => item.id === bundle.templateId);
  const comparable = config => JSON.stringify([config.durationSeconds, [...config.participants].sort(), Object.entries(config.values).sort()]);
  const modified = !!template && comparable(configuration) !== comparable(template.configuration);
  return { bundle, configuration, readOnly, template, modified, workingModified: !readOnly && (modified || comparable(bundle.working) !== comparable(bundle.startingConfiguration)) };
}
export function updateExperiment(state, step, record, patch) {
  const view = experimentView(state, step, record);
  if (view.readOnly) throw new Error('Executed configuration is read-only. Prepare a new demonstration attempt first.');
  for (const key of ['durationSeconds', 'participants', 'values']) if (key in patch) view.bundle.working[key] = patch[key];
  return experimentView(state, step, record);
}
export function loadExperimentTemplate(state, step, record, id, owner, replaceModified = false) {
  const template = experimentTemplates(state, step.operation, owner).find(item => item.id === id);
  if (!template) throw new Error('Select an available Experiment template.');
  const view = experimentView(state, step, record);
  if (view.readOnly) throw new Error('Executed configuration is read-only. Prepare a new demonstration attempt first.');
  if (view.workingModified && !replaceModified) throw new Error('Confirm replacing modified working values before loading a template.');
  updateExperiment(state, step, record, clone(template.configuration));
  record.experiment.startingConfiguration = clone(template.configuration);
  record.experiment.templateId = template.id;
}
export function saveExperimentTemplate(state, step, record, name, owner) {
  const view = experimentView(state, step, record);
  if (view.readOnly) throw new Error('Prepare an editable configuration before saving a new template.');
  const available = experimentTemplates(state, step.operation, owner);
  const trimmed = name.trim();
  if (!trimmed || available.some(template => template.name.toLowerCase() === trimmed.toLowerCase())) throw new Error('Choose a new personal template name; existing templates are not overwritten.');
  const template = Object.freeze({ id: `personal-experiment-${state.experimentTemplates.length}`, operation: step.operation, owner, name: trimmed, configuration: freezeConfiguration(view.configuration) });
  state.experimentTemplates.push(template);
  record.experiment.templateId = template.id;
  record.experiment.startingConfiguration = clone(view.configuration);
  return template;
}
export function prepareExperimentRepeat(state, step, record) {
  if (record.status === 'running') throw new Error('A running demonstration configuration cannot be edited.');
  const view = experimentView(state, step, record);
  view.bundle.working = clone(view.configuration);
  view.bundle.startingConfiguration = clone(view.configuration);
  view.bundle.editing = true;
}
export function experimentIssues(state, step, configuration) {
  const issues = [];
  if (!Number.isFinite(configuration.durationSeconds) || configuration.durationSeconds <= 0) issues.push('Set a positive planned duration.');
  if (configuration.participants.some(id => !state.selectedDevices.includes(id))) issues.push('Remove participants that are not selected in Setup.');
  const participants = devices.filter(device => configuration.participants.includes(device.id));
  if (!participants.some(device => deviceExamples[device.id]?.acquisition)) issues.push('Select at least one demonstration data-acquisition device.');
  if (participants.some(device => !device.available)) issues.push('A participating demonstration device is unavailable.');
  if (declaredCoverage(step.required, configuration.participants).some(row => !row.providers.some(device => device.available))) issues.push('A required capability has no available participating provider.');
  const fields = participants.flatMap(device => deviceExamples[device.id]?.fields || []);
  if (fields.some(field => {
    const value = configuration.values[field.id];
    if (field.type === 'number') return !Number.isFinite(value) || value < field.min || value > field.max;
    if (field.type === 'select') return !field.options.includes(value);
    return typeof value !== 'boolean';
  })) issues.push('Correct the illustrative parameter values.');
  return issues;
}
export function captureExperiment(state, step, record) {
  const view = experimentView(state, step, record);
  const issues = experimentIssues(state, step, view.configuration);
  if (issues.length) throw new Error(issues.join(' '));
  const snapshot = freezeConfiguration(view.configuration);
  view.bundle.attempts.push(snapshot);
  view.bundle.editing = false;
  state.experimentMonitor = { protocolId: state.protocolId, stepId: step.id, name: step.name, operation: step.operation, configuration: snapshot };
  return snapshot;
}

export function experimentDeviceGroups(state, step, configuration) {
  const groups = [...step.required.map(capability => ({ capability, required: true })), ...step.optional.filter(capability => !step.required.includes(capability)).map(capability => ({ capability, required: false }))];
  const coverage = declaredCoverage(groups.map(group => group.capability), configuration.participants.filter(id => state.selectedDevices.includes(id)));
  return groups.map((group, index) => ({ ...group, options: devices.filter(device => state.selectedDevices.includes(device.id) && device.capabilities.includes(group.capability)), covered: coverage[index].providers.some(device => device.available) }));
}
