import { createStorageDemo, visibleStorageSessions, selectCollection, selectDeletion, storageSelection, storageHistory, deletionReview } from './storage-demo.mjs';
import { escapeText as esc } from './gui-presentation.js';
import { servicesAdministrator } from './services-view.js';

const panel = document.querySelector('#panel-storage');
const model = createStorageDemo();
let workspace = 'collection', message = '', filters = {}, reviewSelection = [];
const dialog = document.createElement('dialog');
dialog.className = 'catalog-dialog storage-dialog';
dialog.setAttribute('aria-labelledby', 'storage-review-title');
document.body.append(dialog);
const sessions = () => visibleStorageSessions(model, document.querySelector('#experimenter-select').selectedOptions[0]?.textContent, servicesAdministrator());
const selection = kind => storageSelection(model, sessions(), kind);
const button = (attribute, label, disabled = false) => `<button type="button" ${attribute} ${disabled ? 'disabled' : ''}>${label}</button>`;
const status = session => `<span class="storage-status">${esc(session.status)} · fixture</span>`;
const identity = session => `<strong>${esc(session.name)}</strong><small>${esc(session.id)} · ${esc(session.owner)} · ${esc(session.project)} · ${esc(session.animal)} · ${esc(session.date)}</small>`;

function sessionBrowser(deleting = false) {
  return sessions().map(session => {
    const selected = session.experiments.filter(experiment => model.deletion.has(experiment.id)).length;
    return `<article class="storage-session" ${deleting ? '' : `draggable="true" data-drag-session="${session.id}"`}>
      <div class="storage-row">${deleting ? `<label><input type="checkbox" data-delete-session="${session.id}" ${selected === session.experiments.length ? 'checked' : ''}> Entire Session</label>` : ''}<div>${identity(session)}</div>${status(session)}${deleting ? '' : button(`data-add-session="${session.id}"`, model.collection.has(session.id) ? 'Added' : 'Add', model.collection.has(session.id))}</div>
      <p>${esc(session.availability)}. Estimated size: unavailable.</p>
      <details><summary>Experiments and recordings (${session.experiments.length} Experiments${deleting ? `; ${selected} selected` : ''})</summary>${session.experiments.map(experiment => `<div class="storage-experiment">${deleting ? `<label><input type="checkbox" data-delete-experiment="${experiment.id}" data-session="${session.id}" ${model.deletion.has(experiment.id) ? 'checked' : ''}> ${esc(experiment.name)}</label>` : `<strong>${esc(experiment.name)}</strong>`}<small>${esc(experiment.id)} · ${esc(experiment.node)}</small><p>Originals: ${esc(experiment.originals)} · ${experiment.verified ? 'Verified permanent copy (fictional)' : 'No verified permanent copy'}</p><ul>${experiment.recordings.map(recording => `<li>${esc(recording)} — inspection only</li>`).join('')}</ul><small>Artifact counts and exact target paths unavailable. ${deleting ? 'Selection includes all original scientific files, including timing/index files.' : 'Collection selects the whole Session only.'}</small></div>`).join('')}</details></article>`;
  }).join('') || '<p>No demonstration Sessions match this experimenter. Live Session discovery is unavailable.</p>';
}

function collection() {
  const selected = selection('collection');
  return `<div class="storage-columns"><section class="storage-card"><h3>Available Sessions</h3><p>Expand to inspect. Drag or Add a whole Session; selection does not start collection.</p>${button('data-add-pending', 'Collect everything pending')}${sessionBrowser()}</section><section class="storage-card storage-bucket" aria-label="Collection bucket"><h3>Collection bucket (${selected.length})</h3><div class="storage-drop-zone ${selected.length ? '' : 'is-empty'}" data-collection-bucket role="region" aria-label="Session drop zone">${selected.map(({ session }) => `<div class="storage-row storage-bucket-item"><div>${identity(session)}</div>${button(`data-remove-session="${session.id}"`, 'Remove')}</div>`).join('')}<p class="storage-drop-hint">${selected.length ? 'Drag more Sessions here, or click Add.' : 'Drag Sessions here, or click Add.'}</p></div><p class="storage-bucket-summary">${selected.length} Sessions selected · Estimated total size: unavailable</p><label class="storage-check"><input type="checkbox" data-delete-after ${model.deleteAfter ? 'checked' : ''}> Delete original recordings from AcquisitionNodes after verified collection.</label><p>Per Session: deletion requires verified collection, durable preservation evidence, exact-original safety and separate authorization. Failed, incomplete or uncertain collection never permits deletion.</p>${button('data-store-review', 'Store — review selection', !selected.length)}</section></div>
      <section class="storage-card"><h3>Collection progress and capacity</h3><p>Live transfer progress, speeds and completion times: unavailable. No transfer is running in this browser.</p><dl class="storage-capacity"><dt>Permanent storage total / used / available</dt><dd>Unavailable</dd><dt>AcquisitionNode source capacity</dt><dd>Unavailable</dd><dt>Collection-bucket estimated size</dt><dd>Unavailable</dd></dl><p>Transfer completion, verification and durable preservation are separate confirmations.</p>${model.sessions.filter(session => sessions().includes(session) && ['pending','active','incomplete'].includes(session.status)).map(session => `<p>${esc(session.name)}: ${status(session)} · transfer ${session.status === 'incomplete' ? 'incomplete' : session.status}; verification unconfirmed; durable preservation unconfirmed${session.unresolved ? '; outstanding preservation obligation (fixture)' : ''}.</p>`).join('')}</section>`;
}

function deletion() {
  const selected = selection('deletion');
  return `<section class="storage-card storage-delete"><h3>⚠ Delete AcquisitionNode originals</h3><p>Manual deletion may be requested before or after collection. Only original scientific files belonging to selected Experiments are in scope, including timing/index artifacts.</p><p>Existing StorageManager copies, global scientific data, Session/Experiment historical metadata, operational evidence and Permanent Session Evidence Archives remain untouched.</p>${sessionBrowser(true)}<p><strong>${selected.length} Experiments selected:</strong> ${selected.map(({ session, experiment }) => `${esc(session.name)} / ${esc(experiment.name)}`).join('; ') || 'None'}</p>${button('data-delete-review', 'Review deletion', !selected.length)}</section>`;
}

function history() {
  const rows = storageHistory(sessions(), filters);
  return `<section class="storage-card"><h3>Collection history</h3><p>Fictional readback only; live historical queries are unavailable. Default: all pending, active, failed/incomplete and unresolved entries; successful collections completed within 30 days. Older successes remain searchable.</p><div class="storage-filters"><label>Search Session, experimenter, project, animal or date<input data-history-query value="${esc(filters.query || '')}" type="search"></label><label>Collection status<select data-history-status><option value="">All statuses</option>${['pending','active','failed','incomplete','uncertain','collected'].map(value => `<option ${filters.status === value ? 'selected' : ''}>${value}</option>`).join('')}</select></label><label><input type="checkbox" data-history-older ${filters.older ? 'checked' : ''}> Include older successful collections</label></div>${rows.map(session => `<article class="storage-session">${identity(session)}${status(session)}<p>Collection completion: ${esc(session.completedAt || 'Unconfirmed')} · recording date: ${session.date}</p><p>Verification: ${session.verified ? 'verified (fixture)' : 'unconfirmed'} · durable preservation: ${session.verified ? 'confirmed in fictional fixture only' : 'unconfirmed'} · source deletion: unavailable${session.unresolved ? ' · unresolved preservation obligation (fixture)' : ''}</p></article>`).join('') || '<p>No matching fixture history. No live query was submitted.</p>'}</section>`;
}

function renderStorage() {
  panel.innerHTML = `<header><h2 id="heading-storage">Storage</h2><p>Browser-local demonstration · fictional Session fixtures, no collection or deletion requests.</p><p>Viewing: ${servicesAdministrator() ? 'Administrator — all fixture Sessions' : `Experimenter — ${esc(document.querySelector('#experimenter-select').selectedOptions[0]?.textContent || 'Not selected')}`}. Change identity in Setup; administrator mode in Services. Visibility is not backend authorization.</p></header><div class="storage-tabs" role="group" aria-label="Storage workspace">${[['collection','Collection'],['deletion','Delete originals'],['history','History']].map(([key,label]) => button(`data-storage-workspace="${key}" aria-pressed="${workspace === key}"`, label)).join('')}</div><p class="storage-feedback" role="status">${esc(message)}</p>${workspace === 'collection' ? collection() : workspace === 'deletion' ? deletion() : history()}`;
  panel.querySelectorAll('[data-delete-session]').forEach(input => {
    const session = sessions().find(item => item.id === input.dataset.deleteSession);
    const count = session.experiments.filter(item => model.deletion.has(item.id)).length;
    input.indeterminate = count > 0 && count < session.experiments.length;
  });
}

function openReview(deleting) {
  reviewSelection = selection(deleting ? 'deletion' : 'collection');
  if (!reviewSelection.length) return;
  const risky = deleting && deletionReview(reviewSelection).risky;
  dialog.classList.toggle('storage-delete', deleting);
  dialog.dataset.kind = deleting ? 'deletion' : 'collection';
  dialog.innerHTML = `<h2 id="storage-review-title">${deleting ? 'Delete AcquisitionNode originals' : 'Review whole-Session collection'}</h2><p>Fictional selection only</p><ul>${reviewSelection.map(({ session, experiment }) => `<li>${esc(session.name)} (${esc(session.id)})${experiment ? ` / ${esc(experiment.name)} (${esc(experiment.id)}) — ${experiment.verified ? 'Verified permanent copy (fixture)' : 'No verified permanent copy'}; collection ${esc(session.status)}` : ''}</li>`).join('')}</ul>${deleting ? `<p>All original scientific files of these Experiments, including timing/index artifacts. Exact targets require framework readback. StorageManager/global copies, historical metadata, operational evidence and Permanent Session Evidence Archives remain untouched.</p><p class="storage-risk">${risky ? 'Risk of irreversible scientific-data loss: some data have no verified copy or incomplete/uncertain collection.' : 'Verified-copy fixtures still require explicit confirmation and local safety admission.'}</p>${risky ? '<label><input type="checkbox" data-risk-ack> I understand that scientific data without a verified copy may be permanently lost.</label>' : ''}` : `<p>Estimated size unavailable. Conditional deletion: ${model.deleteAfter ? 'requested for each selected Session only after verified collection, durable preservation and safety admission' : 'not selected'}. Selection cannot establish live eligibility.</p>`}<p>No framework interface is connected. Proceeding submits no request and changes no files or preservation state.</p><div class="catalog-dialog__actions">${button('data-storage-cancel','Cancel')}${button('data-storage-proceed', deleting ? 'Delete originals' : 'Store', risky)}</div>`;
  dialog.showModal();
  dialog.querySelector('[data-storage-cancel]').focus();
}

panel.addEventListener('click', event => {
  const target = event.target.closest('button');
  if (!target) return;
  if (target.dataset.storageWorkspace) { workspace = target.dataset.storageWorkspace; message = ''; }
  if (target.dataset.addSession) selectCollection(model, sessions(), target.dataset.addSession);
  if (target.dataset.removeSession) selectCollection(model, sessions(), target.dataset.removeSession, false);
  if (target.hasAttribute('data-add-pending')) sessions().filter(session => session.status === 'pending').forEach(session => selectCollection(model, sessions(), session.id));
  if (target.hasAttribute('data-store-review')) { openReview(false); return; }
  if (target.hasAttribute('data-delete-review')) { openReview(true); return; }
  renderStorage();
});
panel.addEventListener('input', event => {
  if (!event.target.hasAttribute('data-history-query')) return;
  const value = event.target.value;
  const caret = event.target.selectionStart;
  filters.query = value;
  renderStorage();
  const input = panel.querySelector('[data-history-query]');
  input.focus({ preventScroll: true });
  input.setSelectionRange(caret, caret);
});
panel.addEventListener('change', event => {
  const input = event.target;
  if (input.hasAttribute('data-delete-after')) model.deleteAfter = input.checked;
  if (input.dataset.deleteSession) selectDeletion(model, sessions().find(session => session.id === input.dataset.deleteSession), null, input.checked);
  if (input.dataset.deleteExperiment) selectDeletion(model, sessions().find(session => session.id === input.dataset.session), input.dataset.deleteExperiment, input.checked);
  if (input.hasAttribute('data-history-query')) filters.query = input.value;
  if (input.hasAttribute('data-history-status')) filters.status = input.value;
  if (input.hasAttribute('data-history-older')) filters.older = input.checked;
  // Keep expanded Session rows and focus intact during checkbox selection.
  const opened = [...panel.querySelectorAll('details')].map(item => item.open);
  renderStorage(); panel.querySelectorAll('details').forEach((item,index) => item.open = opened[index]);
});
panel.addEventListener('dragstart', event => {
  const source = event.target.closest('[data-drag-session]');
  if (source) event.dataTransfer.setData('text/plain', source.dataset.dragSession);
});
panel.addEventListener('dragover', event => {
  const zone = event.target.closest('[data-collection-bucket]');
  if (!zone) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
  zone.classList.add('is-drag-over');
});
panel.addEventListener('dragleave', event => {
  const zone = event.target.closest('[data-collection-bucket]');
  if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drag-over');
});
panel.addEventListener('dragend', () => panel.querySelector('[data-collection-bucket]')?.classList.remove('is-drag-over'));
panel.addEventListener('drop', event => {
  if (!event.target.closest('[data-collection-bucket]')) return;
  event.preventDefault(); selectCollection(model, sessions(), event.dataTransfer.getData('text/plain')); renderStorage();
});
dialog.addEventListener('change', () => { dialog.querySelector('[data-storage-proceed]').disabled = !deletionReview(reviewSelection, dialog.querySelector('[data-risk-ack]')?.checked).canProceed; });
dialog.addEventListener('click', event => {
  if (event.target === dialog || event.target.closest('[data-storage-cancel]')) dialog.close();
  if (event.target.closest('[data-storage-proceed]')) {
    if (dialog.dataset.kind === 'deletion' && !deletionReview(reviewSelection, dialog.querySelector('[data-risk-ack]')?.checked).canProceed) return;
    message = 'Awaiting framework integration. No request was submitted; no files were collected or deleted. Existing records and preservation state are unchanged.';
    dialog.close(); renderStorage();
  }
});
document.addEventListener('gui-section-changed', event => { if (event.detail === 'storage') renderStorage(); });
document.addEventListener('gui-administrator-changed', () => { dialog.close(); reviewSelection = []; renderStorage(); });
document.querySelector('#experimenter-select').addEventListener('change', () => { dialog.close(); reviewSelection = []; renderStorage(); });
renderStorage();
