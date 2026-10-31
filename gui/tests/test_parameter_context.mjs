import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDemo } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo } from '../src/miceball_gui/static/session-context.mjs';
import { selectedStepContext, actOnSessionStep, sessionProgress } from '../src/miceball_gui/static/session-demo.mjs';
import { experimentView, updateExperiment } from '../src/miceball_gui/static/experiment-demo.mjs';
import { activeParameterSnapshot } from '../src/miceball_gui/static/experiment-parameters.mjs';
import { formatCalendarDate } from '../src/miceball_gui/static/calendar-date.mjs';
import { createAnimalCatalog } from '../src/miceball_gui/static/animal-demo.mjs';

test('drawer reads existing prepared Session values without creating or mutating configuration', () => {
  const state = createDemo();
  assert.equal(activeParameterSnapshot(state), null);
  launchSessionDemo(state, {});
  const { step, record } = selectedStepContext(state);
  const before = JSON.stringify(state);
  assert.equal(activeParameterSnapshot(state), null);
  assert.equal(JSON.stringify(state), before);
  experimentView(state, step, record);
  updateExperiment(state, step, record, { durationSeconds: 321 });
  const prepared = JSON.stringify(state);
  const view = activeParameterSnapshot(state);
  assert.equal(view.configuration.durationSeconds, 321);
  assert.deepEqual(view.configuration.participants, record.experiment.working.participants);
  view.configuration.values['orca.exposure'] = 999;
  assert.equal(JSON.stringify(state), prepared);
});

test('executing configuration wins over mutable working values and other selected steps', () => {
  const state = createDemo();
  launchSessionDemo(state, {});
  const { step, record } = selectedStepContext(state);
  updateExperiment(state, step, record, { durationSeconds: 321 });
  actOnSessionStep(state, step.id, 'run');
  record.experiment.working.durationSeconds = 999;
  state.selectedDevices = [];
  sessionProgress(state).selectedId = state.activeSession.protocols[0].steps[1].id;
  assert.equal(activeParameterSnapshot(state).configuration.durationSeconds, 321);
  assert.throws(() => updateExperiment(state, step, record, { durationSeconds: 50 }), /read-only/);
});

test('mouse and Session calendar dates use YYYYMMDD without rewriting timestamps or ISO storage', () => {
  assert.equal(formatCalendarDate('2026-10-30'), '20261030');
  assert.equal(formatCalendarDate('20261030'), '20261030');
  assert.equal(formatCalendarDate('Aug 24, 2026'), '20260824');
  assert.equal(formatCalendarDate('2026-10-30T12:30:00Z'), '2026-10-30T12:30:00Z');
  assert.equal(formatCalendarDate('Not set'), 'Not set');
  const animal = createAnimalCatalog().get('M1023');
  assert.equal(animal.date_of_birth, 'Sep 16, 2026');
  assert.equal(formatCalendarDate(animal.date_of_birth), '20260916');
});
