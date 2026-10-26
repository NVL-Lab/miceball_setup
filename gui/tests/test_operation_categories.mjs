import { test } from 'node:test';
import assert from 'node:assert/strict';
import { operations, operationCategoryAvailability } from '../src/miceball_gui/static/protocol-demo.mjs';
import { createDemo, selectProtocol } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo } from '../src/miceball_gui/static/session-context.mjs';
import { freeOperationChoices } from '../src/miceball_gui/static/session-demo.mjs';

test('category availability presents real definitions and leaves the two deferred categories unpopulated', () => {
  const categories = operationCategoryAvailability();
  assert.deepEqual(categories, [
    { category: 'Experiment', count: 4 }, { category: 'Analysis', count: 3 },
    { category: 'Scientific Validation', count: 0 }, { category: 'Operator interaction', count: 0 },
  ]);
  const state = createDemo(); selectProtocol(state, null); launchSessionDemo(state, { name: 'Demo' });
  assert.deepEqual(freeOperationChoices(state).map(choice => choice.operation.id), operations.map(operation => operation.id));
});
