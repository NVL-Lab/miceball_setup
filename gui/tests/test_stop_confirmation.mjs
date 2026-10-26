import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confirmStop } from '../src/miceball_gui/static/stop-confirmation.mjs';
import { createDemo } from '../src/miceball_gui/static/protocol-demo.mjs';
import { selectedStepContext, actOnSessionStep, monitoredExperiment, requestExperimentStop } from '../src/miceball_gui/static/session-demo.mjs';
import { sessionStopPreview } from '../src/miceball_gui/static/services-demo.mjs';

// Minimal native-dialog test double; real dismissal/focus is checked in the browser.
class DialogElement extends EventTarget {
  constructor() { super(); this.open = false; this.controls = new Map(); }
  setAttribute() {}
  focus() {}
  querySelector(selector) {
    if (!this.controls.has(selector)) this.controls.set(selector, new DialogElement());
    return this.controls.get(selector);
  }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new Event('close')); }
  click() { this.dispatchEvent(new Event('click')); }
  escape() { this.dispatchEvent(new Event('cancel')); this.close(); }
}
let dialog;
globalThis.document = { createElement: () => new DialogElement(), body: { append: element => { dialog = element; } } };

test('Experiment Stop dismissal changes neither running execution nor history; confirm initiates once', () => {
  const state = createDemo();
  const { step, record } = selectedStepContext(state);
  actOnSessionStep(state, step.id, 'run');
  const before = JSON.stringify(record);
  let attempts = 0;
  const initiate = () => { attempts++; requestExperimentStop(state); };
  for (const dismiss of ['keep', 'escape', 'close']) {
    confirmStop('Experiment', initiate);
    assert.equal(dialog.querySelector('#stop-confirmation-title').textContent, 'Stop Experiment?');
    assert.equal(JSON.stringify(record), before);
    if (dismiss === 'keep') dialog.querySelector('[data-keep-running]').click();
    else if (dismiss === 'escape') dialog.escape();
    else dialog.close();
    assert.equal(attempts, 0);
    assert.equal(JSON.stringify(record), before);
  }
  confirmStop('Experiment', initiate);
  dialog.querySelector('[data-confirm-stop]').click();
  dialog.querySelector('[data-confirm-stop]').click();
  assert.equal(attempts, 1);
  assert.equal(monitoredExperiment(state).record.stopRequested, true);
  assert.equal(record.history.length, JSON.parse(before).history.length + 1);
});

test('Session confirmation precedes and does not alter the blocked Stop/Kill preview', () => {
  let attempts = 0, preview;
  const initiate = () => { attempts++; preview = sessionStopPreview('blocked'); };
  for (const dismiss of ['keep', 'escape', 'close']) {
    confirmStop('Session', initiate);
    assert.equal(dialog.querySelector('#stop-confirmation-title').textContent, 'Stop Session?');
    if (dismiss === 'keep') dialog.querySelector('[data-keep-running]').click();
    else if (dismiss === 'escape') dialog.escape();
    else dialog.close();
    assert.equal(attempts, 0);
    assert.equal(preview, undefined);
  }
  confirmStop('Session', initiate);
  dialog.querySelector('[data-confirm-stop]').click();
  dialog.querySelector('[data-confirm-stop]').click();
  assert.equal(attempts, 1);
  assert.deepEqual(preview, sessionStopPreview('blocked'));
  assert.equal(preview.canKill, true);
});
