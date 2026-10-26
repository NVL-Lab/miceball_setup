let dialog;
let pendingStop = null;

// This gate has no execution state: only explicit confirmation invokes its caller.
export function confirmStop(kind, initiateStop) {
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.className = 'catalog-dialog';
    dialog.id = 'stop-confirmation';
    dialog.setAttribute('aria-labelledby', 'stop-confirmation-title');
    dialog.innerHTML = '<form method="dialog"><h2 id="stop-confirmation-title"></h2><p>Confirm to initiate the existing browser-local Stop workflow. Keeping it running or dismissing this dialog does not initiate a Stop.</p><div class="catalog-dialog__actions"><button type="button" class="dialog-button" data-keep-running>Keep Running</button><button type="button" class="dialog-button dialog-button--primary" data-confirm-stop>Confirm Stop</button></div></form>';
    document.body.append(dialog);
    dialog.querySelector('[data-keep-running]').addEventListener('click', () => {
      pendingStop = null;
      dialog.close();
    });
    dialog.addEventListener('cancel', () => { pendingStop = null; });
    dialog.addEventListener('close', () => { if (!dialog.open) pendingStop = null; });
    dialog.querySelector('[data-confirm-stop]').addEventListener('click', () => {
      const initiate = pendingStop;
      pendingStop = null;
      dialog.close();
      initiate?.();
    });
  }
  if (dialog.open) return;
  dialog.querySelector('#stop-confirmation-title').textContent = `Stop ${kind}?`;
  pendingStop = initiateStop;
  dialog.showModal();
  dialog.querySelector('[data-keep-running]').focus();
}
