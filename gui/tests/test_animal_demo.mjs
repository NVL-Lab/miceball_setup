import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAnimalCatalog, saveAnimalDemo } from '../src/miceball_gui/static/animal-demo.mjs';
import { createDemo } from '../src/miceball_gui/static/protocol-demo.mjs';
import { launchSessionDemo } from '../src/miceball_gui/static/session-context.mjs';

test('existing animal selections resolve complete independent metadata repeatedly', () => {
  const catalog = createAnimalCatalog();
  for (const id of ['M1023', 'M1041', 'M1023', 'M1041']) {
    const animal = catalog.get(id);
    assert.equal(animal.animal_id, id);
    for (const field of ['animal_name', 'species', 'strain', 'sex', 'date_of_birth']) assert.ok(animal[field]);
  }
  assert.notEqual(catalog.get('M1023').strain, catalog.get('M1041').strain);
  assert.notEqual(catalog.get('M1023').sex, catalog.get('M1041').sex);
});

test('new animal metadata survives reselection and same-label entries do not overwrite examples', () => {
  const catalog = createAnimalCatalog();
  const values = { animal_id: 'M1023', animal_name: 'New demo', species: 'Example species', strain: 'Example strain', sex: 'Female', date_of_birth: '2026-09-01', notes: 'Retain these notes' };
  const saved = { ...values };
  const key = saveAnimalDemo(catalog, values);
  values.animal_name = 'Unsaved edit';
  for (const id of ['M1041', key, 'M1023', key]) assert.ok(catalog.get(id));
  assert.deepEqual(catalog.get(key), saved);
  assert.equal(catalog.get('M1023').animal_name, 'Pip');
  const other = createAnimalCatalog();
  assert.equal(other.has(key), false); // No durable or shared catalog.
});

test('future Setup animal edits cannot change the captured active identity', () => {
  const state = createDemo(), catalog = createAnimalCatalog();
  const identity = { name: 'Demo Session', animal: catalog.get('M1023').animal_id };
  launchSessionDemo(state, identity);
  identity.animal = catalog.get('M1041').animal_id;
  saveAnimalDemo(catalog, { animal_id: 'New demo animal', animal_name: 'New' });
  assert.equal(state.activeSession.identity.animal, 'M1023');
});
