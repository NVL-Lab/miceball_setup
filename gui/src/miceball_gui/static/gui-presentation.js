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
    try { name = parseConfigurationString(name); } catch (_) { name = 'Invalid JSON string'; }
  }
  return { name: name || 'Unnamed Session', date: fields[1].value || 'Not set', experimenter: selected('experimenter-select'), owner: document.querySelector('#experimenter-select').value, project: selected('project-select'), animal: selected('animal-select') };
}
export function configurationStringEditor(control) {
  const editor = document.createElement('textarea');
  for (const attribute of control.attributes) if (!['type', 'value'].includes(attribute.name)) editor.setAttribute(attribute.name, attribute.value);
  editor.rows = control.rows || 1;
  editor.classList.add('configuration-string');
  editor.dataset.configurationString = '';
  editor.value = configurationStringText(control.value);
  const label = document.createElement('small'); label.textContent = 'JSON string';
  control.replaceWith(label, editor);
  return editor;
}
