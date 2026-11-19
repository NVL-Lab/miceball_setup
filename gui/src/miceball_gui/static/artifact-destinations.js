// A transient projection of StorageManager's registry, never a destination authority.
import { escapeText as esc } from './gui-presentation.js';
import { servicesAdministrator, servicesAdministratorName } from './services-view.js';
import { activityPresentation } from './activity-presentation.mjs';
import { catalogId } from './catalog-client.mjs';
import { recordActivity, updateActivity, recordActivityTransition } from './activity-history.mjs';

let adapter, catalog = null, current = false, loading = false, selection = '', initialized = false;
let feedback = 'Destination information is unconfirmed.';
let selectionSignature = '', managementSignature = '', acceptedSession = null;
let managementEntry = null, managementStatus = '';
const change = () => document.dispatchEvent(new Event('gui-destinations-changed'));
const choices = () => catalog?.destinations || [];
const capacity = entry => Number.isSafeInteger(entry.validation?.available_bytes)
  ? `${new Intl.NumberFormat().format(entry.validation.available_bytes)} bytes available` : 'Capacity unavailable';
const observation = entry => `${entry.validation?.status || 'unverified'} · ${capacity(entry)} · ${entry.validation?.reason || 'Admission requires StorageManager confirmation'}`;

export function destinationManagementMarkup() {
  if (!adapter || !servicesAdministrator()) return '';
  return `<section class="storage-card artifact-destinations" aria-labelledby="destinations-title"><h3 id="destinations-title">Scientific artifact destinations</h3><p>StorageManager owns these destinations. Changes do not move data or change accepted Sessions.</p><button type="button" class="dialog-button" data-destination-refresh ${loading ? 'disabled' : ''}>Refresh destinations</button><p role="status">${esc(feedback)}</p>${choices().map(entry => `<article class="storage-session"><div class="storage-row"><strong>${esc(entry.name)}${entry.destination_id === catalog.default_destination_id ? ' · Installation default' : ''}</strong><span>${entry.enabled ? 'Enabled' : 'Disabled'}</span></div><p class="destination-root">${esc(entry.root)}</p><p>${esc(current ? observation(entry) : 'Last known · current availability unconfirmed')}</p>${entry.destination_id === catalog.default_destination_id ? '' : `<div class="storage-tabs"><button type="button" class="dialog-button" data-destination-toggle="${esc(entry.destination_id)}" ${!adapter.canControl() || !current || loading ? 'disabled' : ''}>${entry.enabled ? 'Disable' : 'Enable'}</button><button type="button" class="dialog-button" data-destination-remove="${esc(entry.destination_id)}" ${!adapter.canControl() || !current || loading ? 'disabled' : ''}>Remove registration</button></div>`}</article>`).join('')}<button type="button" class="dialog-button" data-destination-register ${!adapter.canControl() || !current || loading ? 'disabled' : ''}>Register destination</button></section>`;
}

function renderSelection() {
  const select = document.querySelector('#artifact-destination');
  if (!select || !adapter) return;
  const snapshot = adapter.snapshot(), accepted = snapshot?.status?.session_id ? snapshot.configuration?.storage_location : null;
  if (snapshot?.status?.session_id) acceptedSession = snapshot.status.session_id;
  else if (acceptedSession && current) {
    // A confirmed release begins fresh preparation; connection loss does not.
    acceptedSession = null; selection = catalog?.default_destination_id || '';
  }
  const value = accepted ?? selection;
  const signature = JSON.stringify([catalog, current, loading, value, snapshot?.status?.session_id, feedback]);
  if (signature === selectionSignature) return;
  selectionSignature = signature;
  select.replaceChildren(new Option('Select an approved destination', ''));
  for (const entry of choices()) {
    const option = new Option(`${entry.name}${entry.destination_id === catalog.default_destination_id ? ' · Installation default' : ''}${entry.enabled ? '' : ' · Disabled'}`, entry.destination_id);
    option.disabled = !entry.enabled || entry.validation?.status === 'invalid';
    select.add(option);
  }
  if (value && !choices().some(entry => entry.destination_id === value)) select.add(new Option('Destination information unavailable', value));
  select.value = value || '';
  select.disabled = Boolean(snapshot?.status?.session_id) || !current || loading;
  const entry = choices().find(item => item.destination_id === value);
  document.querySelector('#artifact-destination-info').textContent = accepted != null
    ? `Controller-confirmed Session destination: ${entry?.name || 'name unavailable'}. Fixed for every Experiment.${loading ? ` ${feedback}` : current ? '' : ' Current availability unconfirmed.'}`
    : loading || !current ? feedback : entry ? `${entry.enabled ? '' : 'Disabled. '}${observation(entry)}. StorageManager rechecks at launch.` : 'Choose an approved destination. No alternative will be selected automatically.';
}

export function syncArtifactDestinations() {
  if (managementEntry && managementEntry.status !== managementStatus) {
    managementStatus = managementEntry.status;
    feedback = activityPresentation(managementEntry).message;
    const status = document.querySelector('[data-destination-dialog-status]');
    if (status) status.textContent = feedback;
    if (managementStatus === 'succeeded') refreshArtifactDestinations();
  }
  renderSelection();
  const signature = destinationManagementMarkup();
  if (signature !== managementSignature) { managementSignature = signature; change(); }
}

export function invalidateArtifactDestinations() {
  current = false;
  feedback = 'Destination information is unconfirmed. Refresh after reconnecting.';
  syncArtifactDestinations();
}

export async function refreshArtifactDestinations(explicit = false) {
  if (!adapter || loading) return;
  loading = true;
  const activity = explicit ? recordActivity('destination_discovery', 'controller') : null;
  feedback = 'Refreshing destinations; pending confirmation.';
  renderSelection(); change();
  try {
    const result = await adapter.read();
    if (!result || !Array.isArray(result.destinations)) throw new Error('Destination information could not be confirmed.');
    catalog = result; current = true;
    const unavailable = choices().filter(entry => entry.enabled && entry.validation?.status === 'invalid');
    const status = unavailable.length ? 'unknown' : 'succeeded';
    const error = unavailable.map(entry => `${entry.name}: ${entry.validation.reason || 'unavailable'}`).join('; ');
    if (activity) updateActivity(activity, {status, error});
    else recordActivityTransition('destination_discovery', status, error);
    if (!initialized) { selection ||= result.default_destination_id || ''; initialized = true; }
    feedback = 'Approved destinations received. Availability is rechecked by StorageManager at launch.';
  } catch (error) {
    current = false;
    if (activity) updateActivity(activity, {status: 'unknown', error: error.message});
    else recordActivityTransition('destination_discovery', 'unknown', error.message);
    feedback = activity ? activityPresentation(activity).message : 'Destination information unavailable. See Activity History in Services.';
  }
  finally { loading = false; syncArtifactDestinations(); }
}

export function selectedArtifactDestination() {
  const entry = choices().find(item => item.destination_id === selection);
  if (!current || !entry || !entry.enabled || entry.validation?.status === 'invalid')
    throw new Error('Select an available approved scientific destination. Refresh destinations if confirmation is unavailable.');
  return entry.destination_id;
}

export function installArtifactDestinations(operations) {
  adapter = operations;
  const input = document.querySelector('[aria-labelledby="storage-title"] input');
  const label = input.closest('label');
  label.firstChild.textContent = 'Scientific artifact destination';
  const select = document.createElement('select'); select.id = 'artifact-destination';
  select.setAttribute('aria-describedby', 'artifact-destination-info'); input.replaceWith(select);
  const info = document.createElement('p'); info.id = 'artifact-destination-info'; info.setAttribute('role', 'status');
  label.after(info);
  const browse = document.querySelector('[aria-labelledby="storage-title"] button');
  browse.textContent = 'Refresh destinations'; browse.disabled = false; browse.type = 'button';
  browse.removeAttribute('title');
  browse.addEventListener('click', () => refreshArtifactDestinations(true));
  select.addEventListener('change', () => { selection = select.value; initialized = true; renderSelection(); });
  const dialog = document.createElement('dialog'); dialog.className = 'catalog-dialog'; document.body.append(dialog);
  dialog.setAttribute('aria-labelledby', 'destination-dialog-title');
  document.addEventListener('click', event => {
    if (event.target.closest('[data-destination-refresh]')) { refreshArtifactDestinations(true); return; }
    const button = event.target.closest('[data-destination-register], [data-destination-toggle], [data-destination-remove]');
    if (!button || button.disabled || !servicesAdministrator() || !adapter.canControl() || !current || loading) return;
    const entry = choices().find(item => item.destination_id === (button.dataset.destinationToggle || button.dataset.destinationRemove));
    const registration = button.hasAttribute('data-destination-register'), remove = button.hasAttribute('data-destination-remove');
    const title = registration ? 'Register scientific destination' : `${remove ? 'Remove registration for' : entry.enabled ? 'Disable' : 'Enable'} ${entry.name}`;
    dialog.innerHTML = `<form><h2 id="destination-dialog-title">${esc(title)}</h2><p>${remove ? 'StorageManager refuses removal when retained Session bindings require this destination. Files will not be deleted.' : 'StorageManager validates and confirms the request. No disks will be mounted and no recordings moved.'}</p><label>Administrator name<input name="administrator" required></label>${registration ? '<label>Destination name<input name="name" required></label><label>Existing directory on the StorageManager computer<input name="root" required></label>' : ''}<p role="status" data-destination-dialog-status></p><div class="catalog-dialog__actions"><button type="button" class="dialog-button" data-destination-cancel>Cancel</button><button type="submit" class="dialog-button">Confirm</button></div></form>`;
    dialog.querySelector('[name="administrator"]').value = servicesAdministratorName();
    dialog.querySelector('[name="administrator"]').readOnly = true;
    dialog.querySelector('[data-destination-cancel]').onclick = () => dialog.close();
    // Stable identity survives an uncertain attempt; there is no automatic replay.
    const destinationId = registration ? catalogId() : entry.destination_id;
    dialog.querySelector('form').onsubmit = async event => {
      event.preventDefault();
      if (!servicesAdministrator() || !adapter.canControl()) return;
      const data = new FormData(event.target);
      const parameters = {experimenter_name: data.get('administrator'), administrator_mode: true,
        destination_id: destinationId, ...(registration ? {name: data.get('name'), root: data.get('root')} : {enabled: remove ? false : !entry.enabled, remove})};
      const submit = dialog.querySelector('[type="submit"]'); submit.disabled = true;
      const result = await adapter.command(registration ? 'register_artifact_destination' : 'update_artifact_destination', parameters);
      managementEntry = result; managementStatus = result.status;
      feedback = activityPresentation(result).message;
      dialog.querySelector('[data-destination-dialog-status]').textContent = feedback;
      if (result.status === 'succeeded') { dialog.close(); await refreshArtifactDestinations(); }
      else { current = false; syncArtifactDestinations(); }
      // Failed/uncertain requests require dismissal and explicit current readback.
    };
    dialog.showModal();
  });
  document.addEventListener('gui-administrator-changed', () => dialog.close());
  renderSelection();
}
