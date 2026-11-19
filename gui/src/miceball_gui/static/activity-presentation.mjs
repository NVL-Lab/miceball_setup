// Informative presentation only; the existing connected outcome collection owns data.
const operations = {
  load_catalog: ['Catalog refresh', 'Catalog available.'],
  destination_discovery: ['Destination discovery', 'Destination information received.'],
  validate_parameters: ['Parameter validation', 'Parameters validated locally.'],
  prepare_session: ['Session preparation', 'Session prepared locally.'],
  unavailable_operation: ['Operation request', 'Operation available.'],
  register_artifact_destination: ['Destination registration', 'Scientific destination registered.'],
  update_artifact_destination: ['Destination update', 'Scientific destination updated.'],
  save_catalog: ['Catalog save', 'Catalog saved.'],
  save_synchronization: ['Synchronization defaults', 'Synchronization defaults saved.'],
  remove_catalog: ['Catalog removal', 'Catalog entry removed.'],
  take_browser_control: ['Control request', 'Control acquired.'],
  view_only: ['View Only request', 'View Only selected.'],
  launch_session: ['Session launch', 'Session launched successfully.'],
  start_launched_session: ['Session start', 'Session started.'],
  start_launched_experiment: ['Experiment start', 'Experiment started.'],
  stop_launched_experiment: ['Experiment stop', 'Experiment stopped.'],
  prepare_experiment: ['Experiment preparation', 'Experiment prepared locally.'],
  normal_stop_session: ['Session Stop', 'Session stopped.'],
  kill_session: ['Session Kill', 'Session Kill completed.'],
  release_session: ['Session release', 'Session released.'],
  reconcile_launched_experiment_expiry: ['Experiment completion check', 'Experiment completion checked.'],
  get_node_inventory: ['Inventory refresh', 'Inventory refreshed.'],
  check_readiness: ['Readiness check', 'Readiness check completed.'],
  connection_status: ['Controller connection', 'Controller connection confirmed.'],
  stop_service: ['Service Stop', 'Service stopped.'],
  kill_service: ['Service Kill', 'Service Kill completed.'],
  cancel_service: ['Stop cancellation', 'Stop cancellation confirmed.'],
  shutdown_framework: ['Framework shutdown', 'Framework shutdown completed.'],
  recover_archive_write: ['Archive write recovery', 'Archive write recovery completed.'],
  recover_session_record_write: ['Session Record recovery', 'Session Record recovery completed.'],
  recover_artifact_transfer: ['Artifact transfer recovery', 'Artifact transfer recovery completed.'],
  preserve_scientific_artifact: ['Artifact preservation', 'Artifact preservation confirmed.'],
  cleanup_device_resources: ['Device resource cleanup', 'Device resource cleanup completed.'],
  dispose_temporary_evidence: ['Temporary evidence disposal', 'Temporary evidence disposal completed.'],
};

export function activityPresentation(entry) {
  const [label, success] = operations[entry.operation] || ['Operation', 'Operation completed.'];
  let reason = entry.error || entry.result?.error || '';
  // Keep original diagnostics in the existing result; ordinary feedback uses readable terms.
  for (const [name, [readable]] of Object.entries(operations)) reason = reason.replaceAll(name, readable);
  if (/timeout|timed out/i.test(reason)) reason = 'The response timed out; execution may still be in progress.';
  else if (/NATS|WebSocket|_INBOX|ECONN|Transport/i.test(reason)) reason = 'Communication is unavailable or could not be verified.';
  let message;
  if (entry.operation === 'connection_status') message = entry.status === 'succeeded' ? success : `Controller connection is unconfirmed. Current state may be last known. ${reason}`;
  else if (entry.status === 'succeeded') message = success;
  else if (entry.status === 'pending') message = entry.source === 'local'
    ? `${label} is being prepared locally.` : `${label} requested; pending confirmation.`;
  else if (['uncertain', 'unknown'].includes(entry.status)) {
    message = `${label} could not be confirmed.${entry.operation === 'launch_session' ? ' Check Session status.' : ''} ${reason || 'The outcome is unavailable.'} No automatic retry.`;
  } else message = `${label} ${entry.source === 'local' ? 'could not proceed locally' : entry.source === 'submission' ? 'was not accepted for submission' : entry.status === 'rejected' ? 'was rejected by Controller' : 'failed'}: ${reason || 'No further reason was provided.'}`;
  if (entry.feedback_error) message += ' The display could not be refreshed; check current Session status.';
  return {message, time: new Date(entry.observed_at).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}), status: entry.status};
}
