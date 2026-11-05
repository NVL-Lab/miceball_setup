import { test } from 'node:test';
import assert from 'node:assert/strict';
import {configurationIdentity} from '../src/miceball_gui/static/configuration-values.mjs';

globalThis.document = {documentElement: {dataset: {runtime: 'connected'}}};
const {createDemo, devices, operations} = await import('../src/miceball_gui/static/protocol-demo.mjs');
const {applyControllerSnapshot, launchSessionDemo} = await import('../src/miceball_gui/static/session-context.mjs');
const {prepareFreeOperation, selectedStepContext, actOnSessionStep, requestExperimentStop} = await import('../src/miceball_gui/static/session-demo.mjs');
const {experimentView, updateExperiment} = await import('../src/miceball_gui/static/experiment-demo.mjs');
const {activeParameterSnapshot} = await import('../src/miceball_gui/static/experiment-parameters.mjs');
const {createStorageDemo} = await import('../src/miceball_gui/static/storage-demo.mjs');
const {createServicesDemo, beginShutdownPreview} = await import('../src/miceball_gui/static/services-demo.mjs');
const declaration = {device_id: 'camera', scientific_products: [{data_product_id: 'frames'}]};
function snapshot() {
  return {instance_id: 'controller-instance', status: {session_id: 'session', session_state: 'running', active_experiment_id: null, experiment_lifecycle_evidence: []},
    configuration: {selected_devices: [structuredClone(declaration)], expected_runtime_participants: [{component_type: 'acquisition_node', component_id: 'node'}],
      session_parameters: {experimenter: 'Accepted scientist', name: 'Accepted name'}, protocol_reference: null}, experiments: []};
}

test('connected preparation begins without fictional devices, protocols, results or parameter defaults', () => {
  const state = createDemo();
  assert.deepEqual(state.protocols, []);
  assert.deepEqual(devices, []);
  assert.equal(operations.filter(op => !op.unavailable).length, 1);
  applyControllerSnapshot(state, snapshot());
  prepareFreeOperation(state, 'acquisition');
  const {step,record} = selectedStepContext(state);
  assert.deepEqual(record.results, []);
  assert.notEqual(record.status, 'completed');
  const view = experimentView(state, step, record);
  assert.equal(view.configuration.durationSeconds, null);
  assert.deepEqual(view.configuration.values, {});
  assert.throws(() => launchSessionDemo(state, {}), /Controller/);
  assert.throws(() => actOnSessionStep(state, step.id, 'run'), /Controller/);
  assert.throws(() => requestExperimentStop(state), /Controller/);
});

test('accepted identity and executed values survive working edits, completion and detached readback', () => {
  devices.push({id: configurationIdentity('node', 'camera'), nodeId: 'node', declaration: structuredClone(declaration)});
  const state = createDemo(), original = snapshot();
  applyControllerSnapshot(state, original);
  original.configuration.session_parameters.name = 'Changed externally';
  assert.equal(state.activeSession.identity.name, 'Accepted name');
  assert.deepEqual(state.activeSession.selectedDevices, [configurationIdentity('node', 'camera')]);
  prepareFreeOperation(state, 'acquisition');
  const {step,record} = selectedStepContext(state);
  updateExperiment(state, step, record, {durationSeconds: 12});
  state.submittedExperiment = {stepId: step.id, experimentId: 'recording'};
  const running = snapshot(); running.status.active_experiment_id = 'recording';
  running.experiments = [{experiment_id: 'recording', scientific_outputs: [], configuration: {
    duration_s: 12, participating_devices: {node: ['camera']}, device_configurations: {}, recording_budgets: {node: 1000}, preservation_budget_bytes: 1000}}];
  applyControllerSnapshot(state, running);
  record.experiment.working.durationSeconds = 999;
  assert.equal(activeParameterSnapshot(state).configuration.durationSeconds, 12);
  assert.throws(() => updateExperiment(state, step, record, {durationSeconds: 3}), /read-only/);
  running.status.active_experiment_id = null;
  running.status.experiment_lifecycle_evidence = [{experiment_id: 'recording', event_type: 'experiment_stop', sequence: 1, session_time_s: 12}];
  applyControllerSnapshot(state, running);
  assert.equal(record.status, 'completed');
  assert.equal(activeParameterSnapshot(state).source, 'Fixed executed-attempt configuration');
  assert.deepEqual(record.results, []); // Lifecycle completion is not scientific-result retrieval.
  const detached = activeParameterSnapshot(state); detached.configuration.durationSeconds = 500;
  assert.equal(activeParameterSnapshot(state).configuration.durationSeconds, 12);
  const first = structuredClone(record.experiment.attempts[0]);
  state.submittedExperiment = {stepId: step.id, experimentId: 'second-recording'};
  running.experiments.push({...structuredClone(running.experiments[0]), experiment_id: 'second-recording',
    configuration: {...structuredClone(running.experiments[0].configuration), duration_s: 15}});
  running.status.active_experiment_id = 'second-recording';
  running.status.experiment_lifecycle_evidence.push({experiment_id: 'second-recording', event_type: 'experiment_start', sequence: 2, session_time_s: 15});
  applyControllerSnapshot(state, running);
  applyControllerSnapshot(state, running);
  assert.equal(record.attempts.length, 2);
  assert.deepEqual(record.experiment.attempts[0], first);
  assert.equal(record.experiment.attempts[1].durationSeconds, 15);
  assert.equal(record.history.length, 2);
  assert.equal(state.activeSession.freeOperations.length, 1);
  devices.length = 0;
});

test('missing application definitions and ambiguous node ownership never invent an executable checklist or selection', () => {
  const state = createDemo(), readback = snapshot();
  readback.configuration.protocol_reference = 'Unavailable application protocol';
  applyControllerSnapshot(state, readback);
  assert.deepEqual(state.activeSession.protocols, []);
  assert.notEqual(state.activeSession.protocolId, null);
  assert.deepEqual(state.activeSession.selectedDevices, []);
  assert.equal(state.controllerSnapshot.configuration.protocol_reference, 'Unavailable application protocol');
});

test('unconnected Storage and Services expose unknown data without simulated outcomes', () => {
  const storage = createStorageDemo(true), services = createServicesDemo(true);
  assert.deepEqual(storage.sessions, []);
  assert.ok(services.services.every(service => service.current === false && service.confirmed === null));
  services.administrator = true;
  assert.throws(() => beginShutdownPreview(services), /unavailable/);
});

test('authoritative readback preserves delimiter-containing coordinates and distinct executed values', () => {
  const declarations = [{device_id: 'a.b'}, {device_id: 'a'}, {device_id: 'b/c'}, {device_id: 'c'}];
  const coordinates = [['node', 'a.b'], ['node', 'a'], ['a', 'b/c'], ['a/b', 'c']];
  devices.push(...coordinates.map(([nodeId, deviceId], i) => ({id: configurationIdentity(nodeId, deviceId), nodeId, deviceId, declaration: declarations[i]})));
  try {
    const state = createDemo();
    const readback = snapshot();
    readback.configuration.selected_devices = declarations;
    readback.configuration.expected_runtime_participants = ['node', 'a', 'a/b'].map(component_id => ({component_type: 'acquisition_node', component_id}));
    readback.status.active_experiment_id = 'distinct';
    readback.experiments = [{experiment_id: 'distinct', scientific_outputs: [], configuration: {
      duration_s: 2, participating_devices: {node: ['a.b', 'a'], a: ['b/c'], 'a/b': ['c']},
      device_configurations: {node: {'a.b': {c: 2}, a: {'b.c': 9}}, a: {'b/c': {gain: 3}}, 'a/b': {c: {gain: 4}}},
      recording_budgets: {}, preservation_budget_bytes: 1000}}];
    applyControllerSnapshot(state, readback);
    assert.equal(new Set(state.activeSession.selectedDevices).size, 4);
    const values = activeParameterSnapshot(state).configuration.values;
    for (const [coordinates, value] of [[['node', 'a.b', 'c'], 2], [['node', 'a', 'b.c'], 9], [['a', 'b/c', 'gain'], 3], [['a/b', 'c', 'gain'], 4]]) {
      assert.equal(values[configurationIdentity(...coordinates)], value);
    }
  } finally {devices.length = 0;}
});
