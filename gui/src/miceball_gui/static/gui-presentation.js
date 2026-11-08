import { configurationStringText, parseConfigurationString } from './configuration-values.mjs';

export const escapeText = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
export function executionIdentity(state) {
  return state.activeSession?.identity || sessionIdentity();
}
export function navigate(section) {
  document.dispatchEvent(new CustomEvent('gui-section', { detail: section }));
}
export function sessionIdentity() {
  const fields = document.querySelectorAll('.session-identity-grid :is(input, textarea)');
  const selected = id => document.querySelector(`#${id}`).selectedOptions[0]?.textContent || 'Not selected';
  let name = fields[0].value;
  if (fields[0].hasAttribute('data-configuration-string')) {
    try { name = readConfigurationString(fields[0]); } catch (_) { name = 'Invalid text value'; }
  }
  return { name: name || 'Unnamed Session', date: fields[1].value || 'Not set', experimenter: selected('experimenter-select'), owner: document.querySelector('#experimenter-select').value, project: selected('project-select'), animal: selected('animal-select') };
}
function needsExactCharacters(value) {
  return typeof value !== 'string' || /[\r\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/.test(value)
    || [...value].some(character => character.length === 1 && /[\ud800-\udfff]/.test(character));
}
export function setConfigurationString(control, value) {
  // Native textareas normalize CR. Keep the existing lossless editor for values
  // needing exact code units; ordinary text never acquires JSON syntax.
  const exact = needsExactCharacters(value);
  control.dataset.stringEncoding = exact ? 'exact' : 'text';
  control.value = exact ? configurationStringText(value) : value;
  control.setCustomValidity(value?.invalidString !== undefined ? 'Invalid exact-character representation.' : '');
  const toggle = control.nextElementSibling;
  if (toggle?.hasAttribute('data-string-mode')) toggle.textContent = exact ? 'Use ordinary text' : 'Edit exact characters';
}
export function readConfigurationString(control) {
  return control.dataset.stringEncoding === 'exact' ? parseConfigurationString(control.value) : control.value;
}
export function configurationStringEditor(control, value = control.value) {
  const editor = document.createElement('textarea');
  for (const attribute of control.attributes) if (!['type', 'value'].includes(attribute.name)) editor.setAttribute(attribute.name, attribute.value);
  editor.rows = control.rows || 1;
  editor.classList.add('configuration-string');
  editor.dataset.configurationString = '';
  const toggle = document.createElement('button'); toggle.type = 'button'; toggle.dataset.stringMode = '';
  toggle.className = 'string-mode-button';
  toggle.title = 'Ordinary text needs no quotation marks. Exact-character mode uses an escaped string for control characters.';
  control.replaceWith(editor, toggle);
  setConfigurationString(editor, value);
  const insertExact = (event, text) => {
    if (!event.cancelable || editor.readOnly || editor.matches(':disabled')
        || editor.dataset.stringEncoding !== 'text' || typeof text !== 'string' || !needsExactCharacters(text)) return;
    event.preventDefault();
    const next = editor.value.slice(0, editor.selectionStart) + text + editor.value.slice(editor.selectionEnd);
    setConfigurationString(editor, next);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
  };
  // Capture the original transfer before native CR/LF normalization.
  editor.addEventListener('paste', event => insertExact(event, event.clipboardData?.getData('text/plain')));
  editor.addEventListener('beforeinput', event => insertExact(event, event.dataTransfer?.getData('text/plain') ?? event.data));
  toggle.addEventListener('click', () => {
    if (editor.disabled || editor.readOnly || editor.matches(':disabled')) return;
    let current;
    try { current = readConfigurationString(editor); }
    catch (_) { editor.reportValidity(); return; }
    if (editor.dataset.stringEncoding === 'text') {
      editor.dataset.stringEncoding = 'exact'; editor.value = configurationStringText(current);
      toggle.textContent = 'Use ordinary text';
    } else {
      setConfigurationString(editor, current);
      if (editor.dataset.stringEncoding === 'exact') {
        toggle.title = 'This value requires exact-character mode to preserve its control characters.';
        return;
      }
    }
    editor.setCustomValidity(''); // Changing representation does not set an absent/null override.
  });
  return editor;
}
