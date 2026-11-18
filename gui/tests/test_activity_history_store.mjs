import test from 'node:test';
import assert from 'node:assert/strict';
import {activities, recordActivity, updateActivity, recordLocalActivity, recordActivityTransition, recordInvalidControl} from '../src/miceball_gui/static/activity-history.mjs';

globalThis.document = new EventTarget();
test.beforeEach(() => { activities.length = 0; });
test('initial loss, recovery and subsequent loss retain transitions without polling noise', () => {
  recordActivityTransition('connection_status', 'unknown', 'Controller unavailable');
  for (let i = 0; i < 10; i++) recordActivityTransition('connection_status', 'unknown', 'Still unavailable');
  recordActivityTransition('connection_status', 'succeeded');
  recordActivityTransition('connection_status', 'succeeded');
  recordActivityTransition('connection_status', 'unknown', 'Disconnected');
  assert.deepEqual(activities.map(entry => entry.status), ['unknown', 'succeeded', 'unknown']);
});
test('successful automatic reads stay quiet; failed refresh and recovery remain informative', () => {
  recordActivityTransition('load_catalog', 'succeeded');
  assert.equal(activities.length, 0);
  recordActivityTransition('load_catalog', 'failed', 'Catalog cannot be read; retained data unchanged');
  recordActivityTransition('load_catalog', 'failed', 'Catalog unavailable');
  recordActivityTransition('load_catalog', 'succeeded');
  assert.equal(activities.length, 2);
  assert.match(activities[0].error, /retained data unchanged/);
});
test('one retained outcome supports pending, uncertainty and confirmed reconciliation', () => {
  const entry = recordActivity('launch_session', 'controller');
  updateActivity(entry, {status: 'uncertain', error: 'Confirmation unavailable'});
  recordLocalActivity('save_catalog', 'Name required');
  updateActivity(entry, {status: 'succeeded', error: ''});
  assert.equal(activities.length, 2);
  assert.equal(activities[0], entry);
  assert.equal(activities[0].status, 'succeeded');
});
test('repeated reporting of one invalid field does not produce keystroke history', () => {
  const control = {value: '', validationMessage: 'Please fill out this field.', getAttribute: () => 'Template name'};
  recordInvalidControl('save_catalog', control);
  recordInvalidControl('save_catalog', control);
  assert.equal(activities.length, 1);
  assert.match(activities[0].error, /Template name.*fill out/);
});
