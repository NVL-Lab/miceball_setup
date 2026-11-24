// Transient Controller readback and explicit whole-Session collection, not a registry.
import {escapeText as esc} from './gui-presentation.js';
import {servicesAdministrator} from './services-view.js';
import {destinationManagementMarkup} from './artifact-destinations.js';
import {activityPresentation} from './activity-presentation.mjs';
import {activities} from './activity-history.mjs';

let adapter, history = null, current = false, loading = false, collecting = false;
let message = 'Historical Session information is unconfirmed.', workspace = 'collection';
let contextKey = '', revision = 0, query = '';
let renderKey = '';
const selected = new Set(), details = new Map(), results = new Map();
const panel = () => document.querySelector('#panel-storage');
const operator = () => {
  const select = document.querySelector('#experimenter-select');
  return {experimenter_name: select.value ? select.selectedOptions[0]?.textContent || '' : '', administrator_mode: servicesAdministrator()};
};
const context = () => JSON.stringify([adapter?.snapshot()?.instance_id, adapter?.snapshot()?.control, operator()]);
const eligible = row => row.collection_status?.eligible === true && row.collection_status?.collection_available === true;
const identity = row => row.accepted_session_config?.session_parameters?.name || row.session_id;
const json = value => esc(JSON.stringify(value, null, 2));
const button = (attribute, label, disabled = false) => `<button type="button" ${attribute} ${disabled ? 'disabled' : ''}>${label}</button>`;

function collectionLabel(row) {
  const latest = row.collection_history?.at(-1);
  if (!latest) return 'No confirmed collection outcome';
  const files = latest.payload?.artifact_results || [];
  return `${row.collection_progress?.outcome_archived ? 'Collection outcome archived' : 'Collection preservation unconfirmed'}; ${files.length} reported artifacts; ${files.filter(file => file.verification_status === 'verified').length} verified`;
}

export function renderConnectedStorage() {
  const root = panel();
  if (!root) return;
  const key = JSON.stringify([history, current, loading, collecting, message, workspace, query, [...selected], [...details], [...results].map(([id, entry]) => [id, entry.status, entry.result, entry.error]), adapter?.canControl(), destinationManagementMarkup()]);
  if (key === renderKey) return;
  renderKey = key;
  const opened = new Set([...root.querySelectorAll('details[open][data-storage-detail]')].map(item => item.dataset.storageDetail));
  const rows = history?.sessions || [], available = current && !loading && !collecting;
  const visible = rows.filter(row => JSON.stringify([row.session_id, row.accepted_session_config?.session_parameters]).toLowerCase().includes(query.toLowerCase()));
  root.innerHTML = `<header><h2 class="visually-hidden" id="heading-storage">Storage</h2><p>Controller-mediated historical readback and whole-Session collection. Collection never deletes originals.</p></header>
    <div class="storage-tabs">${button('data-storage-live-refresh', 'Refresh Sessions', !adapter || loading || collecting)}${button('data-storage-live-workspace="collection"', 'Collection')}${button('data-storage-live-workspace="history"', 'History')}${button('data-storage-live-workspace="deletion"', 'Delete originals')}</div>
    <p role="status" data-storage-live-feedback>${esc(message)}${history && !current ? ' Last-known history only; current availability unconfirmed.' : ''}</p>
    ${workspace === 'deletion' ? '<p>Original-recording deletion is not connected in this integration. Collection does not authorize deletion.</p>' : `
    <div class="storage-columns"><section class="storage-card"><h3>Available Sessions</h3>
    <label>Search Sessions<input type="search" data-storage-live-query value="${esc(query)}"></label>
    ${button('data-storage-live-pending', 'Collect everything pending', !available || !adapter?.canControl())}
    ${visible.map(row => `<article class="storage-session" draggable="${available && eligible(row) && adapter?.canControl() ? 'true' : 'false'}" data-storage-live-drag="${esc(row.session_id)}"><div class="storage-row"><div><strong>${esc(identity(row))}</strong><small>${esc(row.session_id)} · ${esc(row.experimenter_name || 'Owner unavailable')}</small></div>${button(`data-storage-live-add="${esc(row.session_id)}"`, selected.has(row.session_id) ? 'Added' : 'Add', !available || !eligible(row) || selected.has(row.session_id) || !adapter?.canControl())}</div>
      <p>${esc(row.collection_status?.lifecycle_state || 'Lifecycle unavailable')} · ${esc(collectionLabel(row))}</p>
      <p>${esc(row.collection_status?.availability_reason || row.collection_status?.eligibility_reason || 'StorageManager admission is checked again on collection.')}</p>
      <details data-storage-detail="${esc(row.session_id)}" ${opened.has(row.session_id) ? 'open' : ''}><summary>Session, Experiments and artifacts</summary>
      ${button(`data-storage-live-inspect="${esc(row.session_id)}"`, 'Read source details', !available)}
      <p>Recorded artifact count: ${esc(row.collection_progress?.artifact_count ?? 'unavailable')}. Source reachability is independent of historical discovery.</p>
      <pre>${json(details.get(row.session_id) || row)}</pre></details>
      ${results.has(row.session_id) ? `<p data-storage-live-result="${esc(row.session_id)}">${esc(activityPresentation(results.get(row.session_id)).message)}</p><pre>${json(results.get(row.session_id).result?.outcome?.details || {})}</pre>` : ''}</article>`).join('') || `<p>${current ? 'No matching historical Sessions in the confirmed readback.' : 'Historical Session discovery unavailable. No empty-history conclusion is implied.'}</p>`}
    </section><section class="storage-card storage-bucket"><h3>Collection bucket (${selected.size})</h3><div data-storage-live-bucket>${[...selected].map(id => `<div class="storage-row"><span>${esc(identity(rows.find(row => row.session_id === id) || {session_id: id}))} · ${esc(id)}</span>${button(`data-storage-live-remove="${esc(id)}"`, 'Remove', collecting)}</div>`).join('')}</div>
    <p>Whole Sessions only. Selection does not initiate transfer. Originals will not be deleted.</p>${button('data-storage-live-review', 'Store — review selection', !available || !selected.size || !adapter?.canControl())}</section></div>
    <section class="storage-card"><h3>Collection progress and capacity</h3><p>Per-file outcomes, verification and preservation are reported separately. Transfer speed and live byte progress are unavailable.</p><pre data-storage-live-capacity>${history?.capacity ? json(history.capacity) : 'Capacity unavailable'}</pre><p>Capacity is an owner observation, not collection admission or a complete total/used-space report.</p></section>`}`;
  root.insertAdjacentHTML('beforeend', destinationManagementMarkup());
}

export function syncConnectedStorage() {
  const key = context();
  if (key !== contextKey) {
    contextKey = key; revision++; current = false; history = null; details.clear(); selected.clear(); results.clear();
    message = 'Controller or operator context changed. Refresh Sessions; earlier requests are not replayed. Their outcomes remain in Activity History.';
  }
  for (const entry of activities.filter(entry => entry.operation === 'collect_saved_session_artifacts_remote' && entry.session_id))
    results.set(entry.session_id, entry);
  renderConnectedStorage();
}

export function invalidateConnectedStorage() {
  revision++; current = false;
  message = 'Controller connection unconfirmed. Refresh Sessions after reconnecting.';
  renderConnectedStorage();
}

export async function refreshConnectedStorage() {
  if (!adapter || loading || collecting) return;
  syncConnectedStorage();
  const version = revision;
  loading = true; message = 'Reading historical Sessions; confirmation pending.'; renderConnectedStorage();
  try {
    await adapter.refreshOutcomes();
    if (version !== revision) return;
    const data = await adapter.read('read_storage_sessions', operator(), null);
    if (version !== revision) return;
    if (!Array.isArray(data.sessions)) throw new Error('Historical Session response is invalid.');
    history = data; current = true; details.clear();
    for (const id of selected) if (!data.sessions.some(row => row.session_id === id && eligible(row))) selected.delete(id);
    message = `${data.sessions.length} historical Sessions received. Discovery is not collection.`;
  } catch (error) {
    if (version === revision) { current = false; message = `Historical readback unconfirmed: ${error.message}`; }
  } finally { loading = false; renderConnectedStorage(); }
}

async function inspectSession(id) {
  if (!current || loading || collecting) return;
  const version = revision;
  loading = true; message = 'Reading Session and original-owner details; confirmation pending.'; renderConnectedStorage();
  try {
    const data = await adapter.read('read_storage_session', operator(), id);
    if (version !== revision) return;
    if (data.session_id !== id) throw new Error('Historical Session identity mismatch.');
    details.set(id, data); message = 'Session details received. Unconfirmed original owners do not remove historical records.';
  } catch (error) { if (version === revision) message = `Source detail readback unconfirmed: ${error.message}. Historical Session information is retained.`; }
  finally { loading = false; renderConnectedStorage(); }
}

export function installConnectedStorage(operations) {
  adapter = operations;
  const dialog = document.createElement('dialog'); dialog.className = 'catalog-dialog storage-dialog'; document.body.append(dialog);
  panel().addEventListener('click', event => {
    const target = event.target.closest('button');
    if (!target || target.disabled) return;
    if (target.hasAttribute('data-storage-live-refresh')) { refreshConnectedStorage(); return; }
    if (target.dataset.storageLiveWorkspace) workspace = target.dataset.storageLiveWorkspace;
    if (target.dataset.storageLiveInspect) { inspectSession(target.dataset.storageLiveInspect); return; }
    if (target.dataset.storageLiveRemove && !collecting) selected.delete(target.dataset.storageLiveRemove);
    if (current && !collecting && adapter.canControl()) {
      if (target.dataset.storageLiveAdd && history.sessions.some(row => row.session_id === target.dataset.storageLiveAdd && eligible(row))) selected.add(target.dataset.storageLiveAdd);
      if (target.hasAttribute('data-storage-live-pending')) history.sessions.filter(row => eligible(row)
        && (!row.collection_history?.length || row.collection_history.at(-1).payload?.artifact_results?.some(file => file.collection_status !== 'success'))).forEach(row => selected.add(row.session_id));
      if (target.hasAttribute('data-storage-live-review') && selected.size) {
        const ids = [...selected], version = revision, owner = operator();
        dialog.innerHTML = `<h2>Review whole-Session collection</h2><ul>${ids.map(id => `<li>${esc(identity(history.sessions.find(row => row.session_id === id)))} · ${esc(id)}</li>`).join('')}</ul><p>StorageManager will revalidate eligibility, retrieve and verify artifacts, and preserve the actual outcome. No original recordings will be deleted.</p>${button('data-storage-live-cancel', 'Cancel')}${button('data-storage-live-confirm', 'Store')}`;
        dialog.querySelector('[data-storage-live-cancel]').onclick = () => dialog.close();
        dialog.querySelector('[data-storage-live-confirm]').onclick = async event => {
          if (collecting || version !== revision || !current || !adapter.canControl()) { dialog.close(); return; }
          event.target.disabled = true; dialog.close(); collecting = true;
          try {
            for (const id of ids) {
              if (version !== revision || !adapter.canControl()) { message = 'Remaining selections were not submitted: control or confirmation is unavailable.'; break; }
              message = `${id}: collection requested; awaiting authoritative outcome.`; renderConnectedStorage();
              const result = await adapter.collect(id, {...owner, evidence_id: crypto.randomUUID()});
              if (version !== revision) break;
              results.set(id, result);
              message = `${id}: ${activityPresentation(result).message}`;
              if (result.status === 'succeeded') selected.delete(id);
              renderConnectedStorage();
              if (['pending', 'uncertain', 'unknown'].includes(result.status)) { message += ' Remaining selections were not submitted; no automatic retry.'; break; }
            }
          } finally { collecting = false; if (version === revision) current = false; renderConnectedStorage(); }
        };
        dialog.showModal(); return;
      }
    }
    renderConnectedStorage();
  });
  panel().addEventListener('input', event => {
    if (!event.target.hasAttribute('data-storage-live-query')) return;
    const caret = event.target.selectionStart; query = event.target.value; renderConnectedStorage();
    const input = panel().querySelector('[data-storage-live-query]'); input.focus(); input.setSelectionRange(caret, caret);
  });
  panel().addEventListener('dragstart', event => {
    const source = event.target.closest('[data-storage-live-drag][draggable="true"]');
    if (source) event.dataTransfer.setData('text/plain', source.dataset.storageLiveDrag);
  });
  panel().addEventListener('dragover', event => { if (event.target.closest('[data-storage-live-bucket]')) event.preventDefault(); });
  panel().addEventListener('drop', event => {
    if (!event.target.closest('[data-storage-live-bucket]')) return;
    event.preventDefault();
    const id = event.dataTransfer.getData('text/plain');
    if (current && !loading && !collecting && adapter.canControl() && history.sessions.some(row => row.session_id === id && eligible(row))) selected.add(id);
    renderConnectedStorage();
  });
  document.addEventListener('gui-section-changed', event => { if (event.detail === 'storage' && !current) refreshConnectedStorage(); });
  for (const target of [document, document.querySelector('#experimenter-select')]) target.addEventListener(target === document ? 'gui-administrator-changed' : 'change', () => { dialog.close(); syncConnectedStorage(); });
  document.addEventListener('gui-activity-changed', () => renderConnectedStorage());
  syncConnectedStorage();
}
