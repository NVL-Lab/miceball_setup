import { describeRecordingSelection } from './recording-identity.mjs';

const dialog = document.createElement('dialog');
dialog.className = 'catalog-dialog';
dialog.id = 'recording-picker';
dialog.setAttribute('aria-labelledby', 'recording-picker-title');
dialog.innerHTML = `<form method="dialog"><h2 id="recording-picker-title">Load previous recording</h2><p>Select from any accessible Session or project. Selection alone is not scientific acceptance.</p><label>Recording file<input type="file" id="recording-file"></label><label>Recording folder<input type="file" id="recording-folder" webkitdirectory multiple></label><p class="catalog-dialog__note">Browser-native access only: filenames and, for supported folder selection, relative paths. No absolute filesystem path, file-content reading, upload, import or suitability check. Empty folders may not be selectable.</p><p id="recording-picker-selection" role="status">No new selection.</p><div class="catalog-dialog__actions"><button type="button" class="dialog-button" data-cancel-recording>Cancel</button><button type="button" class="dialog-button dialog-button--primary" data-use-recording disabled>Use selection</button></div></form>`;
document.body.append(dialog);
let pending = null;
let selected = null;
const useButton = dialog.querySelector('[data-use-recording]');
const folderInput = dialog.querySelector('#recording-folder');
folderInput.disabled = !('webkitdirectory' in folderInput);
if (folderInput.disabled) folderInput.parentElement.append('Folder selection is unavailable in this browser; choose a file instead.');
for (const [selector, kind] of [['#recording-file', 'file'], ['#recording-folder', 'folder']]) {
  const input = dialog.querySelector(selector);
  input.addEventListener('change', () => {
    const selection = describeRecordingSelection(input.files, kind);
    if (!selection) return;
    selected = selection;
    dialog.querySelector('#recording-picker-selection').textContent = `${selection.kind}: ${selection.name} · ${selection.entries.length} file(s). Metadata selected only; not accepted.`;
    useButton.disabled = false;
  });
}
dialog.querySelector('[data-cancel-recording]').addEventListener('click', () => { pending = null; dialog.close(); });
dialog.addEventListener('cancel', () => { pending = null; });
dialog.addEventListener('close', () => {
  if (dialog.open) return;
  pending = null; selected = null;
  dialog.querySelector('#recording-file').value = '';
  folderInput.value = '';
});
useButton.addEventListener('click', () => {
  const callback = pending, selection = selected;
  if (!callback || !selection) return;
  pending = null; selected = null;
  dialog.close();
  callback(selection);
});

export function openRecordingPicker(onSelect) {
  if (dialog.open) return;
  pending = onSelect; selected = null; useButton.disabled = true;
  dialog.querySelector('#recording-picker-selection').textContent = 'No new selection. Cancel keeps the existing operation and input unchanged.';
  dialog.showModal();
  dialog.querySelector('[data-cancel-recording]').focus();
}
