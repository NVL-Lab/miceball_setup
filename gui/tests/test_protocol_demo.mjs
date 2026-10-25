import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sessionProgress, sessionStepView, actOnSessionStep } from '../src/miceball_gui/static/session-demo.mjs';
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
