// Presentation restriction only. Controller admission and operation-specific
// permissions remain authoritative; busy Controlling is still editable.
const inspection = [
  '.section-nav button', '.sidebar button', '#navigation-toggle', '#theme-toggle', '#pin-button',
  '#alerts-trigger', '#alerts-close', '#take-over', '#view-only', '[data-mode]',
  '[data-administrator-entry]', '[data-danger-enter]',
  '[data-section]', '[data-open-setup]', '[data-close-setup]',
  '[data-setup-parameters]', '[data-step-parameters]', '[data-return-session]',
  '[data-parameter-expand]', '[data-parameter-collapse]', '[data-session-step]',
  '[data-session-navigate]', '[data-experiment-parameters]', '[data-expand-output]',
  '[data-science-session]', '[data-close-validation]', '.roi-example-control select',
  '[data-trace-toggle]', '[data-detail]', '[data-expand-service]', '[data-toggle-history]',
  '[data-storage-workspace]', '[data-history-query]', '[data-history-status]', '[data-history-older]',
  '[data-storage-live-refresh]', '[data-storage-live-inspect]', '[data-storage-live-workspace]', '[data-storage-live-query]', '[data-storage-live-cancel]',
  '[data-refresh-services]', '[data-readiness]', '#services-refresh', '#load-inventory', '#inventory-node',
  '[data-destination-refresh]', '[data-refresh-interval]', '[data-dialog-dismiss]', '[data-stop-dismiss]',
  '[data-admin-close]', '[data-danger-cancel]', '[data-storage-cancel]',
  '[data-cancel-template-load]', '#cancel-protocol', 'dialog button[aria-label^="Close"]'
].join(',');
const previousDisabled = new Map();
const locked = () => document.documentElement.dataset.runtime === 'connected'
  && document.documentElement.dataset.controlMode !== 'controlling';
const editable = control => !control.matches(inspection);

function rememberChanges(records) {
  for (const record of records) if (record.type === 'attributes' && record.attributeName === 'disabled'
      && previousDisabled.has(record.target)) previousDisabled.set(record.target, record.target.disabled);
}

export function syncOwnershipPresentation() {
  rememberChanges(observer.takeRecords());
  const readonly = locked();
  for (const control of document.querySelectorAll('input, select, textarea, button')) {
    if (readonly && editable(control)) {
      if (!previousDisabled.has(control)) previousDisabled.set(control, control.disabled);
      if (!control.disabled) control.disabled = true;
    } else if (previousDisabled.has(control)) {
      control.disabled = previousDisabled.get(control); previousDisabled.delete(control);
    }
  }
  for (const control of previousDisabled.keys()) if (!control.isConnected) previousDisabled.delete(control);
  observer.takeRecords(); // Do not mistake our presentation changes for owner restrictions.
}
const observer = new MutationObserver(records => { rememberChanges(records); syncOwnershipPresentation(); });
observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true,
  attributeFilter: ['disabled', 'data-control-mode', 'data-runtime']});
// Capture also covers open dialogs, delegated handlers, keyboard and drag paths.
for (const type of ['click', 'beforeinput', 'input', 'change', 'submit', 'keydown', 'pointerdown', 'dragstart', 'drop']) {
  document.addEventListener(type, event => {
    if (!locked() || type === 'keydown' && ['Escape', 'Tab'].includes(event.key)) return;
    // Accepted readback refreshes the existing canonical date annotation through
    // an input notification; it is not an editing gesture or a command.
    if (type === 'input' && !event.isTrusted && event.target.matches('input[data-canonical-date]')) return;
    const control = event.target.closest('input, select, textarea, button');
    const drag = ['pointerdown', 'dragstart', 'drop'].includes(type)
      && event.target.closest('#editor-steps, [data-drag-session], [data-collection-bucket], [data-storage-live-drag], [data-storage-live-bucket]');
    if (type === 'submit' || drag || control && editable(control)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
}
