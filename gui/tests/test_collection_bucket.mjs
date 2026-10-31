import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import * as storage from '../src/miceball_gui/static/storage-demo.mjs';
import { escapeText } from '../src/miceball_gui/static/gui-presentation.js';
import { formatCalendarDate } from '../src/miceball_gui/static/calendar-date.mjs';

// Exercise the actual view's DOM event boundary without a browser dependency.
const source = readFileSync(new URL('../src/miceball_gui/static/storage-view.js', import.meta.url), 'utf8').replace(/^import .*;\r?$/gm, '');
function bucketView() {
  const classes = new Set();
  const zone = { classList: { add: value => classes.add(value), remove: value => classes.delete(value) }, contains: target => target === zone || target?.parent === zone };
  const listeners = new Map();
  const panel = { innerHTML: '', addEventListener: (name, callback) => listeners.set(name, callback), querySelectorAll: () => [], querySelector: () => zone };
  const experimenter = { selectedOptions: [{textContent:'Taylor Kim'}], addEventListener() {} };
  const document = {
    querySelector: selector => selector === '#panel-storage' ? panel : experimenter,
    createElement: () => ({setAttribute() {}, addEventListener() {}}),
    body: {append() {}}, addEventListener() {},
  };
  runInNewContext(source, {...storage, document, formatCalendarDate, esc:escapeText, servicesAdministrator:() => false});
  const click = (dataset = {}, attribute = '') => {
    const button = {dataset, hasAttribute: name => name === attribute};
    listeners.get('click')({target:{closest:() => button}});
  };
  const drag = (name, values = {}) => listeners.get(name)({target:{closest:() => zone}, ...values});
  return {panel, click, drag, classes, zone};
}

test('bucket displays distinct empty/populated items, Add/Remove and a separate review summary', () => {
  const {panel, click} = bucketView();
  assert.match(panel.innerHTML, /Drag Sessions here, or click Add\./);
  assert.match(panel.innerHTML, /0 Sessions selected · Estimated total size: unavailable/);
  assert.match(panel.innerHTML, /<\/div><p class="storage-bucket-summary">/);
  click({addSession:'demo-pending'});
  assert.match(panel.innerHTML, /storage-row storage-bucket-item/);
  assert.match(panel.innerHTML, /data-remove-session="demo-pending"/);
  assert.match(panel.innerHTML, /1 Sessions selected · Estimated total size: unavailable/);
  click({storageWorkspace:'deletion'});
  assert.match(panel.innerHTML, /0 Experiments selected:/);
  click({storageWorkspace:'collection'});
  click({removeSession:'demo-pending'});
  assert.match(panel.innerHTML, /Drag Sessions here, or click Add\./);
});

test('drop accepts visible whole Sessions only and uses the same selection as Add', () => {
  const {panel, drag} = bucketView();
  let prevented = false;
  drag('drop', {preventDefault:() => prevented = true, dataTransfer:{getData:() => 'demo-pending'}});
  assert.equal(prevented, true);
  assert.match(panel.innerHTML, /1 Sessions selected/);
  drag('drop', {preventDefault() {}, dataTransfer:{getData:() => 'demo-pending-e1'}});
  assert.match(panel.innerHTML, /1 Sessions selected/);
  drag('drop', {preventDefault() {}, dataTransfer:{getData:() => 'demo-other'}});
  assert.match(panel.innerHTML, /1 Sessions selected/);
});

test('drag-over feedback stays across descendants and clears on leave or cancelled drag', () => {
  const {drag, classes, zone} = bucketView();
  const transfer = {};
  drag('dragover', {preventDefault() {}, dataTransfer:transfer});
  assert.equal(transfer.dropEffect, 'copy');
  assert.equal(classes.has('is-drag-over'), true);
  drag('dragleave', {relatedTarget:{parent:zone}});
  assert.equal(classes.has('is-drag-over'), true);
  drag('dragleave', {relatedTarget:null});
  assert.equal(classes.has('is-drag-over'), false);
  drag('dragover', {preventDefault() {}, dataTransfer:transfer});
  drag('dragend');
  assert.equal(classes.has('is-drag-over'), false);
});
