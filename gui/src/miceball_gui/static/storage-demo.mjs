// Fictional, page-local readback examples. These are not framework records.
export function createStorageDemo() {
  const session = (id, owner, status, completedAt, verified, experiments) => ({
    id, name: `${id}_session`, owner, project: 'Visual Learning', animal: 'M1023', date: completedAt ? '2026-07-30' : '2026-10-24',
    status, completedAt, verified, unresolved: status === 'incomplete', size: null,
    availability: status === 'pending' ? 'Available in fixture only; live eligibility unavailable' : 'No new collection eligibility confirmed',
    experiments: experiments.map((name, index) => ({ id: `${id}-e${index + 1}`, name, verified,
      originals: 'Available (fictional)', node: 'Microscope AcquisitionNode', recordings: ['Scientific signal', 'Timing / index artifacts'], count: null })),
  });
  return { sessions: [
    session('demo-pending', 'Taylor Kim', 'pending', null, false, ['Initial imaging', 'Baseline recording']),
    session('demo-incomplete', 'Taylor Kim', 'incomplete', null, false, ['Baseline recording']),
    session('demo-collected', 'Taylor Kim', 'collected', '2026-10-26T12:00:00Z', true, ['Initial imaging']),
    session('demo-older', 'Taylor Kim', 'collected', '2026-08-01T12:00:00Z', true, ['Baseline recording']),
    session('demo-other', 'Morgan Lee', 'active', null, false, ['Initial imaging']),
  ], collection: new Set(), deletion: new Set(), deleteAfter: false };
}

export function visibleStorageSessions(model, owner, administrator) {
  return model.sessions.filter(session => administrator || !!owner && session.owner === owner);
}

export function selectCollection(model, sessions, id, selected = true) {
  if (!sessions.some(session => session.id === id)) return false;
  if (selected) model.collection.add(id); else model.collection.delete(id);
  return true;
}

export function selectDeletion(model, session, experimentId, selected) {
  const targets = session.experiments.filter(experiment => !experimentId || experiment.id === experimentId);
  for (const experiment of targets) {
    if (selected) model.deletion.add(experiment.id); else model.deletion.delete(experiment.id);
  }
}

export function storageSelection(model, sessions, kind) {
  return sessions.flatMap(session => kind === 'collection'
    ? model.collection.has(session.id) ? [{ session }] : []
    : session.experiments.filter(experiment => model.deletion.has(experiment.id)).map(experiment => ({ session, experiment })));
}

export function storageHistory(sessions, filters = {}, now = new Date()) {
  const cutoff = now.getTime() - 30 * 86400000;
  const query = (filters.query || '').trim().toLowerCase();
  return sessions.filter(session => {
    const searchable = [session.id, session.name, session.owner, session.project, session.animal, session.date, session.completedAt].join(' ').toLowerCase();
    if (query && !searchable.includes(query)) return false;
    if (filters.status && session.status !== filters.status) return false;
    return filters.older || query || filters.status || session.status !== 'collected' || session.unresolved || !session.completedAt || Date.parse(session.completedAt) >= cutoff;
  });
}

export function deletionReview(selection, acknowledged = false) {
  const risky = selection.some(({ session, experiment }) => !experiment.verified || ['failed', 'incomplete', 'uncertain'].includes(session.status));
  return { risky, canProceed: selection.length > 0 && (!risky || acknowledged) };
}
