import { catalogClient, removeCatalog } from './catalog-client.mjs';
import { recordActivity, updateActivity } from './activity-history.mjs';

let confirmation;
export async function confirmCatalogRemoval(collection, identity, actor, administrator = false) {
  if (confirmation?.open || catalogClient.pending || !catalogClient.snapshot) return;
  const snapshot = catalogClient.snapshot;
  const target = snapshot.catalog[collection].find(item => item.id === identity);
  if (!target) return;
  const mode = administrator ? await import('./services-view.js') : null;
  if (administrator && !mode.servicesAdministrator()) return;
  if (!administrator && (target.owner !== actor || target.protected)) return;
  if (!confirmation) {
    confirmation = document.createElement('dialog');
    confirmation.className = 'catalog-dialog';
    confirmation.setAttribute('aria-labelledby', 'catalog-remove-title');
    confirmation.innerHTML = '<h2 id="catalog-remove-title">Remove catalog entry?</h2><p data-remove-target></p><div class="catalog-dialog__actions"><button type="button" class="dialog-button" data-remove-cancel>Cancel</button><button type="button" class="dialog-button" data-remove-confirm>Remove</button></div>';
    document.body.append(confirmation);
    confirmation.querySelector('[data-remove-cancel]').onclick = () => confirmation.close();
  }
  const label = target.animal_id || target.name;
  const dependents = collection === 'projects' ? ['animals', 'protocols', 'templates'].flatMap(key =>
    snapshot.catalog[key].filter(item => item.projectId === identity).map(item => item.animal_id || item.name)) : [];
  confirmation.querySelector('[data-remove-target]').textContent = `${label} · ${identity}${dependents.length ? ` — also removes: ${dependents.join(', ')}` : ''}`;
  const submit = confirmation.querySelector('[data-remove-confirm]');
  submit.disabled = false;
  submit.onclick = async () => {
    if (administrator && !mode.servicesAdministrator()) { confirmation.close(); return; }
    submit.disabled = true;
    const activity = recordActivity('remove_catalog');
    try {
      await removeCatalog(collection, identity, administrator ? mode.servicesAdministratorName() : actor,
        administrator, snapshot.revision);
      updateActivity(activity, {status: 'succeeded'});
      confirmation.close();
    } catch (error) {
      updateActivity(activity, {status: error.catalogStatus || 'failed', error: error.message});
      confirmation.querySelector('[data-remove-target]').textContent = error.message;
      // A stale confirmation must be reviewed again, never silently retried.
    }
  };
  confirmation.oncancel = event => { if (submit.disabled) event.preventDefault(); };
  confirmation.showModal();
}

export function initializeCatalogManagement() {
  const card = document.createElement('section');
  card.className = 'setup-card'; card.hidden = true;
  card.innerHTML = '<details class="setup-disclosure"><summary><h3>Catalog management</h3></summary><div class="setup-disclosure-body"><label>Category<select data-catalog-category><option value="experimenters">Experimenters</option><option value="projects">Projects</option><option value="animals">Animals</option><option value="protocols">Protocols</option><option value="templates">Session templates</option><option value="definitions">Saved Steps</option><option value="experimentTemplates">Experiment templates</option></select></label><label>Entry<select data-catalog-entry></select></label><button type="button" class="dialog-button" data-catalog-remove>Remove</button></div></details>';
  document.querySelector('.identity-card').after(card);
  const category = card.querySelector('[data-catalog-category]');
  const entry = card.querySelector('[data-catalog-entry]');
  const remove = card.querySelector('[data-catalog-remove]');
  const render = () => {
    const wasHidden = card.hidden;
    card.hidden = document.documentElement.dataset.administrator !== 'true';
    if (card.hidden || wasHidden) card.querySelector('details').open = false;
    const previous = entry.value;
    entry.replaceChildren(new Option('Not selected', ''));
    for (const item of catalogClient.snapshot?.catalog[category.value] || []) {
      entry.add(new Option(`${item.animal_id || item.name} · ${item.id}`, item.id));
    }
    entry.value = [...entry.options].some(option => option.value === previous) ? previous : '';
    remove.disabled = !entry.value || catalogClient.pending;
  };
  category.onchange = () => { entry.value = ''; render(); };
  entry.onchange = render;
  remove.onclick = () => confirmCatalogRemoval(category.value, entry.value, '', true);
  document.addEventListener('gui-catalog-changed', render);
  document.addEventListener('gui-administrator-changed', render);
  render();
}
