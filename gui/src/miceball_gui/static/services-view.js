import { createServicesDemo, setServicesAdministrator, refreshServicesPreview, serviceReadinessLabel, beginShutdownPreview, finishShutdownPreview, authorizeKillPreview, notificationHistoryView } from './services-demo.mjs';
import { notificationHistory, acknowledgeNotification } from './app.js';
import { escapeText as escape } from './gui-presentation.js';

const panel = document.querySelector('#panel-services');
const connected = document.documentElement?.dataset?.runtime === 'connected';
const model = createServicesDemo(connected);
export const servicesAdministrator = () => model.administrator;
export const serviceActions = {};
export function showBlockedServiceStop(service) {
  if (administrativePreview.open) return;
  authorizeMaintenance('blocked_stop', service);
}

function authorizeMaintenance(operation, service) {
  if (!connected || !model.administrator || !serviceActions.canControl?.()) return;
  const continuation = ['blocked_stop', 'kill_service', 'cancel_service'].includes(operation);
  const attemptId = continuation ? service?.attempt?.stop_attempt_id : null;
  const instanceId = service?.details?.operational_instance_id;
  if (continuation && (service?.attempt?.outcome !== 'blocked' || !attemptId)) return;
  administrativePreview.innerHTML = `<h2 id="admin-preview-title">${operation === 'blocked_stop' ? 'Stop blocked — explicit choice required' : `Authorize ${escape(operation)}`}</h2><p>${escape(service ? `${service.name} / ${service.computer}` : 'Whole configured framework')}</p>${continuation ? `<p>Stop attempt: ${escape(attemptId)}</p><pre>${escape(JSON.stringify(service.attempt, null, 2))}</pre>` : ''}${operation === 'blocked_stop' ? '<label>Continuation<select data-live-choice><option value="cancel_service">Cancel this Stop attempt</option><option value="kill_service">Explicitly authorize maintenance Kill</option></select></label>' : ''}<p>This does not authorize other targets. Force may lose unpreserved evidence and leave cleanup obligations. Timeout is not completion or permission to Kill. Closing this dialog sends no command.</p><label>Administrator name<input data-live-administrator></label><label><input type="checkbox" data-live-authorized> I explicitly authorize this exact operation and target.</label><div class="catalog-dialog__actions"><button type="button" data-admin-close>Close without action</button><button type="button" data-live-confirm disabled>Confirm operation</button></div>`;
  const name = administrativePreview.querySelector('[data-live-administrator]'), check = administrativePreview.querySelector('[data-live-authorized]'), submit = administrativePreview.querySelector('[data-live-confirm]');
  administrativePreview.oninput = () => { submit.disabled = !name.value.trim() || !check.checked; };
  const choice = administrativePreview.querySelector('[data-live-choice]');
  if (choice) choice.onchange = () => { check.checked = false; submit.disabled = true; };
  submit.onclick = () => {
    if (!check.checked || !name.value.trim() || !model.administrator || !serviceActions.canControl?.()) return;
    const current = service && model.services.find(item => item.id === service.id);
    if (continuation && (current?.attempt?.outcome !== 'blocked' || current.attempt.stop_attempt_id !== attemptId
        || current.details?.operational_instance_id !== instanceId)) {
      administrativePreview.close();
      message = 'Stop attempt changed; no continuation sent. Refresh the owner report.';
      renderServices(); return;
    }
    const selected = choice ? choice.value : operation;
    administrativePreview.close();
    serviceActions.maintain(selected, current || service, name.value);
  };
  administrativePreview.showModal();
}
export function updateServices(services, notice = '') {
  model.services = services;
  refreshNotice = notice;
  for (const service of services) {
    service.connectivity = service.current ? 'Confirmed communication' : 'Unknown';
    service.dependencies = service.details ? JSON.stringify({
      readiness_error: service.details.readiness_error,
      dependency_readiness: service.details.dependency_readiness,
      service_diagnostics: service.details.service_diagnostics,
    }, null, 2) : 'No current dependency confirmation';
  }
  renderServices();
}
let refreshTimer;
let message = '';
let refreshNotice = '';
let expandedService = null, shutdownAttempt = null, killTarget = null;
let historyExpanded = false;
const danger = document.createElement('dialog');
danger.className = 'catalog-dialog services-danger';
danger.setAttribute('aria-labelledby', 'services-danger-title');
danger.innerHTML = `<h2 id="services-danger-title">Danger Zone — Administrator Mode</h2><p>Administrator mode exposes advanced operations that can stop framework services, force termination, or affect unresolved recovery and data-preservation obligations.</p><p>These actions may interrupt ongoing experiments or risk loss of scientific data or operational evidence. Only enter if you understand the consequences and intend to perform administrative work.</p><p>This is a trust-based presentation safeguard, not authentication or operation authorization. ${connected ? 'Service administration is unavailable in this connected unit. No command will be sent.' : 'This demo sends no commands.'}</p><div class="catalog-dialog__actions"><button type="button" data-danger-cancel>Cancel</button><button type="button" data-danger-enter>Enter Administrator Mode</button></div>`;
document.body.append(danger);
danger.querySelector('[data-danger-cancel]').addEventListener('click', () => danger.close());
danger.querySelector('[data-danger-enter]').addEventListener('click', () => {
  setServicesAdministrator(model, true, true); danger.close(); renderServices();
  document.dispatchEvent(new CustomEvent('gui-administrator-changed'));
  panel.querySelector('[data-mode="administrator"]').focus({ preventScroll: true });
});
const administrativePreview = document.createElement('dialog');
administrativePreview.className = 'catalog-dialog services-danger';
administrativePreview.setAttribute('aria-labelledby', 'admin-preview-title');
document.body.append(administrativePreview);
administrativePreview.addEventListener('click', event => {
  if (connected && !event.target.closest('[data-admin-close]')) return;
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
  return model.services.map(service => `<li><div class="service-row ${expandedService === service.id ? 'is-selected' : ''}" data-expand-service="${escape(service.id)}" role="button" tabindex="0" aria-expanded="${expandedService === service.id}" aria-controls="detail-${escape(service.id)}" aria-label="${escape(service.name)} · ${escape(service.computer)}"><div class="service-identity"><strong>${escape(service.name)}</strong><small>${escape(service.computer)}</small></div><div class="service-report"><span class="service-status ${service.current && service.readiness === 'Ready' ? 'service-good' : 'service-caution'}">${escape(serviceReadinessLabel(service))}</span><small>${escape(service.connectivity)}${connected ? '' : ' · simulated'}</small><small>Last confirmed: ${service.confirmed ? (connected ? escape(service.confirmed) : `Oct 24, ${service.confirmed} (fixture)`) : 'Never confirmed'}</small></div><div class="service-row-actions"><button type="button" data-readiness="${escape(service.id)}" ${service.pending ? 'disabled' : ''}>${service.pending ? 'Checking…' : 'Check readiness'}</button><span aria-hidden="true">${expandedService === service.id ? '▴' : '▾'}</span></div></div><section id="detail-${escape(service.id)}" class="inline-service-details" ${expandedService === service.id ? '' : 'hidden'} aria-label="${escape(service.name)} details">${expandedService === service.id ? serviceDetails(service) : ''}</section></li>`).join('');
}

function serviceDetails(service) {
  const content = {
    Status: `<p class="services-callout">${escape(serviceReadinessLabel(service))}</p><dl><dt>Connectivity</dt><dd>${escape(service.connectivity)} ${connected ? '' : '(simulated)'}</dd><dt>Last confirmed</dt><dd>${service.confirmed ? (connected ? escape(service.confirmed) : `Oct 24, ${service.confirmed} (fixture)`) : 'Unknown'}</dd><dt>Computer</dt><dd>${escape(service.computer)}</dd></dl>`,
    Dependencies: `<p>${escape(service.dependencies)}</p><p>Services start independently of the GUI. Use the deployment owner's startup instructions; no universal startup order or OS process launch is supplied here.</p>`,
    History: `<ol><li>${service.confirmed ? (connected ? `Last-known report: ${escape(service.confirmed)}` : `Fictional status report · Oct 24, ${service.confirmed}`) : 'No confirmed status report'}</li><li>${connected ? 'Last-known reports are historical, not current availability.' : `${escape(service.connectivity)} transport example; no inferred lifecycle replay, cleanup or recovery.`}</li></ol>`,
  };
  const obligations = model.obligations.filter(item => item.service === service.name);
  if (connected) {
    const retired = service.details?.operational_retirement_confirmed === true;
    const delivery = service.details?.retirement_delivery;
    content.Status += `<p>${service.diagnosticsCurrent ? 'Current owner diagnostics' : 'Last-known or unavailable owner diagnostics'}; last-confirmed readiness is shown separately.</p>`;
    if (retired) content.Status += service.diagnosticsCurrent
      ? `<p>Operational retirement confirmed. ${delivery?.required && !delivery.dependency_release_confirmed ? 'Dependency-release confirmation remains outstanding; the process must be retained.' : 'OS process exit is not established by this report.'} Kill is unavailable because there is no current blocked Stop attempt. This GUI cannot retry retained retirement delivery.</p>`
      : '<p>Last-known owner reported operational retirement. Current retirement, dependency confirmation and OS process exit are unconfirmed.</p>';
  }
  return `<div class="services-detail-tabs" role="group" aria-label="Service detail views">${Object.keys(content).map(name => `<button type="button" data-detail="${name}" aria-pressed="${model.detail === name}">${name}</button>`).join('')}</div><div class="services-detail-content">${content[model.detail]}</div>${obligations.length ? `<h4>Represented obligations / blockers</h4><ul>${obligations.map(item=>`<li>${escape(item.description)} — ${escape(item.outcome)}</li>`).join('')}</ul>` : ''}${connected ? `${service.lastOperation ? `<p class="services-callout">${escape(service.lastOperation.operation)} · ${escape(service.lastOperation.result?.outcome?.details?.outcome || service.lastOperation.status)} ${escape(service.lastOperation.result?.error || '')}</p>` : ''}<p>${escape(service.information || 'No confirmed report')}</p><details><summary>Owner report and remaining obligations</summary><pre>${escape(JSON.stringify({readiness: service.details || null, operation: service.lastOperation || null}, null, 2))}</pre></details>` : ''}${service.readiness === 'Unhealthy' ? `<p>${escape(service.information)}</p>` : ''}${model.administrator ? `<div class="service-specific-administration"><h4>Selected-service administration</h4><button type="button" data-stop-service="${escape(service.id)}">Stop Service</button>${connected && service.attempt?.outcome === 'blocked' ? `<button type="button" data-live-kill="${escape(service.id)}">Kill Service…</button><button type="button" data-live-cancel="${escape(service.id)}">Cancel Stop attempt</button>` : ''}<button type="button" data-administrative="Supported recovery attempts">Recovery availability…</button><button type="button" data-administrative="Abandon outstanding obligations">Review obligations…</button></div>` : ''}`;
}

function notificationRows() {
  return notificationHistoryView(notificationHistory(), historyExpanded).map(item => `<article class="service-notification" data-history-id="${item.id}"><div><strong class="notification-severity">${escape(item.severity)}</strong> · ${escape(item.source)}<time datetime="${item.occurredAt}">${escape(item.displayTime)}</time><p>${escape(item.description)}</p></div><div class="notification-action"><span>${item.acknowledged ? 'Acknowledged · retained in history' : 'Unacknowledged'}</span>${item.acknowledged ? '' : `<button type="button" data-service-ack="${item.id}">Acknowledge</button>`}</div></article>`).join('');
}

function administrativeOperations() {
  if (!model.administrator) return '';
  return `<section id="services-administration" class="services-card services-danger" aria-label="Administrative operations"><h3>Whole-framework shutdown</h3><button type="button" class="shutdown-framework-demo" data-shutdown-framework>Shutdown Framework</button><p>Whole-framework scope, distinct from Stop Service, Session Stop and Experiment Stop. ${connected ? 'Controller coordinates configured owners. No automatic Kill escalation.' : 'Separate confirmation required. Browser-local demonstration only.'}</p>${connected ? `<pre>${escape(JSON.stringify(serviceActions.frameworkOutcome?.() || 'No framework shutdown request recorded', null, 2))}</pre>` : ''}</section>`;
}

function renderServices() {
  const unacknowledged = notificationHistory().filter(item => !item.acknowledged).length;
  panel.innerHTML = `<header class="services-header"><div><h2 id="heading-services">Services</h2><p>Framework status, notifications and administrative operations</p><small>${connected ? 'Configured membership · service-owned readiness · Controller admission remains authoritative' : 'Browser-local demonstration · fictional reports, no live services or commands'}</small></div><div class="services-refresh"><label>Auto refresh (s)<select id="services-refresh"><option value="0">Off</option>${[5,10,30,60].map(n=>`<option value="${n}" ${model.refreshSeconds === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label><button type="button" data-refresh-services>Refresh now</button></div><div class="services-mode" role="group" aria-label="Services mode"><span>Mode:</span><button type="button" data-mode="experimenter" aria-pressed="${!model.administrator}">Experimenter</button><button type="button" data-mode="administrator" aria-pressed="${model.administrator}">Administrator</button></div></header>
    <p class="services-feedback" ${connected ? 'id="services-readiness-unavailable"' : ''} role="status">${escape(message || refreshNotice || (model.lastPreviewRefresh ? `Preview refreshed locally at ${model.lastPreviewRefresh}; fixture confirmations are unchanged.` : (connected ? 'Only valid current checks confirm availability; communication loss alone is not failure.' : 'Automatic refresh repaints fictional information only; it does not confirm availability.')))}</p>
    <section class="services-card"><h3>Configured services (${model.services.length})</h3><ul class="services-list" aria-label="Configured services">${serviceRows()}</ul></section>
    <section class="services-card services-warning-card"><h3>Warnings and errors <small>${connected ? 'Unavailable' : `${unacknowledged} unacknowledged`}</small></h3><p class="services-muted">${connected ? 'Authoritative warning and error history is unavailable.' : 'Latest three entries by default. Acknowledgment is not resolution or deletion.'}</p><div id="services-history" class="services-history" role="region" aria-label="Warning and error history" tabindex="0">${notificationRows()}</div>${notificationHistory().length > 3 ? `<button type="button" data-toggle-history aria-controls="services-history" aria-expanded="${historyExpanded}">${historyExpanded ? 'Show less' : 'Show more'}</button>` : ''}</section>${administrativeOperations()}`;
  if (connected && !serviceActions.refresh) {
    panel.querySelector('#services-refresh').disabled = true;
    panel.querySelector('#services-refresh').setAttribute('aria-describedby', 'services-readiness-unavailable');
    for (const button of panel.querySelectorAll('[data-readiness]')) button.setAttribute('aria-describedby', 'services-readiness-unavailable');
  }
  if (connected && serviceActions.refresh) for (const button of panel.querySelectorAll('[data-stop-service], [data-shutdown-framework]')) button.disabled = !serviceActions.canControl?.();
  if (connected && !serviceActions.refresh) for (const button of panel.querySelectorAll('[data-readiness], [data-stop-service], [data-shutdown-framework], [data-administrative]')) { button.disabled = true; button.title = 'Operational integration unavailable'; }
}

function scheduleServicesRefresh() {
  clearInterval(refreshTimer);
  if (connected && serviceActions.refresh) {
    if (model.refreshSeconds) refreshTimer = setInterval(() => serviceActions.refresh(), model.refreshSeconds * 1000);
    return;
  }
  if (!connected && model.refreshSeconds) refreshTimer = setInterval(() => {
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
  [...panel.querySelectorAll('[data-expand-service]')].find(row => row.dataset.expandService === id)?.focus({preventScroll:true});
}
panel.addEventListener('keydown', event => {
  const row = event.target.closest('[data-expand-service]');
  if (event.target === row && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectService(row.dataset.expandService); }
});

panel.addEventListener('click', event => {
  if (connected && serviceActions.refresh) {
    const button = event.target.closest('button'), row = event.target.closest('[data-expand-service]');
    if (!button && row) { selectService(row.dataset.expandService); return; }
    if (!button || button.disabled) return;
    if (button.dataset.mode === 'administrator' && !model.administrator) { danger.showModal(); return; }
    if (button.dataset.mode === 'experimenter') { setServicesAdministrator(model, false); renderServices(); return; }
    if (button.hasAttribute('data-refresh-services')) { serviceActions.refresh(); return; }
    if (button.dataset.readiness) { serviceActions.refresh(button.dataset.readiness); return; }
    if (button.dataset.detail) { model.detail = button.dataset.detail; renderServices(); return; }
    if (button.dataset.administrative) {
      const service = model.services.find(s => s.id === model.selectedId);
      if (button.dataset.administrative === 'Abandon outstanding obligations') {
        administrativePreview.innerHTML = `<h2 id="admin-preview-title">Owner obligations and retirement</h2><p>${escape(service?.name || 'Selected service')} / ${escape(service?.computer || '')}</p><p>${service?.diagnosticsCurrent ? 'Current owner diagnostics' : 'Last-known or unavailable owner diagnostics; not current confirmation'}. Operational retirement, dependency-release confirmation and OS process exit are distinct. This view does not execute recovery or abandon obligations.</p><pre>${escape(JSON.stringify(service?.details || null, null, 2))}</pre><p>An operationally retired service is not a blocked Stop attempt and is not eligible for another Kill. Retained retirement-delivery completion is not exposed by this external interface.</p><div class="catalog-dialog__actions"><button type="button" data-admin-close>Close</button></div>`;
        administrativePreview.showModal(); return;
      }
      const operations = ['recover_archive_write', 'recover_session_record_write', 'recover_artifact_transfer', 'preserve_scientific_artifact', 'cleanup_device_resources', 'dispose_temporary_evidence'];
      const authorizations = service?.current ? (service.details?.recovery_authorizations || []).filter(record =>
        operations.includes(record.payload?.details?.operation)
        && record.payload?.target?.component_id === service.participant.component_id
        && record.payload?.target?.component_type === service.participant.component_type) : [];
      if (button.dataset.administrative !== 'Supported recovery attempts' || !authorizations.length) {
        message = 'No supported exact-target recovery with existing durable administrator authorization is currently reported. Obligation abandonment is unavailable through this interface. No command sent.';
        renderServices(); return;
      }
      if (!model.administrator || !serviceActions.canControl?.()) {
        message = 'Recovery execution requires current Controller control and a confirmed operation context. No command sent.';
        renderServices(); return;
      }
      administrativePreview.innerHTML = `<h2 id="admin-preview-title">Explicit authorized recovery</h2><p>${escape(service.name)} / ${escape(service.computer)}</p><label>Existing owner authorization<select data-recovery-choice>${authorizations.map((record, index) => `<option value="${index}">${escape(record.payload.details.operation)} · ${escape(record.payload.administrator_id)}</option>`).join('')}</select></label><pre data-recovery-scope></pre><p data-recovery-warning></p><label><input type="checkbox" data-recovery-authorized> I explicitly authorize this exact operation and scope, including the stated consequences.</label><div class="catalog-dialog__actions"><button type="button" data-admin-close>Cancel</button><button type="button" data-recovery-confirm disabled>Execute authorized recovery</button></div>`;
      const choice = administrativePreview.querySelector('[data-recovery-choice]'), check = administrativePreview.querySelector('[data-recovery-authorized]'), submit = administrativePreview.querySelector('[data-recovery-confirm]');
      const selection = () => authorizations[Number(choice.value)];
      const showScope = () => {
        check.checked = false; submit.disabled = true;
        administrativePreview.querySelector('[data-recovery-scope]').textContent = JSON.stringify(selection(), null, 2);
        administrativePreview.querySelector('[data-recovery-warning]').textContent = selection().payload.details.operation === 'dispose_temporary_evidence'
          ? 'Permanent-loss acknowledgment: proven-corrupt temporary evidence in this exact scope will be permanently discarded. This is not scientific-original deletion.'
          : 'Owner safety, durable authorization and current recovery prerequisites are rechecked. This does not confirm preservation, safe reuse or service retirement.';
      };
      choice.onchange = showScope;
      check.onchange = () => { submit.disabled = !check.checked; };
      submit.onclick = () => {
        if (!check.checked || !model.administrator || !serviceActions.canControl?.()) return;
        const authorization = selection(), details = authorization.payload.details;
        administrativePreview.close();
        serviceActions.maintain(details.operation, service, authorization.payload.administrator_id,
          {authorization_evidence_id: authorization.evidence_id, recovery_command_id: details.command_id, obligation: details.obligation});
      };
      showScope(); administrativePreview.showModal(); return;
    }
    const operation = button.hasAttribute('data-stop-service') ? 'stop_service' : button.hasAttribute('data-live-kill') ? 'kill_service' : button.hasAttribute('data-live-cancel') ? 'cancel_service' : button.hasAttribute('data-shutdown-framework') ? 'shutdown_framework' : null;
    if (operation && model.administrator && serviceActions.canControl?.()) {
      const id = button.dataset.stopService || button.dataset.liveKill || button.dataset.liveCancel;
      const service = model.services.find(s => s.id === id);
      authorizeMaintenance(operation, service);
    }
    return;
  }
  if (connected && event.target.closest('[data-readiness], [data-stop-service], [data-shutdown-framework], [data-administrative]')) { message = 'Operational integration unavailable. No command was sent.'; renderServices(); return; }
  const button = event.target.closest('button');
  if (button?.hasAttribute('data-toggle-history')) {
    historyExpanded = !historyExpanded; renderServices();
    panel.querySelector('[data-toggle-history]').focus({preventScroll:true}); return;
  }
  const row = event.target.closest('[data-expand-service]');
  if (!button && row) { selectService(row.dataset.expandService); return; }
  if (!button) return;
  if (button.dataset.mode === 'administrator' && !model.administrator) { danger.showModal(); return; }
  if (button.dataset.mode === 'experimenter') {
    setServicesAdministrator(model, false);
    document.dispatchEvent(new CustomEvent('gui-administrator-changed'));
  }
  if (button.dataset.detail) model.detail = button.dataset.detail;
  if (button.hasAttribute('data-refresh-services')) {
    if (connected) message = 'Live service status refresh unavailable. No readiness check was sent; availability remains unknown.';
    else { message = ''; refreshServicesPreview(model, new Date().toLocaleTimeString()); }
  }
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
export function startServicesRefresh() {
  danger.querySelector('p:last-of-type').textContent = 'This is a cooperative presentation safeguard, not authentication. Each operation requires separate exact-target authorization and service-owned admission.';
  model.refreshSeconds = 10;
  scheduleServicesRefresh();
  renderServices();
}
document.addEventListener('gui-notifications-changed', () => renderServices());
renderServices(); scheduleServicesRefresh();
