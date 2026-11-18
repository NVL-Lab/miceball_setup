// The existing page-local outcome collection, shared before connected startup.
export const activities = [];
const changed = entry => document.dispatchEvent(new CustomEvent('gui-activity-changed', {detail: entry}));
export function recordActivity(operation, source = 'local', status = 'pending', error = '') {
  const entry = {activity_id: String(activities.length + 1), operation, source, status, error, observed_at: new Date().toISOString()};
  activities.push(entry); changed(entry); return entry;
}
export function updateActivity(entry, changes) {
  Object.assign(entry, changes, {observed_at: new Date().toISOString()}); changed(entry);
}
export function recordLocalActivity(operation, error = '', status = error ? 'failed' : 'succeeded') {
  return recordActivity(operation, 'local', status, error);
}
export function recordActivityTransition(operation, status, error = '') {
  const previous = activities.findLast(entry => entry.operation === operation);
  if (previous?.status === status || !previous && status === 'succeeded') return;
  return recordLocalActivity(operation, error, status);
}
const invalidControls = new WeakMap();
export function recordInvalidControl(operation, control) {
  const issue = control.validationMessage;
  if (!issue) { invalidControls.delete(control); return; }
  if (invalidControls.get(control) === `${control.value}:${issue}`) return;
  invalidControls.set(control, `${control.value}:${issue}`);
  const label = control.getAttribute('aria-label') || control.closest('label')?.firstChild?.textContent?.trim() || 'Configuration field';
  return recordLocalActivity(operation, `${label}: ${issue}`);
}
