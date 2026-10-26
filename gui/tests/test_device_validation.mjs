import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDemo, clone, selectProtocol } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo, executionSteps } from '../src/miceball_gui/static/session-context.mjs';
import { selectedStepContext, actOnSessionStep, sessionProgress, prepareFreeOperation, selectRecording } from '../src/miceball_gui/static/session-demo.mjs';
import { experimentView, updateExperiment } from '../src/miceball_gui/static/experiment-demo.mjs';
import { deviceValidationEligibility, startDeviceValidation, stopDeviceValidation, tickDeviceValidation } from '../src/miceball_gui/static/device-validation-demo.mjs';

function session(free = false, maximum = 5) {
  const state = createDemo();
  state.selectedDevices.push('reward', 'holograph');
  if (free) selectProtocol(state, null);
  launchSessionDemo(state, { animal: 'Demo animal' }, { maxDeviceValidationSeconds: maximum });
  if (free) prepareFreeOperation(state, 'baseline');
  const { step, record } = selectedStepContext(state);
  experimentView(state, step, record);
  return state;
}

test('participating device Validation is independent of editable/completed configuration; running-device compatibility stays unverified', () => {
  const state = session();
  const { step, record } = selectedStepContext(state);
  assert.equal(deviceValidationEligibility(state, 'orca').eligible, true);
  const pending = clone(state.activeSession.sessionDemo);
  assert.equal(startDeviceValidation(state, 'orca', 1000).status, 'running');
  stopDeviceValidation(state);
  assert.deepEqual(state.activeSession.sessionDemo, pending);
  actOnSessionStep(state, step.id, 'run');
  const running = clone(state.activeSession.sessionDemo);
  const refused = startDeviceValidation(state, 'orca', 2000);
  assert.equal(refused.status, 'not-started');
  assert.match(refused.reason, /Compatible concurrent use is not established/);
  stopDeviceValidation(state);
  assert.deepEqual(state.activeSession.sessionDemo, running);
  actOnSessionStep(state, step.id, 'complete');
  assert.equal(experimentView(state, step, record).readOnly, true);
  const completed = clone(state.activeSession.sessionDemo);
  assert.equal(startDeviceValidation(state, 'orca', 3000).status, 'running');
  stopDeviceValidation(state);
  assert.deepEqual(state.activeSession.sessionDemo, completed);
});

test('camera, position and actuator fixtures have distinct outputs and retain exact device identities', () => {
  const state = session();
  const { step, record } = selectedStepContext(state);
  updateExperiment(state, step, record, { participants: ['orca', 'stage', 'reward', 'display', 'holograph'] });
  for (const [id, output] of [['orca', 'image'], ['stage', 'plot'], ['reward', 'actuator'], ['display', 'none']]) {
    const validation = startDeviceValidation(state, id, 1000);
    assert.equal(validation.deviceId, id);
    assert.equal(validation.output, output);
    assert.equal(validation.status, 'running');
    stopDeviceValidation(state);
  }
  assert.equal(startDeviceValidation(state, 'holograph', 1000).status, 'not-started');
});

test('manual Stop freezes updates and creates no scientific or Stop history', () => {
  const state = session(true), before = clone(state.activeSession.sessionDemo), steps = clone(executionSteps(state));
  const validation = startDeviceValidation(state, 'orca', 1000);
  tickDeviceValidation(state, 2000);
  assert.equal(validation.elapsedSeconds, 1);
  assert.equal(validation.updates, 1);
  stopDeviceValidation(state);
  const stopped = clone(validation);
  tickDeviceValidation(state, 9000);
  assert.deepEqual(validation, stopped);
  assert.equal(validation.endedBy, 'manual');
  assert.equal(state.activeSession.deviceValidation, undefined);
  assert.deepEqual(state.activeSession.sessionDemo, before);
  assert.deepEqual(executionSteps(state), steps);
});

test('configured maximum ends Validation automatically; no guessed default or indefinite activity', () => {
  const state = session(false, 2.5);
  const validation = startDeviceValidation(state, 'orca', 1000);
  tickDeviceValidation(state, 3499);
  assert.equal(validation.status, 'running');
  tickDeviceValidation(state, 3500);
  assert.equal(validation.status, 'stopped');
  assert.equal(validation.endedBy, 'maximum-duration');
  assert.equal(validation.elapsedSeconds, 2.5);
  assert.equal(state.activeSession.deviceValidation, undefined);
  for (const maximum of [null, 0, -1]) {
    const unset = session(false, maximum);
    assert.equal(startDeviceValidation(unset, 'orca', 0).status, 'not-started');
    assert.match(unset.activeSession.deviceValidation.reason, /maximum Device Validation duration/);
  }
});

test('Validation cannot modify the fixed pool, configured maximum, recorded input or scientific results', () => {
  const state = session();
  selectRecording(state, 'step-1', { kind: 'file', name: 'example', entries: [{ name: 'example' }] });
  actOnSessionStep(state, 'step-1', 'accept-recording');
  const before = clone(state.activeSession.sessionDemo), pool = [...state.activeSession.selectedDevices];
  state.selectedDevices = []; state.protocolId = null;
  startDeviceValidation(state, 'orca', 1000);
  tickDeviceValidation(state, 6000);
  assert.deepEqual(state.activeSession.sessionDemo, before);
  assert.deepEqual(state.activeSession.selectedDevices, pool);
  assert.equal(state.activeSession.sessionValues.maxDeviceValidationSeconds, 5);
  assert.equal(state.activeSession.protocolId, 'cabmi');
  assert.equal(deviceValidationEligibility(state, 'invented').eligible, false);
});

test('unsupported concurrent use cannot be silently enabled by starting an Experiment after Validation', () => {
  const state = session(), { step, record } = selectedStepContext(state);
  const before = clone(record);
  startDeviceValidation(state, 'orca', 1000);
  assert.throws(() => actOnSessionStep(state, step.id, 'run'), /Compatible concurrent use is unverified/);
  assert.deepEqual(record, before);
  stopDeviceValidation(state);
  actOnSessionStep(state, step.id, 'run');
  assert.equal(record.status, 'running');
});
