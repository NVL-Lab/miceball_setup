import assert from 'node:assert/strict';
import test from 'node:test';
import {activityPresentation} from '../src/miceball_gui/static/activity-presentation.mjs';

const entry = {operation: 'launch_session', observed_at: '2026-11-17T15:42:00Z', source: 'controller'};
test('confirmed routine success is concise and does not expose correlation or raw data', () => {
  const record = {...entry, status: 'succeeded', request_id: 'private-id', result: {status: 'succeeded'}};
  const before = structuredClone(record), view = activityPresentation(record);
  assert.equal(view.message, 'Session launched successfully.');
  assert.equal(view.time, new Date(entry.observed_at).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}));
  assert.deepEqual(record, before);
  const displayFailure = activityPresentation({...record, feedback_error: 'Rendering failed.'});
  assert.equal(displayFailure.status, 'succeeded');
  assert.match(displayFailure.message, /^Session launched successfully\..*display could not be refreshed/);
});
test('preparation, backend rejection and Controller failure remain distinguishable', () => {
  assert.match(activityPresentation({...entry, status: 'failed', source: 'local', error: 'Session number is invalid.'}).message, /locally.*Session number is invalid/);
  assert.match(activityPresentation({...entry, status: 'rejected', source: 'submission', error: 'Invalid configuration.'}).message, /submission.*Invalid configuration/);
  assert.match(activityPresentation({...entry, status: 'rejected', error: 'Reservation denied.'}).message, /rejected by Controller.*Reservation denied/);
});
test('pending, timeout and unknown never imply execution failure, cancellation or replay', () => {
  assert.match(activityPresentation({...entry, status: 'pending'}).message, /pending confirmation/);
  for (const status of ['uncertain', 'unknown']) {
    const message = activityPresentation({...entry, status, error: 'NATS timeout on _INBOX.private'}).message;
    assert.match(message, /could not be confirmed.*Check Session status.*No automatic retry/);
    assert.doesNotMatch(message, /failed|_INBOX|NATS/);
  }
});
test('local preparation is never presented as framework execution', () => {
  assert.equal(activityPresentation({...entry, operation: 'prepare_experiment', source: 'local', status: 'succeeded'}).message, 'Experiment prepared locally.');
});
