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

test('collection success does not imply deletion success', () => {
  const collection = {...entry, operation: 'collect_saved_session_artifacts_remote', session_id: 'saved', status: 'succeeded'};
  assert.match(activityPresentation(collection).message, /collection succeeded.*Originals were preserved/i);
  const result = {outcome: {details: {session_id: 'saved', collection_outcome: {
    session_id: 'saved', archival_confirmed: true, artifact_collection_result: {succeeded: true}},
    deletion: {command: 'delete_original_artifacts', succeeded: false, details: {session_id: 'saved', operation_id: 'delete-original'}, error: 'Deletion outcome is unconfirmed'}}}};
  const requested = {...collection, deletion_requested: true, deletion_operation_id: 'delete-original', status: 'failed', result};
  assert.match(activityPresentation(requested).message, /Collection succeeded.*deletion.*not.*confirmed/);
  result.outcome.details.deletion.succeeded = true;
  assert.match(activityPresentation({...requested, status: 'succeeded'}).message, /Collection succeeded.*original deletion succeeded/);
  result.outcome.details.deletion.details.operation_id = 'another-operation';
  assert.doesNotMatch(activityPresentation({...requested, status: 'succeeded'}).message, /deletion succeeded/);
});

test('uncertain collection with requested deletion never certifies either operation', () => {
  for (const status of ['pending', 'uncertain', 'failed']) {
    const view = activityPresentation({...entry, operation: 'collect_saved_session_artifacts_remote', deletion_requested: true, status});
    assert.doesNotMatch(view.message, /collection succeeded|deletion succeeded/i);
  }
});
