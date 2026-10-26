import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNavigationMenu } from '../src/miceball_gui/static/navigation-menu.mjs';

class MenuElement {
  constructor(parent = null) {
    this.parent = parent; this.attributes = new Map(); this.listeners = new Map(); this.classes = new Set();
    this.classList = { contains: name => this.classes.has(name), add: name => this.classes.add(name), remove: name => this.classes.delete(name), toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name) };
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  getAttribute(name) { return this.attributes.get(name); }
  addEventListener(type, callback) { this.listeners.set(type, callback); }
  fire(type, values = {}) { this.listeners.get(type)?.({ target: this, ...values }); }
  contains(target) { return target === this || !!target?.parent && this.contains(target.parent); }
  focus() { this.focused = true; this.fire('focusin'); }
}

function menu() {
  const sidebar = new MenuElement(), toggle = new MenuElement(sidebar), document = new MenuElement();
  let controller;
  controller = createNavigationMenu(sidebar, toggle, document, () => { sidebar.classList.remove('is-pinned'); controller.syncPinned(); });
  return { sidebar, toggle, document, controller };
}

test('all six tab selections stay closed through pointer/focus changes and repeated navigation', () => {
  const { sidebar, toggle, controller } = menu();
  for (let repeat = 0; repeat < 3; repeat++) {
    for (const section of ['Setup', 'Session', 'Parameters', 'Experiment', 'Analysis', 'Services']) {
      toggle.fire('click');
      assert.equal(toggle.getAttribute('aria-expanded'), 'true', section);
      controller.close(); // The existing tab-selection handler invokes this boundary.
      sidebar.fire('pointerleave'); sidebar.fire('pointerenter'); sidebar.fire('focusin');
      assert.equal(toggle.getAttribute('aria-expanded'), 'false', section);
      assert.equal(sidebar.classList.contains('is-temporary-expanded'), false, section);
    }
  }
});

test('toggle open/close, outside dismissal, explicit reopening and Escape remain usable', () => {
  const { sidebar, toggle, document, controller } = menu();
  toggle.fire('click'); toggle.fire('click');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.fire('click'); document.fire('pointerdown', { target: new MenuElement(sidebar) });
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  document.fire('pointerdown', { target: new MenuElement() });
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.fire('click'); controller.close(); toggle.fire('click');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  document.fire('keydown', { key: 'Escape' });
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(toggle.focused, true);
});

test('pinning retains its persistent layout and the navigation toggle can unpin and close', () => {
  const { sidebar, toggle, document, controller } = menu();
  sidebar.classList.add('is-pinned'); controller.syncPinned();
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  document.fire('pointerdown', { target: new MenuElement() });
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  toggle.fire('click');
  assert.equal(sidebar.classList.contains('is-pinned'), false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
});
