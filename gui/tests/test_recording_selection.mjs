import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDemo, selectProtocol, clone } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo, executionSteps } from '../src/miceball_gui/static/session-context.mjs';
import { prepareFreeOperation, selectedStepContext, sessionProgress, sessionStepView, selectRecording, clearRecordingSelection, actOnSessionStep } from '../src/miceball_gui/static/session-demo.mjs';
import { describeRecordingSelection } from '../src/miceball_gui/static/recording-identity.mjs';
import { updateExperiment, experimentView } from '../src/miceball_gui/static/experiment-demo.mjs';

const recording = (name = 'other-project/previous-session/recording') => ({ kind: 'folder', name, entries: [{ name: 'frames.example', relativePath: `${name}/frames.example`, size: 12, lastModified: 10 }] });
function free() {
  const state = createDemo(); selectProtocol(state, null); launchSessionDemo(state, { animal: 'Demo animal' }); return state;
}

test('native metadata preserves file and folder identity without reading contents or making up absolute paths', () => {
  const file = { name: 'frames.example', webkitRelativePath: 'recording/frames.example', size: 12, lastModified: 10, text() { throw new Error('Must not read contents'); }, arrayBuffer() { throw new Error('Must not read contents'); } };
  const folder = describeRecordingSelection([file], 'folder');
  assert.equal(folder.name, 'recording');
  assert.equal(folder.entries[0].relativePath, 'recording/frames.example');
  const single = describeRecordingSelection([{ ...file, webkitRelativePath: '' }], 'file');
  assert.equal(single.name, 'frames.example');
  assert.equal(single.entries[0].relativePath, null);
  assert.equal(describeRecordingSelection([], 'folder'), null);
});

test('selection and clearing do not execute, satisfy or add history; unsupported operations retain normal execution', () => {
  const state = free();
  const step = prepareFreeOperation(state, 'roi');
  const { record } = selectedStepContext(state);
  const before = clone(record);
  selectRecording(state, step.id, recording());
  assert.equal(record.status, before.status);
  assert.deepEqual(record.results, before.results);
  assert.deepEqual(record.attempts, before.attempts);
  assert.deepEqual(record.history, before.history);
  assert.ok(sessionStepView(state, step).actions.includes('run'));
  assert.throws(() => actOnSessionStep(state, step.id, 'load'), /explicit simulated/);
  clearRecordingSelection(state, step.id);
  assert.equal(record.recordingSelection, undefined);
  assert.deepEqual(record.history, before.history);
  assert.throws(() => actOnSessionStep(state, step.id, 'accept-recording'), /not available/);
  const baseline = prepareFreeOperation(state, 'baseline');
  assert.equal(sessionStepView(state, baseline).supports.load, false);
  assert.throws(() => selectRecording(state, baseline.id, recording()), /does not currently support/);
  actOnSessionStep(state, baseline.id, 'run'); actOnSessionStep(state, baseline.id, 'complete');
  assert.equal(sessionProgress(state).steps[baseline.id].status, 'completed');
});

test('Protocol Mode satisfaction is explicit, separate from execution/skipping, and retains fixed steps/results', () => {
  const state = createDemo(); launchSessionDemo(state, { name: 'Protocol demo' });
  const fixed = clone(executionSteps(state));
  const progress = sessionProgress(state), original = clone(progress.steps['step-1']);
  selectRecording(state, 'step-1', recording());
  assert.equal(progress.steps['step-1'].status, 'completed');
  actOnSessionStep(state, 'step-1', 'accept-recording');
  assert.equal(progress.steps['step-1'].status, 'satisfied');
  assert.deepEqual(progress.steps['step-1'].results, original.results);
  assert.deepEqual(progress.steps['step-1'].attempts, original.attempts);
  assert.match(progress.steps['step-1'].history.at(-1), /no new execution, acquisition or scientific output/);
  assert.equal(progress.steps['step-1'].recordedInputs[0].outcome, 'accepted');
  assert.equal(sessionStepView(state, executionSteps(state)[3]).status, 'skipped');
  selectProtocol(state, 'reference'); state.selectedDevices = [];
  assert.deepEqual(executionSteps(state), fixed);
  assert.equal(progress.steps['step-1'].status, 'satisfied');
});

test('rejection preserves status and results, changing selection retains older decisions, and Free Mode inputs are occurrence-local', () => {
  const state = free();
  const first = prepareFreeOperation(state, 'roi');
  const firstRecord = selectedStepContext(state).record;
  selectRecording(state, first.id, recording('current-session'));
  actOnSessionStep(state, first.id, 'reject-recording');
  assert.equal(firstRecord.status, 'not-started');
  assert.deepEqual(firstRecord.results, []);
  assert.deepEqual(firstRecord.attempts, []);
  selectRecording(state, first.id, recording('another-project'));
  actOnSessionStep(state, first.id, 'accept-recording');
  const accepted = clone(firstRecord.recordedInputs);
  const second = prepareFreeOperation(state, 'roi');
  assert.notEqual(first.id, second.id);
  assert.equal(selectedStepContext(state).record.recordingSelection, undefined);
  selectRecording(state, second.id, recording('third-project'));
  assert.deepEqual(firstRecord.recordedInputs, accepted);
  assert.equal(firstRecord.status, 'satisfied');
  actOnSessionStep(state, second.id, 'run'); actOnSessionStep(state, second.id, 'complete');
  assert.equal(selectedStepContext(state).record.status, 'completed');
  assert.equal(firstRecord.status, 'satisfied');
  assert.equal(state.activeSession.protocolId, null);
});

test('recorded-input selection never changes unrelated Experiment working values or executed snapshots', () => {
  const state = free();
  const baseline = prepareFreeOperation(state, 'baseline');
  const baselineRecord = selectedStepContext(state).record;
  updateExperiment(state, baseline, baselineRecord, { durationSeconds: 77 });
  const analysis = prepareFreeOperation(state, 'calibrate');
  selectRecording(state, analysis.id, recording());
  actOnSessionStep(state, analysis.id, 'accept-recording');
  assert.equal(experimentView(state, baseline, baselineRecord).configuration.durationSeconds, 77);
  actOnSessionStep(state, baseline.id, 'run'); actOnSessionStep(state, baseline.id, 'complete');
  assert.equal(baselineRecord.experiment.attempts[0].durationSeconds, 77);
  assert.equal(sessionProgress(state).steps[analysis.id].status, 'satisfied');
});

test('the existing downstream-review mechanism preserves and restores recorded-input satisfaction', () => {
  const state = createDemo(); launchSessionDemo(state, { name: 'Protocol demo' });
  selectRecording(state, 'step-5', recording()); actOnSessionStep(state, 'step-5', 'accept-recording');
  const saved = clone(sessionProgress(state).steps['step-5'].recordedInputs);
  actOnSessionStep(state, 'step-2', 'run'); actOnSessionStep(state, 'step-2', 'complete');
  assert.equal(sessionProgress(state).steps['step-5'].status, 'needs-review');
  actOnSessionStep(state, 'step-5', 'validate');
  assert.equal(sessionProgress(state).steps['step-5'].status, 'satisfied');
  assert.deepEqual(sessionProgress(state).steps['step-5'].recordedInputs, saved);
});
