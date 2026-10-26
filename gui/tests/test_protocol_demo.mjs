import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sessionProgress, sessionStepView, actOnSessionStep, selectedStepContext, monitoredExperiment, requestExperimentStop, finishExperimentStop } from '../src/miceball_gui/static/session-demo.mjs';
import { experimentTemplates, experimentView, updateExperiment, loadExperimentTemplate, saveExperimentTemplate, prepareExperimentRepeat, experimentDeviceGroups } from '../src/miceball_gui/static/experiment-demo.mjs';
import { devices } from '../src/miceball_gui/static/protocol-demo.mjs';
import { traceExamples, distributionExample } from '../src/miceball_gui/static/output-examples.mjs';
import { createDemo, selectProtocol, selectTemplate, coverage, saveProtocol, clone, moveStep, assignCapability, preparedSteps, savedOccurrence, copyStepToEdit, saveReusableStep } from '../src/miceball_gui/static/protocol-demo.mjs';

test('optional step inclusion updates requirements without editing the protocol', () => {
  const state = createDemo();
  const saved = clone(state.protocols[0]);
  assert.equal(coverage(state).required.some(r => r.capability === 'holographic_stimulation'), false);
  state.included.push('step-3');
  assert.equal(coverage(state).required.find(r => r.capability === 'holographic_stimulation').providers.length, 0);
  state.included = state.included.filter(id => id !== 'step-3');
  assert.equal(coverage(state).required.some(r => r.capability === 'holographic_stimulation'), false);
  assert.deepEqual(state.protocols[0], saved);
  assert.equal(coverage(state).required.some(r => r.capability === 'imaging_camera'), true);
});
test('templates filter by protocol and supply editable device and step defaults', () => {
  const state = createDemo();
  selectTemplate(state, 'holographic');
  assert.ok(state.included.includes('step-3'));
  assert.ok(state.selectedDevices.includes('reward'));
  state.selectedDevices.push('extra');
  assert.ok(state.selectedDevices.includes('extra'));
  selectProtocol(state, 'reference');
  assert.equal(state.templateId, '');
  selectTemplate(state, 'standard');
  assert.equal(state.templateId, '');
  // UI exposes only associated templates; an incompatible template must not apply defaults.
  assert.ok(state.selectedDevices.includes('extra'));
});
test('declared coverage and availability remain separate with multiple and extra devices', () => {
  const state = createDemo();
  assert.equal(state.templateId, '');
  assert.equal(coverage(state).required.find(r => r.capability === 'reward_delivery').providers.length, 0);
  state.selectedDevices.push('reward', 'holograph');
  state.included.push('step-3');
  const result = coverage(state);
  assert.ok(result.required.every(r => r.providers.length));
  assert.equal(result.unavailable[0].id, 'holograph');
  assert.ok(state.selectedDevices.includes('stage'));
  assert.ok(state.selectedDevices.includes('logitech') && state.selectedDevices.includes('extra'));
  assert.ok(!result.required.some(r => r.capability === 'behavior_video'));
});
test('personal edits save order and duplicate operations while references cannot be overwritten', () => {
  const state = createDemo();
  const copy = clone(state.protocols[1]);
  assert.throws(() => saveProtocol(state, copy));
  copy.id = 'my-copy'; copy.protected = false; copy.name = 'My protocol';
  copy.steps.push({ ...clone(copy.steps[0]), id: 'repeat' });
  copy.steps.reverse();
  saveProtocol(state, copy);
  assert.equal(state.protocolId, 'my-copy');
  assert.equal(state.templateId, '');
  assert.equal(state.protocols.find(p => p.id === 'my-copy').steps[0].id, 'repeat');
  assert.equal(state.protocols.find(p => p.id === 'reference').steps.length, 3);
});

test('identity-based reorder preserves every field through bottom/top and adjacent moves', () => {
  const state = createDemo();
  const draft = clone(state.protocols[0]);
  draft.steps[3] = copyStepToEdit(state, draft.steps[3]);
  draft.steps[3].configuration = 'Keep demonstration settings';
  const original = clone(draft.steps);
  moveStep(draft.steps, 'step-6', 'step-0');
  assert.equal(draft.steps[0].id, 'step-6');
  moveStep(draft.steps, 'step-6', 'step-5', true);
  assert.equal(draft.steps.at(-1).id, 'step-6');
  moveStep(draft.steps, 'step-3', 'step-2');
  assert.equal(draft.steps[2].id, 'step-3');
  for (const step of original) assert.deepEqual(draft.steps.find(s => s.id === step.id), step);
  assert.equal(state.protocols[0].steps[2].id, 'step-2');
  saveProtocol(state, draft);
  assert.equal(state.protocols[0].steps[2].id, 'step-3');
});

test('capability selections move between lists, deduplicate, remove, and survive Save', () => {
  const state = createDemo();
  const draft = clone(state.protocols[0]);
  const step = draft.steps[0] = copyStepToEdit(state, draft.steps[0]);
  assignCapability(step, 'required', 'behavior_video', true);
  assignCapability(step, 'required', 'behavior_video', true);
  assert.equal(step.required.filter(id => id === 'behavior_video').length, 1);
  assert.ok(!step.optional.includes('behavior_video'));
  assignCapability(step, 'optional', 'imaging_camera', true);
  assert.ok(!step.required.includes('imaging_camera'));
  assert.ok(step.optional.includes('imaging_camera'));
  assignCapability(step, 'required', 'behavior_video', false);
  assert.deepEqual(step.required, []);
  saveProtocol(state, draft);
  assert.deepEqual(state.protocols[0].steps[0].optional, ['imaging_camera']);
  assert.ok(!coverage(state).required.some(row => row.capability === 'behavior_video'));
});

test('saved definitions are immutable, repeated occurrences retain independent identity', () => {
  const state = createDemo();
  const definition = state.definitions[0];
  assert.throws(() => { definition.name = 'Changed'; }, TypeError);
  assert.throws(() => { definition.required.push('other'); }, TypeError);
  const draft = clone(state.protocols[0]);
  draft.steps.push(savedOccurrence(state, definition.id, 'repeat'));
  moveStep(draft.steps, 'repeat', 'step-0');
  assert.equal(draft.steps[0].definitionId, draft.steps[1].definitionId);
  draft.steps.splice(1, 1);
  // Even a modified occurrence snapshot cannot overwrite its saved definition.
  draft.steps[0].name = 'Attempted mutation';
  saveProtocol(state, draft);
  assert.equal(state.protocols[0].steps[0].name, definition.name);
  assert.equal(state.protocols[0].steps[0].id, 'repeat');
  assert.equal(state.definitions[0], definition);
});

test('explicit reusable save is personal, globally unique, and independent of protocol save/cancel', () => {
  const state = createDemo();
  const original = clone(state.protocols[0]);
  const working = copyStepToEdit(state, original.steps[0]);
  assert.equal(working.name, 'Initial imaging - copy');
  working.description = 'Personal demonstration settings';
  const saved = saveReusableStep(state, working, 'Taylor');
  assert.ok(saved.definitionId);
  assert.equal(saved.operation, 'initial');
  assert.ok(preparedSteps(state, 'Taylor').some(item => item.id === saved.definitionId));
  assert.ok(!preparedSteps(state, 'Morgan').some(item => item.id === saved.definitionId));
  assert.throws(() => saveReusableStep(state, { ...working, name: ` ${working.name.toUpperCase()} ` }, 'Morgan'), /already exists/);
  assert.throws(() => saveReusableStep(state, saved, 'Taylor'), /Copy/);
  assert.deepEqual(state.protocols[0], original);
  const count = state.definitions.length;
  const draft = clone(original);
  draft.steps[0] = copyStepToEdit(state, saved);
  saveProtocol(state, draft);
  assert.equal(state.definitions.length, count);
  assert.equal(state.protocols[0].steps[0].definitionId, undefined);
  assert.equal(state.definitions.find(item => item.id === saved.definitionId).description, working.description);
});

test('optional coverage reports all selected providers and missing coverage without required blockers', () => {
  const state = createDemo();
  assert.equal(coverage(state).optional.find(row => row.capability === 'behavior_video').providers.length, 2);
  const required = clone(coverage(state).required);
  state.selectedDevices = state.selectedDevices.filter(id => !['logitech', 'extra'].includes(id));
  assert.equal(coverage(state).optional.find(row => row.capability === 'behavior_video').providers.length, 0);
  assert.deepEqual(coverage(state).required, required);
});

test('Session preview uses the selected protocol and stable independent step occurrences', () => {
  const state = createDemo();
  selectProtocol(state, 'reference');
  const progress = sessionProgress(state);
  assert.equal(Object.keys(progress.steps).length, 3);
  const draft = clone(state.protocols[1]);
  draft.id = 'custom'; draft.name = 'Different scientific workflow'; draft.protected = false;
  draft.steps.push(savedOccurrence(state, draft.steps[0].definitionId, 'repeat-initial'));
  saveProtocol(state, draft);
  const custom = sessionProgress(state);
  assert.equal(custom.steps['repeat-initial'].status, 'not-started');
  assert.equal(custom.steps['step-0'].status, 'completed');
  custom.selectedId = 'repeat-initial';
  moveStep(state.protocols.at(-1).steps, 'repeat-initial', 'step-0');
  assert.equal(sessionProgress(state).selectedId, 'repeat-initial');
  assert.equal(state.protocols.at(-1).steps[0].id, 'repeat-initial');
  selectProtocol(state, 'reference');
  assert.equal(sessionProgress(state), progress);
});

test('repeat review simulation retains results and supports explicit validation without editing definitions', () => {
  const state = createDemo();
  const original = clone(state.protocols);
  const progress = sessionProgress(state);
  const previousResults = clone(progress.steps['step-1'].results);
  actOnSessionStep(state, 'step-0', 'repeat');
  assert.equal(progress.steps['step-0'].status, 'running');
  assert.equal(progress.steps['step-1'].status, 'needs-review');
  assert.match(progress.steps['step-1'].reviewReason, /not automatic scientific invalidation/);
  assert.deepEqual(progress.steps['step-1'].results, previousResults);
  actOnSessionStep(state, 'step-0', 'complete');
  assert.equal(progress.steps['step-0'].results.length, 2);
  actOnSessionStep(state, 'step-1', 'validate');
  assert.equal(progress.steps['step-1'].status, 'completed');
  assert.deepEqual(progress.steps['step-1'].results, previousResults);
  assert.match(progress.steps['step-1'].history.at(-1), /No Controller acceptance/);
  assert.deepEqual(state.protocols, original);
});

test('Session actions reflect simulated capability availability, operation support and optionality', () => {
  const state = createDemo();
  const protocol = state.protocols[0];
  const baseline = protocol.steps[2], holo = protocol.steps[3], loop = protocol.steps[6];
  assert.equal(sessionStepView(state, baseline).status, 'ready');
  assert.equal(sessionStepView(state, loop).status, 'unavailable');
  assert.ok(sessionStepView(state, baseline).actions.includes('run'));
  assert.ok(!sessionStepView(state, baseline).actions.includes('load'));
  assert.throws(() => actOnSessionStep(state, baseline.id, 'skip'), /not available/);
  assert.throws(() => actOnSessionStep(state, loop.id, 'run'), /not available/);
  assert.equal(sessionStepView(state, holo).status, 'skipped');
  state.included.push(holo.id);
  assert.equal(sessionStepView(state, holo).status, 'unavailable');
  actOnSessionStep(state, holo.id, 'skip');
  assert.equal(sessionStepView(state, holo).status, 'skipped');
  assert.ok(state.included.includes(holo.id));
  actOnSessionStep(state, 'step-1', 'load');
  assert.equal(sessionProgress(state).steps['step-1'].results.at(-1).origin, 'Simulated previous result');
});

test('out-of-order completion requests downstream review while preserving skipped steps and results', () => {
  const state = createDemo();
  const steps = state.protocols[0].steps;
  actOnSessionStep(state, 'step-4', 'run');
  actOnSessionStep(state, 'step-4', 'complete');
  assert.equal(sessionStepView(state, steps[2]).status, 'ready');
  assert.equal(sessionStepView(state, steps[3]).status, 'skipped');
  assert.equal(sessionStepView(state, steps[4]).status, 'completed');
  const previous = clone(sessionProgress(state).steps['step-4']);
  actOnSessionStep(state, 'step-2', 'run');
  actOnSessionStep(state, 'step-2', 'complete');
  const downstream = sessionStepView(state, steps[4]);
  assert.equal(downstream.status, 'needs-review');
  assert.ok(downstream.actions.includes('validate') && downstream.actions.includes('repeat'));
  assert.match(downstream.record.reviewReason, /completed/);
  assert.deepEqual(downstream.record.results, previous.results);
  assert.deepEqual(downstream.record.history.slice(0, previous.history.length), previous.history);
  assert.equal(sessionStepView(state, steps[3]).status, 'skipped');
  assert.equal(sessionStepView(state, steps[5]).status, 'not-started');
  actOnSessionStep(state, 'step-4', 'validate');
  assert.equal(sessionStepView(state, steps[4]).status, 'completed');
  assert.deepEqual(downstream.record.results, previous.results);
});

test('sequential completion leaves later unstarted and skipped steps unchanged', () => {
  const state = createDemo();
  const before = clone(sessionProgress(state));
  actOnSessionStep(state, 'step-2', 'run');
  actOnSessionStep(state, 'step-2', 'complete');
  for (const id of ['step-3', 'step-4', 'step-5', 'step-6']) {
    assert.deepEqual(sessionProgress(state).steps[id], before.steps[id]);
  }
  assert.equal(sessionStepView(state, state.protocols[0].steps[3]).status, 'skipped');
});

test('loading a replacement result uses the same downstream review behavior', () => {
  const state = createDemo();
  actOnSessionStep(state, 'step-4', 'run');
  actOnSessionStep(state, 'step-4', 'complete');
  const results = clone(sessionProgress(state).steps['step-4'].results);
  actOnSessionStep(state, 'step-1', 'load');
  assert.equal(sessionProgress(state).steps['step-4'].status, 'needs-review');
  assert.deepEqual(sessionProgress(state).steps['step-4'].results, results);
});

test('simulated running/error/retry preserves earlier mock results and prevents concurrent demo runs', () => {
  const state = createDemo();
  const original = clone(state.protocols[0].steps[0]);
  const progress = sessionProgress(state);
  actOnSessionStep(state, 'step-0', 'repeat');
  assert.throws(() => actOnSessionStep(state, 'step-2', 'run'), /not available/);
  actOnSessionStep(state, 'step-0', 'error');
  assert.equal(progress.steps['step-0'].status, 'error');
  assert.equal(progress.steps['step-0'].results.length, 1);
  actOnSessionStep(state, 'step-0', 'repeat');
  actOnSessionStep(state, 'step-0', 'complete');
  assert.equal(progress.steps['step-0'].results.length, 2);
  assert.deepEqual(state.protocols[0].steps[0], original);
});

test('Parameters context follows Session selection and working values survive revisiting steps', () => {
  const state = createDemo();
  const progress = sessionProgress(state);
  progress.selectedId = 'step-2';
  const { step, record } = selectedStepContext(state);
  updateExperiment(state, step, record, { durationSeconds: 360 });
  progress.selectedId = 'step-1';
  assert.equal(selectedStepContext(state).step.operation, 'roi');
  progress.selectedId = 'step-2';
  assert.equal(selectedStepContext(state).record, record);
  assert.equal(experimentView(state, step, record).configuration.durationSeconds, 360);
  assert.equal(experimentView(state, step, record).bundle.templateId, '');
  actOnSessionStep(state, step.id, 'run');
  assert.equal(state.experimentMonitor.configuration.durationSeconds, 360);
});

test('Experiment templates load copies and personal saves never overwrite laboratory or Session templates', () => {
  const state = createDemo();
  const sessionTemplates = clone(state.templates), definitions = clone(state.definitions);
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  const lab = experimentTemplates(state, step.operation, 'Taylor')[0];
  const original = clone(lab.configuration);
  loadExperimentTemplate(state, step, record, lab.id, 'Taylor');
  assert.deepEqual(experimentView(state, step, record).configuration, original);
  assert.notEqual(experimentView(state, step, record).configuration, lab.configuration);
  assert.equal(experimentView(state, step, record).modified, false);
  updateExperiment(state, step, record, { durationSeconds: 450 });
  assert.equal(experimentView(state, step, record).modified, true);
  assert.throws(() => saveExperimentTemplate(state, step, record, lab.name, 'Taylor'), /new personal template name/);
  const personal = saveExperimentTemplate(state, step, record, 'Taylor baseline', 'Taylor');
  assert.equal(personal.owner, 'Taylor');
  assert.equal(personal.configuration.durationSeconds, 450);
  assert.ok(experimentTemplates(state, step.operation, 'Taylor').includes(personal));
  assert.ok(!experimentTemplates(state, step.operation, 'Morgan').includes(personal));
  assert.throws(() => loadExperimentTemplate(state, step, record, personal.id, 'Morgan'), /available Experiment template/);
  assert.deepEqual(lab.configuration, original);
  assert.deepEqual(state.templates, sessionTemplates);
  assert.deepEqual(state.definitions, definitions);
});

test('running and completed Experiment snapshots are read-only and repeat editing cannot rewrite history', () => {
  const state = createDemo();
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  updateExperiment(state, step, record, { durationSeconds: 240 });
  actOnSessionStep(state, step.id, 'run');
  const first = state.experimentMonitor.configuration;
  assert.throws(() => updateExperiment(state, step, record, { durationSeconds: 5 }), /read-only/);
  assert.throws(() => { first.values['orca.exposure'] = 99; }, TypeError);
  assert.throws(() => first.participants.push('reward'), TypeError);
  actOnSessionStep(state, step.id, 'complete');
  assert.throws(() => loadExperimentTemplate(state, step, record, 'experiment-baseline', 'Taylor'), /read-only/);
  prepareExperimentRepeat(state, step, record);
  updateExperiment(state, step, record, { durationSeconds: 480 });
  actOnSessionStep(state, step.id, 'repeat');
  assert.equal(first.durationSeconds, 240);
  assert.equal(state.experimentMonitor.configuration.durationSeconds, 480);
  assert.equal(record.experiment.attempts[0], first);
});

test('Experiment simulation gates duration and participating devices without changing Session inclusion', () => {
  const state = createDemo();
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  const selected = [...state.selectedDevices];
  updateExperiment(state, step, record, { participants: ['display'] });
  assert.ok(sessionStepView(state, step).issues.some(issue => issue.includes('data-acquisition')));
  assert.throws(() => actOnSessionStep(state, step.id, 'run'), /not available/);
  updateExperiment(state, step, record, { participants: ['orca'], durationSeconds: 0 });
  assert.ok(!sessionStepView(state, step).ready);
  updateExperiment(state, step, record, { durationSeconds: 60 });
  assert.ok(sessionStepView(state, step).ready);
  updateExperiment(state, step, record, { participants: ['orca', 'reward'] });
  assert.ok(sessionStepView(state, step).issues.some(issue => issue.includes('not selected in Setup')));
  assert.deepEqual(state.selectedDevices, selected);
});

test('scientific drawing fixtures remain immutable presentation examples', () => {
  assert.throws(() => traceExamples[0].points.push(3), TypeError);
  assert.throws(() => { distributionExample[0] = 999; }, TypeError);
  assert.equal(traceExamples[0].color, '#238e9b');
});

test('loading a template requires confirmation before replacing edited working values', () => {
  const state = createDemo();
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  updateExperiment(state, step, record, { durationSeconds: 360 });
  const edited = clone(experimentView(state, step, record).configuration);
  assert.throws(() => loadExperimentTemplate(state, step, record, 'experiment-baseline', 'Taylor'), /Confirm replacing/);
  assert.deepEqual(experimentView(state, step, record).configuration, edited);
  loadExperimentTemplate(state, step, record, 'experiment-baseline', 'Taylor', true);
  assert.equal(experimentView(state, step, record).configuration.durationSeconds, 900);
  assert.equal(experimentView(state, step, record).workingModified, false);
  loadExperimentTemplate(state, step, record, 'experiment-baseline', 'Taylor');
  assert.equal(experimentView(state, step, record).workingModified, false);
});

test('capability groups expose all Session providers and share Experiment participation with readiness', () => {
  const state = createDemo();
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  const setup = clone(coverage(state));
  updateExperiment(state, step, record, { participants: ['orca', 'logitech', 'extra'] });
  let configuration = experimentView(state, step, record).configuration;
  let groups = experimentDeviceGroups(state, step, configuration);
  assert.deepEqual(groups.find(group => group.capability === 'behavior_video').options.map(device => device.id), ['logitech', 'extra']);
  assert.ok(groups.every(group => group.options.every(device => state.selectedDevices.includes(device.id))));
  assert.ok(groups.find(group => group.required).covered);
  updateExperiment(state, step, record, { participants: ['orca'] });
  groups = experimentDeviceGroups(state, step, experimentView(state, step, record).configuration);
  assert.equal(groups.find(group => !group.required).covered, false);
  assert.equal(sessionStepView(state, step).ready, true);
  updateExperiment(state, step, record, { participants: ['logitech'] });
  assert.equal(sessionStepView(state, step).ready, false);
  assert.throws(() => actOnSessionStep(state, step.id, 'run'), /not available/);
  assert.deepEqual(coverage(state), setup);
  const loop = state.protocols[0].steps[6];
  const reward = experimentDeviceGroups(state, loop, { ...configuration, participants: ['orca', 'display', 'reward'] }).find(group => group.capability === 'reward_delivery');
  assert.equal(reward.options.length, 0);
  assert.equal(reward.covered, false);
});

test('one physical multi-capability device has one participation state across groups', () => {
  const state = createDemo();
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  const camera = devices.find(device => device.id === 'orca');
  const original = camera.capabilities;
  try {
    camera.capabilities = [...original, 'behavior_video'];
    updateExperiment(state, step, record, { participants: ['orca'] });
    let groups = experimentDeviceGroups(state, step, experimentView(state, step, record).configuration);
    assert.ok(groups.every(group => group.options.includes(camera) && group.covered));
    updateExperiment(state, step, record, { participants: [] });
    groups = experimentDeviceGroups(state, step, experimentView(state, step, record).configuration);
    assert.ok(groups.every(group => !group.covered));
  } finally { camera.capabilities = original; }
});

test('Normal Stop preview remains pending until explicit local completion and retains results/configuration', () => {
  const state = createDemo();
  assert.throws(() => requestExperimentStop(state), /No running/);
  const step = state.protocols[0].steps[2], record = sessionProgress(state).steps[step.id];
  actOnSessionStep(state, step.id, 'run');
  actOnSessionStep(state, step.id, 'complete');
  const previous = clone(record.results);
  actOnSessionStep(state, step.id, 'repeat');
  const snapshot = state.experimentMonitor.configuration;
  requestExperimentStop(state);
  assert.equal(record.status, 'running');
  assert.equal(sessionStepView(state, step).stopPending, true);
  assert.deepEqual(record.results, previous);
  assert.throws(() => updateExperiment(state, step, record, { durationSeconds: 1 }), /read-only/);
  const historyLength = record.history.length;
  requestExperimentStop(state);
  assert.equal(record.history.length, historyLength);
  selectProtocol(state, 'reference');
  finishExperimentStop(state);
  assert.equal(state.protocolId, 'reference');
  assert.equal(monitoredExperiment(state).record, record);
  assert.equal(record.status, 'completed');
  assert.equal(record.stopRequested, false);
  assert.deepEqual(record.results.slice(0, previous.length), previous);
  assert.equal(record.results.at(-1).origin, 'Simulated Normal Stop');
  assert.match(record.history.at(-1), /cleanup and preservation remain unverified/);
  assert.equal(state.experimentMonitor.configuration, snapshot);
  assert.throws(() => requestExperimentStop(state), /No running/);
});
