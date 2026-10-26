import { createServicesDemo, setServicesAdministrator, refreshServicesPreview, serviceReadinessLabel, beginShutdownPreview, finishShutdownPreview, authorizeKillPreview, notificationHistoryView } from './services-demo.mjs';
import { notificationHistory, acknowledgeNotification } from './app.js';
import { escapeText as escape } from './gui-presentation.js';

const panel = document.querySelector('#panel-services');
const model = createServicesDemo();
let refreshTimer;
let message = '';
let expandedService = null, shutdownAttempt = null, killTarget = null;
let historyExpanded = false;
const danger = document.createElement('dialog');
danger.className = 'catalog-dialog services-danger';
danger.setAttribute('aria-labelledby', 'services-danger-title');
danger.innerHTML = `<h2 id="services-danger-title">Danger Zone — Administrator Mode</h2><p>Administrator mode exposes advanced operations that can stop framework services, force termination, or affect unresolved recovery and data-preservation obligations.</p><p>These actions may interrupt ongoing experiments or risk loss of scientific data or operational evidence. Only enter if you understand the consequences and intend to perform administrative work.</p><p>This is a trust-based presentation safeguard, not authentication or operation authorization. This demo sends no commands.</p><div class="catalog-dialog__actions"><button type="button" data-danger-cancel>Cancel</button><button type="button" data-danger-enter>Enter Administrator Mode</button></div>`;
document.body.append(danger);
danger.querySelector('[data-danger-cancel]').addEventListener('click', () => danger.close());
danger.querySelector('[data-danger-enter]').addEventListener('click', () => {
  setServicesAdministrator(model, true, true); danger.close(); renderServices();
  panel.querySelector('[data-mode="administrator"]').focus({ preventScroll: true });
});
const administrativePreview = document.createElement('dialog');
administrativePreview.className = 'catalog-dialog services-danger';
administrativePreview.setAttribute('aria-labelledby', 'admin-preview-title');
document.body.append(administrativePreview);
administrativePreview.addEventListener('click', event => {
  if (event.target.closest('[data-confirm-shutdown]')) { shutdownAttempt = beginShutdownPreview(model, administrativePreview.dataset.stopService || null); renderShutdownPreview(); return; }
  if (event.target.closest('[data-finish-shutdown]')) { finishShutdownPreview(shutdownAttempt); renderShutdownPreview(); return; }
  if (event.target.closest('[data-kill-service]')) {
    killTarget = event.target.closest('[data-kill-service]').dataset.killService;
    const row = shutdownAttempt.participants.find(r=>r.id === killTarget);
    administrativePreview.innerHTML = `<h2 id="admin-preview-title">Kill Service — explicit authorization</h2><p>Target: ${escape(row.name)} · ${escape(row.computer)}</p><p>Force may lose unpreserved scientific data or operational evidence and leave cleanup or preservation unresolved. This authorizes no other service, Session Kill or Experiment Stop.</p><label><input type="checkbox" data-kill-authorization> Authorize only this service's forced continuation in the local demonstration.</label><div class="catalog-dialog__actions"><button type="button" data-cancel-kill>Cancel</button><button type="button" data-confirm-kill disabled>Confirm Kill Service preview</button></div>`;
    administrativePreview.querySelector('[data-cancel-kill]').focus(); return;
  }
  if (event.target.closest('[data-cancel-kill]')) { killTarget = null; renderShutdownPreview(); return; }
  if (event.target.closest('[data-confirm-kill]') && administrativePreview.querySelector('[data-kill-authorization]')?.checked) { authorizeKillPreview(shutdownAttempt, killTarget, true); killTarget = null; renderShutdownPreview(); return; }
  if (event.target.closest('[data-admin-close]')) administrativePreview.close();
  if (event.target.closest('[data-admin-review]') && administrativePreview.querySelector('[name="confirm-scope"]')?.checked) {
    administrativePreview.querySelector('[data-admin-outcome]').textContent = 'Scope/risk review recorded in this local preview only. No command sent. Service-owned authorization and current safety prerequisites are unavailable; execution and its outcome remain unconfirmed. Existing reports, obligations and scientific results are unchanged.';
  }
});
administrativePreview.addEventListener('change', event => {
  if (event.target.hasAttribute('data-kill-authorization')) administrativePreview.querySelector('[data-confirm-kill]').disabled = !event.target.checked;
  if (event.target.name === 'confirm-scope') administrativePreview.querySelector('[data-admin-review]').disabled = !event.target.checked;
});

function serviceRows() {
  return model.services.map(service => `<li><div class="service-row ${expandedService === service.id ? 'is-selected' : ''}" data-expand-service="${service.id}" role="button" tabindex="0" aria-expanded="${expandedService === service.id}" aria-controls="detail-${service.id}" aria-label="${escape(service.name)} · ${escape(service.computer)}"><div class="service-identity"><strong>${escape(service.name)}</strong><small>${escape(service.computer)}</small></div><div class="service-report"><span class="service-status ${service.current && service.readiness === 'Ready' ? 'service-good' : 'service-caution'}">${escape(serviceReadinessLabel(service))}</span><small>${escape(service.connectivity)} · simulated</small><small>Last confirmed: ${service.confirmed ? `Oct 24, ${service.confirmed} (fixture)` : 'Never confirmed'}</small></div><div class="service-row-actions"><button type="button" data-readiness="${service.id}">Check readiness</button><span aria-hidden="true">${expandedService === service.id ? '▴' : '▾'}</span></div></div><section id="detail-${service.id}" class="inline-service-details" ${expandedService === service.id ? '' : 'hidden'} aria-label="${escape(service.name)} details">${expandedService === service.id ? serviceDetails(service) : ''}</section></li>`).join('');
}

function serviceDetails(service) {
  const content = {
    Status: `<p class="services-callout">${escape(serviceReadinessLabel(service))}</p><dl><dt>Connectivity</dt><dd>${escape(service.connectivity)} (simulated)</dd><dt>Last confirmed</dt><dd>${service.confirmed ? `Oct 24, ${service.confirmed} (fixture)` : 'Unknown'}</dd><dt>Computer</dt><dd>${escape(service.computer)}</dd></dl>`,
    Dependencies: `<p>${escape(service.dependencies)}</p><p>Services start independently of the GUI. Use the deployment owner's startup instructions; no universal startup order or OS process launch is supplied here.</p>`,
    History: `<ol><li>${service.confirmed ? `Fictional status report · Oct 24, ${service.confirmed}` : 'No confirmed status report'}</li><li>${escape(service.connectivity)} transport example; no inferred lifecycle replay, cleanup or recovery.</li></ol>`,
  };
  const obligations = model.obligations.filter(item => item.service === service.name);
  return `<div class="services-detail-tabs" role="group" aria-label="Service detail views">${Object.keys(content).map(name => `<button type="button" data-detail="${name}" aria-pressed="${model.detail === name}">${name}</button>`).join('')}</div><div class="services-detail-content">${content[model.detail]}</div>${obligations.length ? `<h4>Represented obligations / blockers</h4><ul>${obligations.map(item=>`<li>${escape(item.description)} — ${escape(item.outcome)}</li>`).join('')}</ul>` : ''}${service.readiness === 'Unhealthy' ? `<p>${escape(service.information)}</p>` : ''}${model.administrator ? `<div class="service-specific-administration"><h4>Selected-service administration</h4><button type="button" data-stop-service="${service.id}">Stop Service</button><button type="button" data-administrative="Supported recovery attempts">Recovery availability…</button><button type="button" data-administrative="Abandon outstanding obligations">Review obligations…</button></div>` : ''}`;
}

function notificationRows() {
  return notificationHistoryView(notificationHistory(), historyExpanded).map(item => `<article class="service-notification" data-history-id="${item.id}"><div><strong class="notification-severity">${escape(item.severity)}</strong> · ${escape(item.source)}<time datetime="${item.occurredAt}">${escape(item.displayTime)}</time><p>${escape(item.description)}</p></div><div class="notification-action"><span>${item.acknowledged ? 'Acknowledged · retained in history' : 'Unacknowledged'}</span>${item.acknowledged ? '' : `<button type="button" data-service-ack="${item.id}">Acknowledge</button>`}</div></article>`).join('');
}

function administrativeOperations() {
  if (!model.administrator) return '';
  return `<section id="services-administration" class="services-card services-danger" aria-label="Administrative operations"><h3>Whole-framework shutdown</h3><button type="button" class="shutdown-framework-demo" data-shutdown-framework>Shutdown Framework</button><p>Whole-framework scope, distinct from Stop Service, Session Stop and Experiment Stop. Separate confirmation required. Browser-local demonstration only.</p></section>`;
}

function renderServices() {
  const unacknowledged = notificationHistory().filter(item => !item.acknowledged).length;
  panel.innerHTML = `<header class="services-header"><div><h2 id="heading-services">Services</h2><p>Framework status, notifications and administrative operations</p><small>Browser-local demonstration · fictional reports, no live services or commands</small></div><div class="services-refresh"><label>Auto refresh (s)<select id="services-refresh"><option value="0">Off</option>${[5,10,30,60].map(n=>`<option value="${n}" ${model.refreshSeconds === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label><button type="button" data-refresh-services>Refresh now</button></div><div class="services-mode" role="group" aria-label="Services mode"><span>Mode:</span><button type="button" data-mode="experimenter" aria-pressed="${!model.administrator}">Experimenter</button><button type="button" data-mode="administrator" aria-pressed="${model.administrator}">Administrator</button></div></header>
    <p class="services-feedback" role="status">${escape(message || (model.lastPreviewRefresh ? `Preview refreshed locally at ${model.lastPreviewRefresh}; fixture confirmations are unchanged.` : 'Automatic refresh repaints fictional information only; it does not confirm availability.'))}</p>
    <section class="services-card"><h3>Configured services (${model.services.length})</h3><ul class="services-list" aria-label="Configured services">${serviceRows()}</ul></section>
    <section class="services-card services-warning-card"><h3>Warnings and errors <small>${unacknowledged} unacknowledged</small></h3><p class="services-muted">Latest three entries by default. Acknowledgment is not resolution or deletion.</p><div id="services-history" class="services-history" role="region" aria-label="Warning and error history" tabindex="0">${notificationRows()}</div>${notificationHistory().length > 3 ? `<button type="button" data-toggle-history aria-controls="services-history" aria-expanded="${historyExpanded}">${historyExpanded ? 'Show less' : 'Show more'}</button>` : ''}</section>${administrativeOperations()}`;
}

function scheduleServicesRefresh() {
  clearInterval(refreshTimer);
  if (model.refreshSeconds) refreshTimer = setInterval(() => {
    if (panel.hidden || danger.open || administrativePreview.open) return;
    // Avoid replacing focused controls during keyboard interaction.
    if (panel.contains(document.activeElement)) return;
    refreshServicesPreview(model, new Date().toLocaleTimeString()); renderServices();
  }, model.refreshSeconds * 1000);
}

function renderShutdownPreview() {
  const attempt = shutdownAttempt;
  administrativePreview.innerHTML = `<h2 id="admin-preview-title">${attempt.scope === 'framework' ? 'Framework shutdown' : 'Stop Service'} — local simulation</h2><p>${attempt.phase === 'pending' ? 'Orderly-stop progress: awaiting simulated reports.' : 'Fictional reports only — not live closeout confirmations.'}</p><ul>${attempt.participants.map(row=>`<li><strong>${escape(row.name)} · ${escape(row.computer)}</strong>${row.orderlyReport ? `<p>Retained orderly report: ${escape(row.orderlyReport.outcome)} — ${escape(row.orderlyReport.note)}</p>` : ''}<p>${escape(row.outcome)} — ${escape(row.note)}</p>${row.outcome === 'blocked' ? `<button type="button" data-kill-service="${row.id}">Kill Service… (preview)</button>` : ''}</li>`).join('')}</ul><p>No real report is changed. Unknown outcomes do not authorize Kill. Acknowledgment never proves retirement, cleanup or preservation. Earlier fixture outcomes are retained; no whole-framework completion is claimed.</p><div class="catalog-dialog__actions"><button type="button" data-admin-close>${attempt.phase === 'pending' ? 'Cancel' : 'Cancel / Close'}</button>${attempt.phase === 'pending' ? '<button type="button" data-finish-shutdown>Show simulated stop reports</button>' : ''}</div>`;
  administrativePreview.querySelector('[data-admin-close]').focus();
}

function openShutdownConfirmation(serviceId) {
  administrativePreview.dataset.stopService = serviceId || '';
  const targets = serviceId ? model.services.filter(s=>s.id === serviceId) : model.services;
  administrativePreview.innerHTML = `<h2 id="admin-preview-title">Confirm ${serviceId ? 'Stop Service' : 'Shutdown Framework'} preview</h2><p>${serviceId ? 'Only the selected service is targeted. Other service reports stay unchanged.' : 'Controller-coordinated whole-framework scope. This fixture is not an implementation of dependency ordering or real surveys.'}</p><ul>${targets.map(s=>`<li>${escape(s.name)} · ${escape(s.computer)}</li>`).join('')}</ul><p>Separate operation authorization and service-owned safety/preservation checks remain necessary. This starts a browser-local progress example only; no command will be sent.</p><div class="catalog-dialog__actions"><button type="button" data-admin-close>Cancel</button><button type="button" data-confirm-shutdown>Start orderly-stop simulation</button></div>`;
  administrativePreview.showModal();
}

function selectService(id) {
  model.selectedId = id;
  expandedService = expandedService === id ? null : id;
  renderServices();
  panel.querySelector(`[data-expand-service="${id}"]`).focus({preventScroll:true});
}
panel.addEventListener('keydown', event => {
  const row = event.target.closest('[data-expand-service]');
  if (event.target === row && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectService(row.dataset.expandService); }
});

panel.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (button?.hasAttribute('data-toggle-history')) {
    historyExpanded = !historyExpanded; renderServices();
    panel.querySelector('[data-toggle-history]').focus({preventScroll:true}); return;
  }
  const row = event.target.closest('[data-expand-service]');
  if (!button && row) { selectService(row.dataset.expandService); return; }
  if (!button) return;
  if (button.dataset.mode === 'administrator' && !model.administrator) { danger.showModal(); return; }
  if (button.dataset.mode === 'experimenter') setServicesAdministrator(model, false);
  if (button.dataset.detail) model.detail = button.dataset.detail;
  if (button.hasAttribute('data-refresh-services')) { message = ''; refreshServicesPreview(model, new Date().toLocaleTimeString()); }
  if (button.dataset.readiness) message = `Readiness preview requested for ${model.services.find(s=>s.id===button.dataset.readiness).name}. No authoritative check was performed; last-confirmed reports are unchanged.`;
  if (button.dataset.serviceAck) {
    acknowledgeNotification(button.dataset.serviceAck);
    panel.querySelector('.services-history').focus({preventScroll:true}); return;
  }
  if (model.administrator && (button.dataset.stopService || button.hasAttribute('data-shutdown-framework'))) { openShutdownConfirmation(button.dataset.stopService); return; }
  if (button.dataset.administrative && model.administrator) {
    const action = button.dataset.administrative;
    const service = model.services.find(s=>s.id===model.selectedId);
    const scope = `${service.name} on ${service.computer}`;
    const obligations = model.obligations.filter(item=>item.service===service.name);
    const explanation = {
      'Supported recovery attempts': 'No supported recovery procedure or current prerequisites are established for this selected-service fixture. Recovery execution is unavailable; no repair or safe-reuse outcome will be invented.',
      'Abandon outstanding obligations': 'Abandonment is an explicit administrative choice, not recovery, cleanup, safe reuse or deletion. No obligation can be discharged in this disconnected demo.',
    }[action];
    administrativePreview.innerHTML = `<h2 id="admin-preview-title">${escape(action)} — preview only</h2><p><strong>Scope:</strong> ${escape(scope)}</p><p>${escape(explanation)}</p>${action === 'Abandon outstanding obligations' ? `<ul>${obligations.map(item=>`<li>${escape(item.type)}: ${escape(item.description)} — ${escape(item.outcome)}</li>`).join('') || '<li>No obligations are represented for this service; absence of fixtures does not prove safe closeout.</li>'}</ul>` : ''}<p>No live command or execution authorization is available. Reviewing a warning cannot satisfy service-owned prerequisites.</p>${action === 'Supported recovery attempts' ? '' : '<label><input type="checkbox" name="confirm-scope"> I have reviewed this specific scope and its risks (local preview only).</label>'}<p data-admin-outcome role="status"></p><div class="catalog-dialog__actions"><button type="button" data-admin-close>Cancel / Close preview</button>${action === 'Supported recovery attempts' ? '' : '<button type="button" data-admin-review disabled>Record local scope review</button>'}</div>`;
    administrativePreview.showModal(); return;
  }
  renderServices();
  if (button.dataset.detail) panel.querySelector(`[data-detail="${button.dataset.detail}"]`)?.focus({preventScroll:true});
  if (button.dataset.mode) panel.querySelector(`[data-mode="${button.dataset.mode}"]`)?.focus({preventScroll:true});
});
panel.addEventListener('change', event => {
  if (event.target.id !== 'services-refresh') return;
  model.refreshSeconds = Number(event.target.value); scheduleServicesRefresh();
});
document.addEventListener('gui-notifications-changed', () => renderServices());
renderServices(); scheduleServicesRefresh();
