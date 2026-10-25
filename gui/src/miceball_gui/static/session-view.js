import { state } from './protocol-setup.js';
import { sessionProgress, sessionStepView, actOnSessionStep } from './session-demo.mjs';

const panel = document.querySelector('#panel-session');
const escape = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const statusLabels = {
  completed: ['✓', 'Completed'], ready: ['▶', 'Ready'], running: ['▶', 'Running'],
  'needs-review': ['!', 'Needs review'], 'not-started': ['○', 'Not started'],
  unavailable: ['○', 'Unavailable'], error: ['!', 'Error'], skipped: ['↷', 'Skipped'],
};
const actionLabels = {
  repeat: 'Repeat step', load: 'Load previous result', validate: 'Validate existing result',
  skip: 'Skip optional step', complete: 'Complete simulation', error: 'Simulate error',
};
let feedback = '';

function statusBadge(status) {
  const [icon, label] = statusLabels[status];
  return `<span class="session-status status-${status}"><span aria-hidden="true">${icon}</span>${label}</span>`;
}

function readinessRows(rows) {
  return rows.map(row => `<li><span class="readiness-mark ${row.providers.some(device => device.available) ? 'status-completed' : 'status-unavailable'}" aria-hidden="true">${row.providers.some(device => device.available) ? '✓' : '○'}</span><div><strong>${escape(row.capability)}</strong><small>${row.providers.length ? row.providers.map(device => `${escape(device.name)}${device.available ? '' : ' · unavailable (demo)'}`).join(', ') : 'No selected provider'}</small></div></li>`).join('');
}

function renderSession() {
  const protocol = state.protocols.find(item => item.id === state.protocolId);
  const progress = sessionProgress(state);
  const step = protocol.steps.find(item => item.id === progress.selectedId);
  const identityFields = [...document.querySelectorAll('.session-identity-grid input')];
  const selectedText = id => document.querySelector(`#${id}`).selectedOptions[0]?.textContent || 'Not selected';
  const header = [
    ['Session', identityFields[0].value || 'Unnamed Session'], ['Date', identityFields[1].value || 'Not set'],
    ['Experimenter', selectedText('experimenter-select')], ['Project', selectedText('project-select')],
    ['Animal', selectedText('animal-select')], ['Protocol', protocol.name], ['Session status', 'Preview · not launched'],
  ];
  panel.innerHTML = `<h2 id="heading-session" class="visually-hidden">Session</h2>
    <dl class="session-information">${header.map(([label, value]) => `<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
    <p class="session-demo-notice">Browser-local demonstration · initial completed results are illustrative. No Session is launched, no data are acquired, and no framework readiness is checked.</p>
    <div class="session-columns">
      <section class="session-card session-protocol-card" aria-labelledby="session-protocol-title">
        <h3 id="session-protocol-title"><span aria-hidden="true">▤</span> Protocol steps (${protocol.steps.length})</h3>
        <ol class="session-protocol-list">${protocol.steps.map((item, index) => {
          const view = sessionStepView(state, item);
          return `<li><button type="button" data-session-step="${escape(item.id)}" aria-pressed="${item.id === progress.selectedId}" class="${item.id === progress.selectedId ? 'is-selected' : ''}"><span class="session-step-number">${index + 1}.</span><span class="session-step-copy"><strong>${escape(item.name)}</strong><small>${escape(item.description || 'No description supplied.')}</small></span><span class="session-step-state">${statusBadge(view.status)}${view.status === 'needs-review' ? '<small>Earlier step updated (demo)</small>' : view.status === 'skipped' ? '<small>Optional step</small>' : ''}</span></button></li>`;
        }).join('')}</ol>
      </section>
      <section class="session-card session-selected-card" aria-label="Selected step">
        ${step ? selectedStepMarkup(state, protocol, step) : '<h3>No protocol steps</h3><p>Add steps using the Protocol Editor in Setup.</p>'}
      </section>
    </div>`;
}

function selectedStepMarkup(state, protocol, step) {
  const view = sessionStepView(state, step);
  const { record, operation } = view;
  const operationType = operation?.type || 'Unsupported operation';
  const capabilities = values => values.length ? values.map(escape).join(', ') : 'None';
  const actions = view.actions.map(action => {
    const label = action === 'run' ? operationType === 'Experiment' ? 'Start Experiment' : 'Run step' : actionLabels[action];
    return `<button type="button" data-session-action="${action}" class="${['run', 'repeat', 'complete', 'validate'].includes(action) ? 'session-primary' : ''}">${label} <small>(demo)</small></button>`;
  }).join('');
  return `<div class="session-selected-heading"><div><p>Step ${protocol.steps.indexOf(step) + 1} of ${protocol.steps.length}</p><h3>${escape(step.name)}</h3></div>${statusBadge(view.status)}</div>
    <p class="session-step-description">${escape(step.description || 'No description supplied.')}</p>
    <div class="session-detail-grid">
      <section class="session-detail-box"><h4>Step information</h4><dl class="session-step-information">
        <dt>Scientific operation</dt><dd>${escape(operation?.name || step.operation)} · ${escape(operationType)}</dd>
        <dt>Step status</dt><dd>${step.mandatory ? 'Required' : 'Optional'}</dd>
        <dt>Required capabilities</dt><dd>${capabilities(step.required)}</dd>
        <dt>Optional capabilities</dt><dd>${capabilities(step.optional)}</dd>
        <dt>Run support</dt><dd>${view.supports.run ? 'Supported (demo)' : 'Operation unavailable'}</dd>
        <dt>Previous-result example</dt><dd>${view.supports.load ? 'Supported (demo)' : 'Not offered'}</dd>
        <dt>Skip support</dt><dd>${step.mandatory ? 'No — required step' : 'Optional steps only (demo)'}</dd>
      </dl></section>
      <section class="session-detail-box session-readiness"><h4>Step readiness <small>Simulated</small></h4><ul>${view.required.length ? readinessRows(view.required) : '<li><span aria-hidden="true">○</span><div>No required hardware capabilities declared.</div></li>'}</ul>
        <p>${view.ready ? 'Required declaration coverage is available in the demo.' : 'A required provider is unselected or unavailable in the demo.'}</p>
        <small>Not Controller readiness. Experiment participation, acquisition-device admission, capacity and runtime checks are not implemented here.</small>
      </section>
    </div>
    ${record.reviewReason ? `<div class="session-review-explanation"><strong>Design proposal · review requested</strong><p>${escape(record.reviewReason)}</p><p>Validate confirms only that this mock result is acceptable to the experimenter.</p></div>` : ''}
    <section class="session-action-section"><h4>Actions <small>Browser-local simulations</small></h4><div class="session-action-buttons">${actions || '<p>No execution action available for this state. Step information and history remain accessible.</p>'}</div>
      ${view.running && view.status !== 'running' ? '<p>Finish the current demonstration simulation before starting another.</p>' : ''}
      ${!view.included ? '<p>This optional step is excluded in Setup.</p>' : ''}
      <p class="session-feedback" id="session-feedback" role="status">${escape(feedback)}</p>
    </section>
    ${view.status === 'running' ? '<section class="session-progress"><h4>Progress <small>Simulation only</small></h4><progress aria-label="Simulated step progress"></progress><p>Illustrative running state — no measured percentage or time estimate. Use Complete simulation or Simulate error to inspect the next state.</p></section>' : ''}
    <section class="session-output"><h4>Step output</h4>${record.results.length ? `<p>${record.results.length} retained mock result${record.results.length === 1 ? '' : 's'} · no scientific files</p><ol>${record.results.map(result => `<li><strong>${escape(result.name)}</strong><span>${escape(result.origin)} · ${escape(result.summary)}</span></li>`).join('')}</ol>` : '<div class="session-empty-output"><span aria-hidden="true">▱</span><p><strong>No output yet</strong><span>Demonstration output summaries will appear here when a simulation completes.</span></p></div>'}</section>
    <div class="session-detail-footer"><details class="session-history"><summary>↶ Step history (${record.history.length})</summary><ol>${record.history.map(entry => `<li>${escape(entry)}</li>`).join('')}</ol></details><div class="session-context-links">
      <button type="button" data-session-navigate="parameters">View parameters ↗</button>
      ${operation ? `<button type="button" data-session-navigate="${operationType === 'Analysis' ? 'analysis' : 'experiment'}">Open ${operationType} workspace ↗</button>` : ''}
    </div></div>`;
}

panel.addEventListener('click', event => {
  const select = event.target.closest('[data-session-step]');
  const action = event.target.closest('[data-session-action]');
  const navigate = event.target.closest('[data-session-navigate]');
  if (navigate) {
    document.dispatchEvent(new CustomEvent('gui-section', { detail: navigate.dataset.sessionNavigate }));
    return;
  }
  if (select) {
    sessionProgress(state).selectedId = select.dataset.sessionStep;
    feedback = '';
    const scroll = panel.querySelector('.session-protocol-list').scrollTop;
    renderSession();
    panel.querySelector('.session-protocol-list').scrollTop = scroll;
    panel.querySelector(`[data-session-step="${CSS.escape(select.dataset.sessionStep)}"]`).focus({ preventScroll: true });
  }
  if (action) {
    const selectedId = sessionProgress(state).selectedId;
    const scroll = panel.scrollTop;
    const listScroll = panel.querySelector('.session-protocol-list').scrollTop;
    actOnSessionStep(state, selectedId, action.dataset.sessionAction);
    feedback = 'Demonstration updated locally. No framework command, scientific processing or persistent result.';
    renderSession();
    panel.scrollTop = scroll;
    panel.querySelector('.session-protocol-list').scrollTop = listScroll;
    const next = panel.querySelector('[data-session-action]');
    next?.focus({ preventScroll: true });
  }
});
document.addEventListener('gui-section-changed', event => {
  if (event.detail === 'session') { feedback = ''; renderSession(); }
});
renderSession();
