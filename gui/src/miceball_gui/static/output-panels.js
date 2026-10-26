// Expansion changes only the original panel's layout, never its contents.
let expandedPanel = null;
function restoreOutputPanel(returnFocus = false) {
  if (!expandedPanel) return;
  const panel = expandedPanel;
  panel.classList.remove('is-expanded');
  const button = panel.querySelector('[data-expand-output]');
  button.textContent = 'Expand ↗';
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-label', `Expand ${panel.dataset.outputTitle}`);
  expandedPanel = null;
  if (returnFocus) button.focus();
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-expand-output]');
  if (!button) return;
  const panel = button.closest('.output-panel');
  if (panel === expandedPanel) { restoreOutputPanel(true); return; }
  restoreOutputPanel();
  expandedPanel = panel;
  panel.classList.add('is-expanded');
  button.textContent = 'Restore ↙';
  button.setAttribute('aria-expanded', 'true');
  button.setAttribute('aria-label', `Restore ${panel.dataset.outputTitle}`);
});
document.addEventListener('keydown', event => { if (event.key === 'Escape' && expandedPanel) { event.preventDefault(); restoreOutputPanel(true); } });
document.addEventListener('gui-section-changed', () => restoreOutputPanel());
