import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDemo, clone, saveProtocol, selectProtocol } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo, executionContext } from '../src/miceball_gui/static/session-context.mjs';
import { sessionProgress, selectedStepContext, sessionStepView, actOnSessionStep, monitoredExperiment, requestExperimentStop, finishExperimentStop } from '../src/miceball_gui/static/session-demo.mjs';
import { experimentView, updateExperiment, prepareExperimentRepeat, experimentDeviceGroups } from '../src/miceball_gui/static/experiment-demo.mjs';

const identity = () => ({ name: 'Frozen Session', date: '2026-10-26', experimenter: 'Demo scientist', owner: 'demo', project: 'Demo project', animal: 'Demo animal' });

test('launched Experiment survives removal of its Setup occurrence and protocol switching (P2)', () => {
  const state = createDemo();
  const active = launchSessionDemo(state, identity());
  const { step, record } = selectedStepContext(state);
  assert.equal(step.operation, 'baseline');
  updateExperiment(state, step, record, { durationSeconds: 456 });
  actOnSessionStep(state, step.id, 'run');
  const snapshot = experimentView(state, step, record).configuration;
  const draft = clone(state.protocols[0]);
  draft.steps = draft.steps.filter(item => item.id !== step.id).reverse();
  draft.name = 'Future procedure';
  saveProtocol(state, draft);
  selectProtocol(state, 'reference');
  state.selectedDevices = [];
  requestExperimentStop(state);
  finishExperimentStop(state);
  assert.equal(record.status, 'completed');
  assert.equal(record.results.at(-1).origin, 'Simulated Normal Stop');
  assert.equal(experimentView(state, step, record).configuration, snapshot);
  assert.equal(snapshot.durationSeconds, 456);
  assert.equal(selectedStepContext(state).step.id, step.id);
  assert.equal(monitoredExperiment(state).record, record);
  assert.equal(active.protocols[0].name, 'CaBMI Closed-Loop Protocol');
  assert.ok(record.history.some(item => item.includes('Normal Stop')));
  prepareExperimentRepeat(state, step, record);
  actOnSessionStep(state, step.id, 'repeat');
  actOnSessionStep(state, step.id, 'complete');
  assert.equal(record.results.length, 2);
  assert.equal(record.experiment.attempts.length, 2);
});

test('launch detaches identity, occurrences, inclusion, capabilities, values and device eligibility without starting an Experiment', () => {
  const state = createDemo();
  const who = identity(), values = { notes: 'Original notes', number: '7' };
  const preview = sessionProgress(state);
  const active = launchSessionDemo(state, who, values);
  const before = clone(active.protocols[0]);
  who.name = 'Future Session'; values.notes = 'Future notes';
  state.protocols[0].steps.reverse();
  state.protocols[0].steps[0].required.push('new-capability');
  state.included = []; state.selectedDevices = ['behavior'];
  assert.deepEqual(active.protocols[0], before);
  assert.equal(active.identity.name, 'Frozen Session');
  assert.equal(active.sessionValues.notes, 'Original notes');
  assert.notEqual(sessionProgress(state), preview);
  assert.equal(monitoredExperiment(state).monitor, undefined);
  assert.ok(Object.values(sessionProgress(state).steps).every(record => record.status !== 'running'));
  const { step, record } = selectedStepContext(state);
  const view = sessionStepView(state, step);
  assert.equal(view.ready, true);
  assert.ok(experimentDeviceGroups(state, step, view.experiment.configuration).some(group => group.options.some(device => device.id === 'orca')));
  const optional = active.protocols[0].steps.find(item => !item.mandatory);
  assert.equal(sessionStepView(state, optional).status, 'skipped');
  assert.ok(sessionStepView(state, step).actions.includes('run'));
  assert.ok(sessionProgress(state).steps['step-0'].results.length);
  assert.throws(() => active.protocols[0].steps.reverse(), TypeError);
  assert.throws(() => launchSessionDemo(state, identity()), /already active/);
  assert.equal(executionContext(active), active);
  assert.equal(experimentView(state, step, record).readOnly, false);
});

test('included optional step remains skippable after Setup excludes it', () => {
  const state = createDemo();
  state.included.push('step-3');
  const step = state.protocols[0].steps.find(item => item.id === 'step-3');
  // A supported available fixture operation permits exercising the skip workflow.
  step.operation = 'roi'; step.required = []; step.optional = [];
  launchSessionDemo(state, identity());
  state.included = [];
  actOnSessionStep(state, step.id, 'skip');
  assert.equal(sessionProgress(state).steps[step.id].status, 'skipped');
});

test('launch preserves detached preview results and immutable attempts but never adopts a running preview', () => {
  const state = createDemo();
  const { step, record } = selectedStepContext(state);
  actOnSessionStep(state, step.id, 'run');
  assert.throws(() => launchSessionDemo(state, identity()), /running preview/);
  actOnSessionStep(state, step.id, 'complete');
  launchSessionDemo(state, identity());
  const captured = selectedStepContext(state).record;
  record.results[0].summary = 'Changed preview';
  record.history.push('Changed preview history');
  assert.notEqual(captured.results[0].summary, 'Changed preview');
  assert.ok(!captured.history.includes('Changed preview history'));
  assert.ok(Object.isFrozen(captured.experiment.attempts[0]));
});
