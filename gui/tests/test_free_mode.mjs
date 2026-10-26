import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDemo, selectProtocol, coverage, saveProtocol, clone } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo, executionSteps, executionProtocol } from '../src/miceball_gui/static/session-context.mjs';
import { sessionProgress, selectedStepContext, freeOperationChoices, prepareFreeOperation, actOnSessionStep, sessionStepView, monitoredExperiment, requestExperimentStop, finishExperimentStop } from '../src/miceball_gui/static/session-demo.mjs';
import { experimentView, updateExperiment, prepareExperimentRepeat } from '../src/miceball_gui/static/experiment-demo.mjs';

function launchFree(devices) {
  const state = createDemo();
  selectProtocol(state, null);
  if (devices) state.selectedDevices = devices;
  launchSessionDemo(state, { name: 'Free demo', animal: 'Demo-42' });
  return state;
}

test('None launches an empty Free Mode context, not a fabricated protocol, with fixed mode and devices', () => {
  const state = createDemo();
  selectProtocol(state, null);
  assert.deepEqual(coverage(state).required, []);
  const count = state.protocols.length;
  launchSessionDemo(state, { name: 'Free demo' });
  assert.equal(state.activeSession.protocolId, null);
  assert.deepEqual(state.activeSession.protocols, []);
  assert.equal(state.protocols.length, count);
  assert.equal(executionProtocol(state), null);
  assert.deepEqual(executionSteps(state), []);
  assert.equal(selectedStepContext(state).step, undefined);
  assert.equal(monitoredExperiment(state).monitor, undefined);
  const pool = [...state.activeSession.selectedDevices];
  selectProtocol(state, 'cabmi'); state.selectedDevices = [];
  assert.equal(state.activeSession.protocolId, null);
  assert.deepEqual(state.activeSession.selectedDevices, pool);
  assert.deepEqual(executionSteps(state), []);
});

test('Free Mode reuses Experiment configuration, distinct attempts, Stop and retained history after Setup changes', () => {
  const state = launchFree();
  const step = prepareFreeOperation(state, 'baseline');
  const { record } = selectedStepContext(state);
  assert.equal(record.results.length, 0);
  updateExperiment(state, step, record, { durationSeconds: 321 });
  actOnSessionStep(state, step.id, 'run');
  const executed = experimentView(state, step, record).configuration;
  selectProtocol(state, 'cabmi'); state.selectedDevices = [];
  const draft = clone(state.protocols[0]); draft.steps = []; saveProtocol(state, draft);
  requestExperimentStop(state); finishExperimentStop(state);
  assert.equal(record.status, 'completed');
  assert.equal(executed.durationSeconds, 321);
  assert.equal(experimentView(state, step, record).configuration, executed);
  prepareExperimentRepeat(state, step, record);
  updateExperiment(state, step, record, { durationSeconds: 222 });
  actOnSessionStep(state, step.id, 'repeat'); actOnSessionStep(state, step.id, 'complete');
  assert.equal(record.results.length, 2);
  assert.equal(new Set(record.attempts.map(attempt => attempt.id)).size, 2);
  assert.equal(record.results[0].attemptId, record.attempts[0].id);
  assert.equal(record.results[1].attemptId, record.attempts[1].id);
  assert.equal(record.experiment.attempts[0].durationSeconds, 321);
  assert.equal(record.experiment.attempts[1].durationSeconds, 222);
  assert.equal(monitoredExperiment(state).monitor.attemptId, record.attempts[1].id);
});

test('Free Mode can choose independent Analysis and Experiment occurrences without protocol review or a next-step requirement', () => {
  const state = launchFree();
  const first = prepareFreeOperation(state, 'roi');
  actOnSessionStep(state, first.id, 'run'); actOnSessionStep(state, first.id, 'complete');
  const retained = clone(sessionProgress(state).steps[first.id]);
  const second = prepareFreeOperation(state, 'baseline');
  actOnSessionStep(state, second.id, 'run'); actOnSessionStep(state, second.id, 'complete');
  const third = prepareFreeOperation(state, 'roi');
  assert.notEqual(first.id, third.id);
  actOnSessionStep(state, third.id, 'run'); actOnSessionStep(state, third.id, 'complete');
  sessionProgress(state).selectedId = first.id;
  actOnSessionStep(state, first.id, 'repeat'); actOnSessionStep(state, first.id, 'complete');
  assert.equal(sessionProgress(state).steps[second.id].status, 'completed');
  assert.equal(sessionProgress(state).steps[third.id].status, 'completed');
  assert.deepEqual(sessionProgress(state).steps[first.id].results[0], retained.results[0]);
  assert.equal(executionProtocol(state), null);
});

test('compatibility uses declared capabilities in the fixed pool, not current readiness or invented operations', () => {
  const state = launchFree(['orca', 'holograph']);
  const holo = freeOperationChoices(state).find(item => item.operation.id === 'holo');
  assert.equal(holo.compatible, true);
  const step = prepareFreeOperation(state, 'holo');
  assert.equal(sessionStepView(state, step).ready, false);
  assert.throws(() => actOnSessionStep(state, step.id, 'run'), /not available/);
  assert.throws(() => prepareFreeOperation(state, 'loop'), /not compatible/);
  assert.throws(() => prepareFreeOperation(state, 'invented'), /not compatible/);
  state.selectedDevices.push('display', 'reward');
  assert.equal(freeOperationChoices(state).find(item => item.operation.id === 'loop').compatible, false);
  const limited = launchFree(['display']);
  assert.equal(freeOperationChoices(limited).find(item => item.operation.id === 'baseline').compatible, false);
  assert.equal(freeOperationChoices(limited).find(item => item.operation.id === 'roi').compatible, true);
});

test('operation selection during a run cannot change the monitored occurrence or bypass the shared concurrency check', () => {
  const state = launchFree();
  const first = prepareFreeOperation(state, 'baseline');
  actOnSessionStep(state, first.id, 'run');
  const second = prepareFreeOperation(state, 'initial');
  assert.equal(selectedStepContext(state).step.id, second.id);
  assert.equal(monitoredExperiment(state).monitor.stepId, first.id);
  assert.throws(() => actOnSessionStep(state, second.id, 'run'), /not available/);
  requestExperimentStop(state); finishExperimentStop(state);
  assert.equal(sessionProgress(state).steps[first.id].status, 'completed');
  assert.equal(sessionProgress(state).steps[second.id].results.length, 0);
});
