export const escapeText = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
export function navigate(section) {
  document.dispatchEvent(new CustomEvent('gui-section', { detail: section }));
}
export function sessionIdentity() {
  const fields = document.querySelectorAll('.session-identity-grid input');
  const selected = id => document.querySelector(`#${id}`).selectedOptions[0]?.textContent || 'Not selected';
  return { name: fields[0].value || 'Unnamed Session', date: fields[1].value || 'Not set', experimenter: selected('experimenter-select'), owner: document.querySelector('#experimenter-select').value, project: selected('project-select'), animal: selected('animal-select') };
}
