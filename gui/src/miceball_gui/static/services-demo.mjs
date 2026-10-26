// Fictional, page-memory presentation fixtures. No discovery, polling or commands.
export function createServicesDemo() {
  return {
    administrator: false, selectedId: 'controller', detail: 'Status', refreshSeconds: 10,
    lastPreviewRefresh: null,
    services: [
      { id: 'controller', name: 'Controller', computer: 'Controller computer · 192.0.2.10', readiness: 'Ready', connectivity: 'Connected', confirmed: '10:24:15', current: true, dependencies: 'Configured participant reports are needed for coordinated operations. Unknown reports do not establish readiness.', information: 'Coordination example only; no live configuration readback.' },
      { id: 'node-microscope', name: 'AcquisitionNode', computer: 'Microscope computer · 192.0.2.20', readiness: 'Ready', connectivity: 'Connected', confirmed: '10:24:12', current: true, dependencies: 'Device availability and accepted configuration are checked by the owning service, not this view.', information: 'Microscope acquisition example. No device settings are exposed here.' },
      { id: 'node-imaging', name: 'AcquisitionNode', computer: 'Imaging computer · 192.0.2.30', readiness: 'Ready', connectivity: 'Reconnecting', confirmed: '10:21:03', current: false, dependencies: 'Connectivity is unconfirmed. Operations requiring this participant cannot be confirmed available; other confirmed participants remain inspectable.', information: 'Last-known report only. Transport reconnection does not replay lifecycle commands.' },
      { id: 'ingestor', name: 'Ingestor', computer: 'Storage computer · 192.0.2.40', readiness: 'Ready', connectivity: 'Restored', confirmed: '10:24:10', current: true, dependencies: 'Evidence intake and archival confirmations are distinct. Restored transport alone proves neither preservation nor prior publication.', information: 'Fictional intake status; no evidence query or collection operation is implemented.' },
      { id: 'storage', name: 'StorageManager', computer: 'Storage computer · 192.0.2.40', readiness: 'Unhealthy', connectivity: 'Connected', confirmed: '10:18:55', current: true, dependencies: 'The reported write problem affects preservation confirmation. Inspection remains available; readiness checks do not repair storage.', information: 'Reported write problem (fictional). No storage paths or credentials are loaded.' },
      { id: 'sync', name: 'Synchronization Manager', computer: 'Controller computer · 192.0.2.10', readiness: 'Unknown', connectivity: 'Unknown', confirmed: null, current: false, dependencies: 'Availability is unknown. Time-dependent operations cannot be declared ready by this GUI.', information: 'No confirmed status is supplied in this scenario.' },
    ],
    obligations: [
      { service: 'StorageManager', type: 'Preservation', description: 'Final evidence preservation not confirmed', outcome: 'Unresolved' },
      { service: 'StorageManager', type: 'Recovery', description: 'Supported procedure / current prerequisites not established', outcome: 'Unknown / unconfirmed' },
      { service: 'Ingestor', type: 'Preservation', description: 'Illustrative evidence handoff attempt; no archival confirmation', outcome: 'Attempt in progress' },
      { service: 'AcquisitionNode', type: 'Cleanup', description: 'Illustrative device release confirmation', outcome: 'Confirmed completed (fixture)' },
    ],
  };
}

export function setServicesAdministrator(model, enabled, confirmed = false) {
  if (enabled && !confirmed) throw new Error('Confirm the Danger Zone before entering Administrator mode.');
  model.administrator = !!enabled;
}

export function refreshServicesPreview(model, at) {
  // A local repaint must never promote a stale/unreachable report to confirmation.
  model.lastPreviewRefresh = at;
}

export function serviceReadinessLabel(service) {
  if (!service.confirmed) return 'Unknown availability';
  return service.current ? `${service.readiness} · fixture confirmation` : `Last known: ${service.readiness} · availability unknown`;
}

export function sessionStopPreview(outcome) {
  const scenarios = {
    completed: { message: 'Orderly Stop confirmed in the fictional scenario only. No real Session was stopped or preservation checked.', canKill: false },
    blocked: { message: 'Reported blocker (fixture): a participant has not confirmed acquisition closeout. The Session is not shown as stopped. A separately authorized Kill may leave partial preservation and unresolved cleanup.', canKill: true },
    unknown: { message: 'No confirmed result (communication timeout example). This is not proof of failure, completion, or safety to Kill. Reconciliation is not implemented in this demo.', canKill: false },
  };
  if (!scenarios[outcome]) throw new Error('Choose an explicit demonstration outcome.');
  return scenarios[outcome];
}

// Local presentation attempt only; never changes a configured service report.
export function beginShutdownPreview(model, serviceId = null) {
  if (!model.administrator) throw new Error('Administrator mode required.');
  const participants = serviceId ? model.services.filter(s => s.id === serviceId) : model.services;
  if (!participants.length) throw new Error('Select a configured service.');
  return { scope: serviceId ? 'service' : 'framework', phase: 'pending',
    participants: participants.map(s => ({ id: s.id, name: s.name, computer: s.computer, outcome: 'pending', note: 'No simulated confirmation yet.' })) };
}

export function finishShutdownPreview(attempt, outcome = 'blocked') {
  if (!['blocked', 'completed', 'failed', 'unknown'].includes(outcome)) throw new Error('Supply an explicit presentation outcome.');
  if (attempt.phase !== 'pending') return attempt;
  attempt.participants.forEach(row => {
    row.outcome = outcome;
    row.note = { blocked: 'Explicit blocked-stop fixture: a service-owned cleanup or preservation prerequisite is unresolved. This report is not inferred from the service list or connectivity.', unknown: 'No confirmation in this fixture. Connectivity loss is not death or failure.', failed: 'Fixture: orderly closeout began but did not complete. Decision 315 does not authorize Kill continuation of this terminal failed attempt; service-owned assessment/manual intervention is required.', completed: 'Orderly closeout confirmed only within this fictional scenario.' }[outcome];
  });
  attempt.phase = 'reported';
  return attempt;
}

export function notificationHistoryView(history, expanded = false) {
  const sorted = [...history].sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt));
  return expanded ? sorted : sorted.slice(0, 3);
}

export function authorizeKillPreview(attempt, serviceId, authorized = false) {
  const row = attempt.participants.find(item => item.id === serviceId);
  if (attempt.phase !== 'reported' || row?.outcome !== 'blocked' || !authorized) throw new Error('Authorize only the specifically blocked service.');
  row.orderlyReport = { outcome: row.outcome, note: row.note };
  row.outcome = 'failed';
  row.note = 'Forced continuation authorized in the local example, but termination is unconfirmed. Cleanup and preservation remain unresolved. No command sent; manual assessment would be required.';
  return row;
}
