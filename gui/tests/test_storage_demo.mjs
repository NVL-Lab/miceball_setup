import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createStorageDemo, visibleStorageSessions, selectCollection, selectDeletion, storageSelection, storageHistory, deletionReview } from '../src/miceball_gui/static/storage-demo.mjs';

test('history searches displayed calendar dates, ISO dates and ordinary terms without changing records', () => {
  const sessions = visibleStorageSessions(createStorageDemo(), 'Taylor Kim', false);
  const before = JSON.stringify(sessions);
  const ids = filters => storageHistory(sessions, filters).map(item => item.id);
  assert.deepEqual(ids({query: '20261024'}), ['demo-pending', 'demo-incomplete']);
  assert.deepEqual(ids({query: '2026-10-24'}), ids({query: '20261024'}));
  assert.deepEqual(ids({query: '20261024', status: 'incomplete'}), ['demo-incomplete']);
  assert.equal(ids({query: 'visual learning'}).length, 4);
  assert.deepEqual(ids({query: 'demo-older'}), ['demo-older']);
  assert.deepEqual(ids({query: 'no match'}), []);
  assert.equal(JSON.stringify(sessions), before);
});

test('collection Add, Remove and pending selection are whole-Session and independent of deletion', () => {
  const model = createStorageDemo(), visible = visibleStorageSessions(model, 'Taylor Kim', false);
  const session = visible[0];
  assert.equal(selectCollection(model, visible, session.experiments[0].id), false);
  assert.equal(selectCollection(model, visible, session.id), true);
  assert.equal(storageSelection(model, visible, 'collection').length, 1);
  assert.equal(model.deletion.size, 0);
  selectCollection(model, visible, session.id, false);
  assert.equal(model.collection.size, 0);
  visible.filter(item => item.status === 'pending').forEach(item => selectCollection(model, visible, item.id));
  assert.deepEqual([...model.collection], [session.id]);
});

test('Experiment and whole-Session deletion retain exact scope and never select collection', () => {
  const model = createStorageDemo(), session = model.sessions[0];
  selectDeletion(model, session, session.experiments[0].id, true);
  assert.equal(storageSelection(model, [session], 'deletion').length, 1);
  selectDeletion(model, session, null, true);
  assert.equal(storageSelection(model, [session], 'deletion').length, 2);
  selectDeletion(model, session, null, false);
  assert.equal(model.deletion.size, 0);
  assert.equal(model.collection.size, 0);
});

test('risky deletion requires acknowledgment, verified copies still require a review selection', () => {
  const model = createStorageDemo();
  const choose = session => session.experiments.map(experiment => ({session, experiment}));
  assert.deepEqual(deletionReview(choose(model.sessions[0])), {risky:true, canProceed:false});
  assert.equal(deletionReview(choose(model.sessions[0]), true).canProceed, true);
  assert.deepEqual(deletionReview(choose(model.sessions[2])), {risky:false, canProceed:true});
  assert.equal(deletionReview([]).canProceed, false);
  const uncertain = {...model.sessions[2], status:'uncertain'};
  assert.equal(deletionReview(choose(uncertain)).risky, true);
});

test('cooperative visibility matches owner exactly; admin sees all; hidden selections are excluded', () => {
  const model = createStorageDemo();
  assert.equal(visibleStorageSessions(model, '', false).length, 0);
  assert.equal(visibleStorageSessions(model, 'Taylor Kim', false).length, 4);
  assert.equal(visibleStorageSessions(model, '', true).length, 5);
  model.collection.add('demo-other'); model.deletion.add('demo-other-e1');
  const visible = visibleStorageSessions(model, 'Taylor Kim', false);
  assert.equal(storageSelection(model, visible, 'collection').length, 0);
  assert.equal(storageSelection(model, visible, 'deletion').length, 0);
});

test('history uses collection completion, retains old unresolved entries and searches older successes', () => {
  const model = createStorageDemo(), now = new Date('2026-10-27T12:00:00Z');
  const defaults = storageHistory(model.sessions, {}, now);
  assert.equal(defaults.some(item=>item.id==='demo-older'), false);
  assert.equal(defaults.some(item=>item.id==='demo-collected'), true);
  assert.equal(defaults.some(item=>item.id==='demo-incomplete'), true);
  assert.equal(storageHistory(model.sessions, {query:'demo-older'}, now).length, 1);
  assert.equal(storageHistory(model.sessions, {older:true}, now).length, 5);
  assert.equal(storageHistory(model.sessions, {status:'active'}, now)[0].owner, 'Morgan Lee');
  assert.equal(storageHistory(model.sessions, {query:'no match'}, now).length, 0);
  for (const status of ['pending','active','failed','incomplete','uncertain']) {
    assert.equal(storageHistory([{...model.sessions[3], status}], {}, now).length, 1);
  }
  assert.equal(storageHistory([{...model.sessions[3], unresolved:true}], {}, now).length, 1);
  assert.equal(model.sessions.length, 5);
});
