import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemo, clone, preparedProtocol, selectProtocol, devices} from '../src/miceball_gui/static/protocol-demo.mjs';
import {selectParameterContext, resolveParameterContext} from '../src/miceball_gui/static/parameter-context.mjs';
import {launchSessionDemo} from '../src/miceball_gui/static/session-context.mjs';
import {selectedStepContext, actOnSessionStep, requestExperimentStop, finishExperimentStop, prepareFreeOperation} from '../src/miceball_gui/static/session-demo.mjs';
import {copyStepToEdit} from '../src/miceball_gui/static/protocol-demo.mjs';
import {deviceParameterFields, parameterIssue, configuredParameterValue} from '../src/miceball_gui/static/parameter-constraints.mjs';
import {experimentView, experimentIssues, deviceExamples} from '../src/miceball_gui/static/experiment-demo.mjs';

test('retained administrative overrides remain readable but cannot authorize future execution', () => {
  const device = devices[0], previous = deviceExamples[device.id];
  const fields = deviceParameterFields('node', 'technical', {
    service_interval: {type: 'integer', minimum: 1, adjustment_scope: 'administrator'},
    rate: {type: 'number', minimum: 1},
  });
  assert.equal(fields[0].adjustmentScope, 'administrator');
  assert.equal(fields[1].adjustmentScope, 'experimenter');
  try {
    deviceExamples[device.id] = {acquisition: true, fields};
    const state = createDemo(); state.connected = true; state.selectedDevices = [device.id];
    const configuration = {durationSeconds: 2, participants: [device.id], experimentId: 'future',
      preservationBudget: 1000, recordingBudgets: {[device.nodeId]: 1000}, values: {[fields[0].id]: 5}};
    const retained = structuredClone(configuration);
    assert.ok(experimentIssues(state, {required: []}, configuration).some(issue => issue.includes('administrator-only')));
    assert.deepEqual(configuration, retained);
    delete configuration.values[fields[0].id];
    assert.equal(experimentIssues(state, {required: []}, configuration).some(issue => issue.includes('administrator-only')), false);
  } finally { deviceExamples[device.id] = previous; }
});

test('configured readback distinguishes scope, null, absent, invalid and unavailable without mutating overrides', () => {
  const device = {nodeId: 'node', deviceId: 'camera', available: true};
  const field = deviceParameterFields('node', 'camera', {fps: {type: 'number', nullable: true, exclusive_minimum: 0}})[0];
  const state = {inventory: {node: {configured_parameters: {scope: 'installation', session_id: null,
    values: {camera: {fps: null}}}}}};
  const before = structuredClone(state);
  assert.deepEqual(configuredParameterValue(state, device, field), {available: true, value: null});
  assert.deepEqual(configuredParameterValue(state, device, field, 'session'), {available: false});
  assert.deepEqual(state, before);
  state.inventory.node.configured_parameters = {scope: 'session', session_id: 'session', values: {camera: {fps: 30}}};
  assert.deepEqual(configuredParameterValue(state, device, field, 'session'), {available: true, value: 30});
  assert.deepEqual(configuredParameterValue(state, device, field, 'other'), {available: false});
  assert.deepEqual(configuredParameterValue(state, {...device, available: false}, field, 'session'), {available: false});
  for (const values of [{}, {fps: -1}, {fps: true}, {fps: Infinity}]) {
    state.inventory.node.configured_parameters.values.camera = values;
    assert.deepEqual(configuredParameterValue(state, device, field, 'session'), {available: false});
  }
  delete state.inventory.node.configured_parameters;
  assert.deepEqual(configuredParameterValue(state, device, field), {available: false});
  state.inventory.node.configured_parameters = {scope: 'installation', session_id: null, values: {}};
  assert.deepEqual(configuredParameterValue(state, {...device, deviceId: '__proto__'},
    {...field, name: '__proto__'}), {available: false});
});

test('Setup preparation and Step editor use existing working values, fixed Session and attempts remain isolated', () => {
  const state = createDemo();
  const protocol = state.protocols[0];
  const step = copyStepToEdit(state, protocol.steps[2]);
  protocol.steps[2] = step;
  state.setupParameterStepId = step.id;
  selectParameterContext(state, {kind: 'setup', origin: 'setup'});
  const setup = resolveParameterContext(state);
  setup.update({durationSeconds: 321});
  assert.equal(resolveParameterContext(state).configuration.durationSeconds, 321);
  assert.equal(preparedProtocol(state).steps[2].parameters.durationSeconds, 321);
  launchSessionDemo(state, {name: 'Fixed'});
  setup.update({durationSeconds: 999});
  selectParameterContext(state, {kind: 'session', origin: 'session'});
  assert.equal(resolveParameterContext(state).configuration.durationSeconds, 321);
  const {step: activeStep} = selectedStepContext(state);
  actOnSessionStep(state, activeStep.id, 'run');
  selectParameterContext(state, {kind: 'experiment', origin: 'experiment'});
  let executed = resolveParameterContext(state);
  assert.equal(executed.readOnly, true);
  assert.equal(executed.configuration.durationSeconds, 321);
  assert.throws(() => executed.update({durationSeconds: 1}), /read-only/);
  requestExperimentStop(state); finishExperimentStop(state);
  executed = resolveParameterContext(state);
  assert.match(executed.source, /executed/);
  assert.equal(executed.configuration.durationSeconds, 321);
  const saved = clone(state.definitions[0]);
  selectParameterContext(state, {kind: 'step', origin: 'protocol-editor', step: {...saved, definitionId: saved.id}});
  assert.equal(resolveParameterContext(state), null, 'No settings are invented for an unconfigured immutable definition');
  const draft = copyStepToEdit(state, saved);
  selectParameterContext(state, {kind: 'step', origin: 'protocol-editor', step: draft});
  resolveParameterContext(state).update({durationSeconds: 42});
  assert.equal(draft.parameters.durationSeconds, 42);
  assert.equal(state.definitions[0].parameters, undefined);
});

test('adapter constraints retain typed choices, defaults, null and inclusive/exclusive boundaries', () => {
  const [choice, number, flag, text] = deviceParameterFields('node', 'camera', {
    mode: {type: 'integer', allowed_values: [0, 2]},
    fps: {type: 'number', minimum: 0, exclusive_minimum: 0, maximum: 3, nullable: true},
    flag: {type: 'boolean'}, text: {type: 'string'},
  });
  assert.deepEqual(choice.allowedValues, [0, 2]);
  assert.equal(parameterIssue(choice, 0), '');
  assert.ok(parameterIssue(choice, '0'));
  assert.ok(parameterIssue(choice, 1));
  assert.equal(parameterIssue(number, null), '');
  assert.ok(parameterIssue(number, 0));
  assert.equal(parameterIssue(number, 3), '');
  assert.ok(parameterIssue(number, 3.1));
  assert.equal(parameterIssue(flag, false), '');
  assert.ok(parameterIssue(flag, 0));
  assert.equal(parameterIssue(text, '\r\n\0\ud800"\\'), '');
  assert.equal('value' in number, false, 'Unavailable resolved defaults are never manufactured');
  const described = deviceParameterFields('node', 'camera', {
    fps: {type: 'number', nullable: true, null_description: 'Do not request a value from the device'},
    other: {type: 'number', nullable: true, null_description: {unexpected: 'metadata'}},
  });
  assert.equal(described[0].nullDescription, 'Do not request a value from the device');
  assert.equal(described[1].nullDescription, 'Use the adapter-defined empty value');
  assert.throws(() => deviceParameterFields('node', 'device', {unknown: {type: 'unsupported'}}), /Unsupported/);
});

test('Free Mode captures Setup preparation once while later Setup edits remain separate', () => {
  const state = createDemo(); selectProtocol(state, null);
  state.setupOperation = {id: 'setup-baseline', name: 'Baseline', operation: 'baseline', required: ['imaging_camera'], optional: [], mandatory: true};
  selectParameterContext(state, {kind: 'setup', origin: 'setup'});
  const future = resolveParameterContext(state);
  future.update({durationSeconds: 17});
  launchSessionDemo(state, {name: 'Free'});
  future.update({durationSeconds: 99});
  prepareFreeOperation(state, 'baseline');
  selectParameterContext(state, {kind: 'session', origin: 'session'});
  assert.equal(resolveParameterContext(state).configuration.durationSeconds, 17);
});

test('loading explicit Step participants preserves preferences and rejects execution outside the fixed pool', () => {
  const state = createDemo(); state.selectedDevices = [];
  const step = {...state.protocols[0].steps[2], parameters: {durationSeconds: 3, participants: ['orca'], values: {}}};
  const before = clone(step);
  const view = experimentView(state, step, {status: 'ready'});
  assert.deepEqual(view.configuration.participants, ['orca']);
  assert.ok(experimentIssues(state, step, view.configuration).some(issue => issue.includes('outside this Session device pool')));
  assert.deepEqual(step, before);
});
