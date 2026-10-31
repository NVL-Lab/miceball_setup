import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createExperimentParameterDrawer } from '../src/miceball_gui/static/experiment-parameter-drawer.js';
import { createDemo } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo } from '../src/miceball_gui/static/session-context.mjs';
import { selectedStepContext, actOnSessionStep, requestExperimentStop, finishExperimentStop } from '../src/miceball_gui/static/session-demo.mjs';
import { updateExperiment } from '../src/miceball_gui/static/experiment-demo.mjs';

// Minimal DOM surface used by the presenter; innerHTML is inspected as output.
class Element {
  constructor() { this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.classes = new Set(); this.classList = { toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name) }; }
  append(node) { this.children.push(node); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  click() { this.listeners.click(); }
  querySelector(selector) {
    const matches = node => selector.startsWith('.') ? node.className === selector.slice(1)
      : selector.startsWith('#') ? node.id === selector.slice(1)
      : selector === '[data-show-experiment-parameters]' ? 'showExperimentParameters' in node.dataset
      : selector === '[data-science-session]' && 'scienceSession' in node.dataset;
    for (const child of this.children) { if (matches(child)) return child; const found = child.querySelector(selector); if (found) return found; }
    return null;
  }
}

for (const openDuringStop of [false, true]) test(`drawer stays ${openDuringStop ? 'expanded' : 'collapsed'} through Stop and completion with refreshed read-only context`, () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: () => new Element() };
  try {
    const state = createDemo(); launchSessionDemo(state, {});
    const { step, record } = selectedStepContext(state);
    updateExperiment(state, step, record, { durationSeconds: 321 });
    const panel = new Element(), heading = new Element(); heading.className = 'view-heading'; panel.append(heading);
    const render = createExperimentParameterDrawer(panel, state);
    render();
    const button = panel.querySelector('[data-show-experiment-parameters]');
    const drawer = panel.querySelector('#experiment-parameters-drawer');
    const check = open => {
      assert.equal(drawer.hidden, !open);
      assert.equal(button.attributes['aria-expanded'], String(open));
      assert.equal(button.textContent, open ? 'Hide Parameters' : 'Show Parameters');
      assert.equal(panel.classes.has('has-parameters-drawer'), open);
      assert.doesNotMatch(drawer.innerHTML, /<(input|select|textarea|button)\b/);
    };
    assert.match(drawer.innerHTML, /Prepared configuration in the active Session/);
    actOnSessionStep(state, step.id, 'run'); render();
    assert.match(drawer.innerHTML, /Fixed executing-attempt configuration/);
    button.click(); check(true); button.click(); check(false);
    if (openDuringStop) button.click();
    requestExperimentStop(state);
    drawer.hidden = false; // Existing Device Validation visibility sweep during render.
    render(); check(openDuringStop);
    assert.match(drawer.innerHTML, /Fixed executing-attempt configuration/);
    finishExperimentStop(state); drawer.hidden = false; render(); check(openDuringStop);
    assert.match(drawer.innerHTML, /Fixed executed-attempt configuration/);
    assert.match(drawer.innerHTML, /321/);
    assert.match(drawer.innerHTML, /Camera \(ORCA-Fusion\)/);
    assert.doesNotMatch(drawer.innerHTML, /Stage \(ASI Tiger\)|Reward solenoid/);
    const completed = JSON.stringify(state);
    if (openDuringStop) button.click();
    button.click(); check(true); render(); check(true); button.click(); check(false);
    assert.equal(JSON.stringify(state), completed);
    assert.equal(record.status, 'completed');
  } finally { globalThis.document = previousDocument; }
});
