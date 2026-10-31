import { formatCalendarDate } from './calendar-date.mjs';
import { state } from './protocol-setup.js';
import { sessionProgress, sessionStepView, actOnSessionStep } from './session-demo.mjs';
import { experimentTemplates, loadExperimentTemplate, prepareExperimentRepeat, updateExperiment, experimentDeviceGroups, deviceExamples } from './experiment-demo.mjs';
import { devices, operationCategoryAvailability } from './protocol-demo.mjs';
import { sessionStopPreview } from './services-demo.mjs';
import { escapeText as escape, executionIdentity, navigate } from './gui-presentation.js';
import { executionContext, executionProtocol, executionSteps } from './session-context.mjs';
import { selectedStepContext, freeOperationChoices, prepareFreeOperation, selectRecording, clearRecordingSelection } from './session-demo.mjs';
import { openRecordingPicker } from './recording-picker.js';
import { startDeviceValidation } from './device-validation-demo.mjs';
import { confirmStop } from './stop-confirmation.mjs';

const panel = document.querySelector('#panel-session');
const statusLabels = {
  completed: ['✓', 'Executed · demo'], satisfied: ['✓', 'Satisfied using previous recording · demo'], ready: ['▶', 'Ready'], running: ['▶', 'Running'],
  'needs-review': ['!', 'Needs review'], 'not-started': ['○', 'Not started'],
  unavailable: ['○', 'Unavailable'], error: ['!', 'Error'], skipped: ['↷', 'Skipped'],
  'stop-requested': ['○', 'Stop requested (demo)'],
};
const actionLabels = {
  repeat: 'Repeat step', load: 'Load previous recording', validate: 'Validate existing result',
  'accept-recording': 'Simulate scientific-application acceptance', 'reject-recording': 'Simulate scientific-application rejection',
  skip: 'Skip optional step', complete: 'Complete simulation', error: 'Simulate error',
};
let feedback = '';
let freeOperationChoice = '';
let pendingTemplateLoad = null;
// Fixed presentation example; alternate outcomes are exercised by model tests.
const stopScenario = 'blocked';
let stopEscalation = false;
const stopDialog = document.createElement('dialog');
stopDialog.className = 'catalog-dialog session-stop-preview';
stopDialog.setAttribute('aria-labelledby', 'session-stop-title');
document.body.append(stopDialog);
stopDialog.addEventListener('close', () => { stopEscalation = false; });
stopDialog.addEventListener('click', event => {
  if (event.target.closest('[data-stop-dismiss]')) stopDialog.close();
  if (event.target.closest('[data-session-kill]') && stopEscalation) {
    stopDialog.innerHTML = `<h2 id="session-stop-title">Kill Session — forced termination warning</h2><p>Session Kill is not service Kill or framework shutdown. It may stop active acquisition and leave only partial data preservation and unresolved cleanup. Authorization does not prove preservation or safe resource reuse.</p><p>This is a browser-local preview only. No lifecycle authorization or current prerequisites are connected.</p><div class="catalog-dialog__actions"><button type="button" data-stop-dismiss>Cancel</button><button type="button" data-kill-preview-confirm>Confirm fictional Kill preview</button></div>`;
    stopDialog.querySelector('[data-stop-dismiss]').focus();
  }
  if (event.target.closest('[data-kill-preview-confirm]') && stopEscalation) {
    stopDialog.innerHTML = '<h2 id="session-stop-title">Kill preview recorded locally</h2><p>No real Session was terminated. Cleanup, preservation and resource safety remain unconfirmed. Mock results and history have not been erased.</p><button type="button" data-stop-dismiss>Close</button>';
    stopDialog.querySelector('[data-stop-dismiss]').focus();
  }
});
const templateConfirmation = document.createElement('dialog');
templateConfirmation.className = 'catalog-dialog';
templateConfirmation.id = 'experiment-template-confirmation';
templateConfirmation.setAttribute('aria-labelledby', 'experiment-template-confirmation-title');
templateConfirmation.innerHTML = '<form method="dialog"><h2 id="experiment-template-confirmation-title">Replace modified working values?</h2><p>The selected template will replace your unsaved working configuration. Executed settings and previous results will not change.</p><div class="catalog-dialog__actions"><button type="button" class="dialog-button" data-cancel-template-load>Cancel</button><button type="button" class="dialog-button dialog-button--primary" data-confirm-template-load>Load template</button></div></form>';
document.body.append(templateConfirmation);
templateConfirmation.querySelector('[data-cancel-template-load]').addEventListener('click', () => templateConfirmation.close());
templateConfirmation.addEventListener('close', () => { pendingTemplateLoad = null; });
templateConfirmation.querySelector('[data-confirm-template-load]').addEventListener('click', () => {
  const pending = pendingTemplateLoad;
  if (!pending) return;
  try {
    loadExperimentTemplate(state, pending.step, pending.record, pending.id, pending.owner, true);
    feedback = 'Template loaded into working values only.';
  } catch (error) { feedback = error.message; }
  templateConfirmation.close();
  renderSession();
});

function statusBadge(status) {
  const [icon, label] = statusLabels[status];
  return `<span class="session-status status-${status}"><span aria-hidden="true">${icon}</span>${label}</span>`;
}

function readinessRows(rows) {
  return rows.map(row => `<li><span class="readiness-mark ${row.providers.some(device => device.available) ? 'status-completed' : 'status-unavailable'}" aria-hidden="true">${row.providers.some(device => device.available) ? '✓' : '○'}</span><div><strong>${escape(row.capability)}</strong><small>${row.providers.length ? row.providers.map(device => `${escape(device.name)}${device.available ? '' : ' · unavailable (demo)'}`).join(', ') : 'No selected provider'}</small></div></li>`).join('');
}

function renderSession() {
  const context = executionContext(state);
  const protocol = executionProtocol(state);
  const steps = executionSteps(state);
  const free = context.protocolId === null;
  const progress = sessionProgress(state);
  const step = steps.find(item => item.id === progress.selectedId);
  const identity = executionIdentity(state);
  const header = [
    ['Session', identity.name], ['Date', formatCalendarDate(identity.date)],
    ['Experimenter', identity.experimenter], ['Project', identity.project],
    ['Animal', identity.animal], ['Protocol', protocol?.name || 'None · Free Mode'], ['Session status', state.activeSession ? 'Active · browser simulation' : 'Preview · not launched'],
  ];
  panel.innerHTML = `<h2 id="heading-session" class="visually-hidden">Session</h2>
    <dl class="session-information">${header.map(([label, value]) => `<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
    <p class="session-demo-notice">Browser-local demonstration · all results are illustrative. No framework Session is launched, no data are acquired, and no framework readiness is checked.</p>
    <p class="session-demo-notice operation-category-availability">Application operation definitions: ${operationCategoryAvailability().map(({ category, count }) => `${escape(category)} — ${count ? `${count} available` : 'none supplied (deferred)'}`).join('; ')}. Device Validation is a separate device-function check, not a scientific Validation operation.</p>
    <div class="session-columns">
      <section class="session-card session-protocol-card" aria-labelledby="session-protocol-title">
        <h3 id="session-protocol-title"><span aria-hidden="true">▤</span> ${free ? 'Free Mode · operation history' : `Protocol steps (${steps.length})`}</h3>
        ${free ? `<p>Choose an application-supplied operation. There is no predefined checklist or required next step.</p><label>Scientific operation<select id="free-operation-choice">${freeOperationChoices(state).map(({operation, compatible, missing}) => `<option value="${escape(operation.id)}" ${compatible ? '' : 'disabled'}>${escape(operation.name)} · ${escape(operation.type)}${compatible ? ' · Capability-compatible' : ` · Missing ${escape(missing.join(', '))}`}</option>`).join('')}</select></label><p>Capability compatibility is not runtime readiness. The existing illustrative checks apply before execution.</p><button type="button" data-prepare-free-operation ${state.activeSession ? '' : 'disabled'}>Prepare operation</button>${state.activeSession ? '' : '<p>Launch the Free Mode Session from Setup first.</p>'}` : ''}
        <ol class="session-protocol-list">${steps.map((item, index) => {
          const view = sessionStepView(state, item);
          return `<li><button type="button" data-session-step="${escape(item.id)}" aria-pressed="${item.id === progress.selectedId}" class="${item.id === progress.selectedId ? 'is-selected' : ''}"><span class="session-step-number">${free ? '·' : `${index + 1}.`}</span><span class="session-step-copy"><strong>${escape(item.name)}</strong><small>${free ? `${escape(view.operation?.type || 'Operation')} · ${view.record.attempts?.length || 0} attempts · ${view.record.results.length} results` : escape(item.description || 'No description supplied.')}</small></span><span class="session-step-state">${statusBadge(view.stopPending ? 'stop-requested' : view.status)}${view.status === 'needs-review' ? '<small>Earlier step updated (demo)</small>' : view.status === 'skipped' ? '<small>Optional step</small>' : ''}</span></button></li>`;
        }).join('')}</ol>
        <button type="button" class="stop-session-demo" data-stop-session>Stop Session<small>Browser-local orderly Stop demonstration</small></button>
      </section>
      <section class="session-card session-selected-card" aria-label="Selected step">
        ${step ? selectedStepMarkup(state, protocol, step) : free ? '<h3>No operation prepared</h3><p>Choose an operation to prepare its configuration. Nothing starts automatically.</p>' : '<h3>No protocol steps</h3><p>Add steps using the Protocol Editor in Setup.</p>'}
      </section>
    </div>`;
  const picker = panel.querySelector('#free-operation-choice');
  if (picker && [...picker.options].some(option => option.value === freeOperationChoice && !option.disabled)) picker.value = freeOperationChoice;
}

function selectedStepMarkup(state, protocol, step) {
  const view = sessionStepView(state, step);
  const { record, operation } = view;
  const operationType = operation?.type || 'Unsupported operation';
  const location = protocol ? `Step ${protocol.steps.indexOf(step) + 1} of ${protocol.steps.length}` : `Free Mode · ${operationType} · ${step.id}`;
  const capabilities = values => values.length ? values.map(escape).join(', ') : 'None';
  if (view.experiment) return `<div class="session-selected-heading"><div><p>${escape(location)}</p><h3>${escape(step.name)}</h3></div>${statusBadge(view.stopPending ? 'stop-requested' : view.status)}</div>
    <p class="session-step-description">${escape(step.description || 'No description supplied.')}</p>
    ${experimentConfigurationMarkup(step, view)}
    ${recordingSelectionMarkup(record, view)}
    ${record.reviewReason ? `<div class="session-review-explanation"><strong>Design proposal · review requested</strong><p>${escape(record.reviewReason)}</p></div>` : ''}
    ${experimentHistoryMarkup(record)}<p class="session-feedback" id="session-feedback" role="status">${escape(feedback)}</p>`;
  const actions = view.actions.map(action => {
    const label = action === 'run' ? protocol ? 'Run step' : 'Run operation' : action === 'repeat' && !protocol ? 'Repeat operation' : actionLabels[action];
    return `<button type="button" data-session-action="${action}" class="${['run', 'repeat', 'complete', 'validate'].includes(action) ? 'session-primary' : ''}">${label} <small>(demo)</small></button>`;
  }).join('');
  return `<div class="session-selected-heading"><div><p>${escape(location)}</p><h3>${escape(step.name)}</h3></div>${statusBadge(view.status)}</div>
    <p class="session-step-description">${escape(step.description || 'No description supplied.')}</p>
    <div class="session-detail-grid">
      <section class="session-detail-box"><h4>Step information</h4><dl class="session-step-information">
        <dt>Scientific operation</dt><dd>${escape(operation?.name || step.operation)} · ${escape(operationType)}</dd>
        <dt>${protocol ? 'Step status' : 'Occurrence'}</dt><dd>${protocol ? step.mandatory ? 'Required' : 'Optional' : escape(step.id)}</dd>
        <dt>Required capabilities</dt><dd>${capabilities(step.required)}</dd>
        <dt>Optional capabilities</dt><dd>${capabilities(step.optional)}</dd>
        <dt>Run support</dt><dd>${view.supports.run ? 'Supported (demo)' : 'Operation unavailable'}</dd>
        <dt>Recorded input</dt><dd>${view.supports.load ? 'Selection supported by this fixture; suitability not checked' : 'Not supported by this fixture'}</dd>
        <dt>Skip support</dt><dd>${!protocol ? 'Not applicable — no protocol checklist' : step.mandatory ? 'No — required step' : 'Optional steps only (demo)'}</dd>
      </dl></section>
      <section class="session-detail-box session-readiness"><h4>Step readiness <small>Simulated</small></h4><ul>${view.required.length ? readinessRows(view.required) : '<li><span aria-hidden="true">○</span><div>No required hardware capabilities declared.</div></li>'}</ul>
        <p>${view.ready ? 'Required declaration coverage is available in the demo.' : 'A required provider is unselected or unavailable in the demo.'}</p>
        <small>Illustrative checks only, not Controller readiness. No real storage-capacity, health, reservation or runtime checks.</small>
        ${view.issues.length ? `<ul>${view.issues.map(issue => `<li>${escape(issue)}</li>`).join('')}</ul>` : ''}
      </section>
    </div>
    ${recordingSelectionMarkup(record, view)}
    ${record.reviewReason ? `<div class="session-review-explanation"><strong>Design proposal · review requested</strong><p>${escape(record.reviewReason)}</p><p>Validate confirms only that this mock result is acceptable to the experimenter.</p></div>` : ''}
    <section class="session-action-section"><h4>Actions <small>Browser-local simulations</small></h4><div class="session-action-buttons">${actions || '<p>No execution action available for this state. Step information and history remain accessible.</p>'}</div>
      ${view.running && view.status !== 'running' ? '<p>Finish the current demonstration simulation before starting another.</p>' : ''}
      ${!view.included ? '<p>This optional step is excluded from this Session configuration.</p>' : ''}
      <p class="session-feedback" id="session-feedback" role="status">${escape(feedback)}</p>
    </section>
    ${view.status === 'running' ? '<section class="session-progress"><h4>Progress <small>Simulation only</small></h4><progress aria-label="Simulated step progress"></progress><p>Illustrative running state — no measured percentage or time estimate. Use Complete simulation or Simulate error to inspect the next state.</p></section>' : ''}
    <section class="session-output"><h4>Step output</h4>${record.results.length ? `<p>${record.results.length} retained mock result${record.results.length === 1 ? '' : 's'} · no scientific files</p><ol>${record.results.map(result => `<li><strong>${escape(result.name)}</strong><span>${escape(result.origin)} · ${escape(result.summary)}</span></li>`).join('')}</ol>` : '<div class="session-empty-output"><span aria-hidden="true">▱</span><p><strong>No output yet</strong><span>Demonstration output summaries will appear here when a simulation completes.</span></p></div>'}</section>
    <div class="session-detail-footer"><details class="session-history"><summary>↶ Step history (${record.history.length})</summary>${attemptHistoryMarkup(record)}<ol>${record.history.map(entry => `<li>${escape(entry)}</li>`).join('')}</ol></details><div class="session-context-links">
      <button type="button" data-session-navigate="parameters">View parameters ↗</button>
      ${operation ? `<button type="button" data-session-navigate="${operationType === 'Analysis' ? 'analysis' : 'experiment'}">Open ${operationType} workspace ↗</button>` : ''}
    </div></div>`;
}

function experimentConfigurationMarkup(step, view) {
  const { configuration, readOnly, modified, template } = view.experiment;
  const templates = experimentTemplates(state, step.operation, executionIdentity(state).owner);
  const canLaunch = view.actions.some(action => ['run', 'repeat'].includes(action)) && !readOnly;
  const participants = configuration.participants.map(id => devices.find(device => device.id === id)?.name || id);
  const groups = experimentDeviceGroups(state, step, configuration);
  const listed = new Set(groups.flatMap(group => group.options.map(device => device.id)));
  const additional = devices.filter(device => executionContext(state).selectedDevices.includes(device.id) && !listed.has(device.id));
  const outside = devices.filter(device => configuration.participants.includes(device.id) && !executionContext(state).selectedDevices.includes(device.id));
  const missing = groups.filter(group => group.required && !group.covered).map(group => group.capability);
  const parameters = configuration.participants.flatMap(id => (deviceExamples[id]?.fields || []).map(field => `${field.label}: ${configuration.values[field.id] === true ? 'Yes' : configuration.values[field.id] === false ? 'No' : configuration.values[field.id]}`));
  const otherIssues = view.issues.filter(issue => !issue.includes('required capability'));
  const auxiliary = view.actions.filter(action => ['validate', 'skip'].includes(action));
  return `<div class="experiment-summary-grid">
    <section class="session-detail-box experiment-template-card"><h4>Experiment template</h4><p>Optional starting configuration</p><label class="visually-hidden" for="experiment-template-select">Experiment template</label><select id="experiment-template-select" ${readOnly ? 'disabled' : ''}><option value="">None / current working values</option>${templates.map(item => `<option value="${escape(item.id)}" ${item.id === view.experiment.bundle.templateId ? 'selected' : ''}>${escape(item.name)} · ${item.owner === null ? 'Laboratory / shared' : 'Personal'}</option>`).join('')}</select><button type="button" data-load-experiment-template ${readOnly ? 'disabled' : ''}>Load template</button></section>
    <section class="session-detail-box experiment-current-card"><h4>Current ${readOnly ? 'executed' : 'working'} configuration</h4><dl class="session-step-information"><dt>Duration</dt><dd>${Number.isFinite(configuration.durationSeconds) ? escape(configuration.durationSeconds) + ' s' : 'Not set'}</dd><dt>Participating devices</dt><dd>${participants.map(escape).join(', ') || 'None selected'}</dd></dl><p class="experiment-parameter-summary">${parameters.slice(0, 4).map(escape).join(' · ') || 'No applicable example parameters.'}</p>${modified ? `<p class="configuration-modified">Modified from ${escape(template.name)}</p>` : ''}${readOnly && view.status !== 'running' ? '<button type="button" data-prepare-experiment>Prepare repeat (demo)</button>' : ''}${readOnly ? '<p>Executed settings are read-only.</p>' : ''}</section>
    </div>
    <section class="experiment-devices"><h4>Experiment devices</h4><p>Choose participants from this Session device pool${state.activeSession ? ', fixed at simulated launch' : ', prepared in Setup'}.</p>
      ${groups.map(group => `<section class="experiment-device-group" data-capability="${escape(group.capability)}"><h5>${escape(group.capability.replaceAll('_', ' '))} — ${group.required ? 'Required' : 'Optional'}</h5><div>${group.options.map(device => experimentDeviceOption(device, configuration, readOnly)).join('') || '<p>No Session devices provide this capability.</p>'}</div></section>`).join('')}
      ${additional.length ? `<details class="experiment-additional-devices" ${additional.some(device => configuration.participants.includes(device.id)) ? 'open' : ''}><summary>Additional Session devices (optional)</summary>${additional.map(device => experimentDeviceOption(device, configuration, readOnly)).join('')}</details>` : ''}
      ${outside.length ? `<div class="experiment-device-warning"><p>Template refers to devices outside this Session: ${outside.map(device => escape(device.name)).join(', ')}. They are not eligible for selection.</p><button type="button" data-remove-outside-devices ${readOnly ? 'disabled' : ''}>Remove out-of-Session references</button></div>` : ''}
      <div class="experiment-coverage ${missing.length ? 'coverage-missing' : 'coverage-good'}" role="status">${missing.length ? 'Missing required capability: ' + missing.map(escape).join(', ') : step.required.length ? '✓ All required capabilities covered' : 'No required hardware capabilities declared'} <small>(demo)</small></div>
      ${otherIssues.length ? `<p class="experiment-device-warning">${otherIssues.map(escape).join(' ')}</p>` : ''}
      <p class="experiment-readiness-note">Declaration coverage and illustrative checks only — not full Controller readiness or storage-capacity confirmation.</p>
    </section>
    <div class="experiment-launch-stack"><button type="button" data-session-navigate="parameters">View / Edit Parameters ↗</button><button type="button" class="session-primary launch-experiment-demo" data-launch-experiment ${canLaunch ? '' : 'disabled'}>▶ Launch Experiment <small>Simulation only — no acquisition</small></button></div>
    ${auxiliary.length ? `<div class="experiment-step-actions">${auxiliary.map(action => `<button type="button" data-session-action="${action}">${actionLabels[action]} (demo)</button>`).join('')}</div>` : ''}
    ${view.status === 'running' && !view.stopPending ? '<details class="experiment-simulation-controls"><summary>Simulation controls</summary><button type="button" data-session-action="complete">Complete simulation</button><button type="button" data-session-action="error">Simulate error</button></details>' : ''}
    ${view.stopPending ? '<p class="experiment-readiness-note">Normal Stop requested in Experiment. The local stop scenario is pending; cleanup and preservation are not confirmed.</p>' : ''}`;
}

function experimentDeviceOption(device, configuration, readOnly) {
  const checked = configuration.participants.includes(device.id);
  return `<div class="experiment-device-row"><label class="experiment-device-option"><input type="checkbox" data-session-experiment-device="${device.id}" ${checked ? 'checked' : ''} ${readOnly || (!device.available && !checked) ? 'disabled' : ''}><span>${escape(device.name)}${device.available ? '' : ' · unavailable (demo)'}</span></label>${checked ? `<button type="button" data-validate-device="${device.id}" aria-label="Validate ${escape(device.name)}">Validate</button>` : ''}</div>`;
}
function experimentHistoryMarkup(record) {
  return `<details class="experiment-history"><summary>Results &amp; history (${record.results.length} mock results · ${record.history.length} entries)</summary>${record.results.length ? `<div class="session-output"><h4>Retained mock results</h4><ol>${record.results.map(result => `<li><strong>${escape(result.name)}</strong><span>${escape(result.origin)} · ${escape(result.summary)}</span></li>`).join('')}</ol></div>` : ''}${attemptHistoryMarkup(record)}<ol>${record.history.map(entry => `<li>${escape(entry)}</li>`).join('')}</ol></details>`;
}

function recordingSelectionMarkup(record, view) {
  const input = record.recordingSelection;
  const reviews = record.recordedInputs || [];
  if (!input && !reviews.length) return '';
  return `<section class="session-detail-box recording-context"><h4>Previous recording · browser-local demonstration</h4>${input ? `<p><strong>${escape(input.selection.name)}</strong> · ${escape(input.selection.kind)} · ${escape(input.review)}</p><p>${escape(input.selection.entries[0]?.relativePath || input.selection.entries[0]?.name || '')} · ${input.selection.entries.length} file(s). No absolute path available.</p><p>Selection is not acceptance. Simulated outcomes do not validate, import or process these data.</p><button type="button" data-clear-recording ${view.running ? 'disabled' : ''}>Clear selection</button>` : ''}${reviews.length ? `<details><summary>Recorded-input outcome history (${reviews.length})</summary><ol>${reviews.map(review => `<li>${escape(review.id)} · ${escape(review.selection.name)} · ${escape(review.outcome)} (simulated) — no new execution or output</li>`).join('')}</ol></details>` : ''}</section>`;
}

function attemptHistoryMarkup(record) {
  return record.attempts?.length ? `<h4>Demonstration attempts</h4><ol>${record.attempts.map(attempt => `<li>${escape(attempt.id)} · ${escape(attempt.status)}</li>`).join('')}</ol>` : '';
}

panel.addEventListener('click', event => {
  const validationButton = event.target.closest('[data-validate-device]');
  if (validationButton) {
    try { startDeviceValidation(state, validationButton.dataset.validateDevice, performance.now()); }
    catch (error) {
      const activeValidation = executionContext(state).deviceValidation;
      if (activeValidation) { activeValidation.notice = error.message; navigate('experiment'); }
      else { feedback = error.message; renderSession(); }
      return;
    }
    navigate('experiment'); return;
  }
  if (event.target.closest('[data-clear-recording]')) {
    clearRecordingSelection(state, sessionProgress(state).selectedId); renderSession(); return;
  }
  if (event.target.closest('[data-prepare-free-operation]')) {
    try { freeOperationChoice = panel.querySelector('#free-operation-choice').value; prepareFreeOperation(state, freeOperationChoice); feedback = ''; }
    catch (error) { feedback = error.message; }
    renderSession(); return;
  }
  if (event.target.closest('[data-remove-outside-devices]')) {
    const progress = sessionProgress(state);
    const context = executionContext(state);
    const { step } = selectedStepContext(state);
    const participants = sessionStepView(state, step).experiment.configuration.participants.filter(id => context.selectedDevices.includes(id));
    updateExperiment(state, step, progress.steps[step.id], { participants }); renderSession(); return;
  }
  if (event.target.closest('[data-stop-session]')) {
    confirmStop('Session', () => {
      const preview = sessionStopPreview(stopScenario);
      stopEscalation = preview.canKill;
      stopDialog.innerHTML = `<h2 id="session-stop-title">${preview.canKill ? 'Session Stop blocked — demonstration' : 'Session Stop — demonstration'}</h2><p>${escape(preview.message)}</p><p>Fixture only: no Session command is sent and the current demonstration run is unchanged.</p><div class="catalog-dialog__actions"><button type="button" data-stop-dismiss>${preview.canKill ? 'Cancel' : 'Close'}</button>${preview.canKill ? '<button type="button" data-session-kill>Kill Session… (preview)</button>' : ''}</div>`;
      stopDialog.showModal();
    });
    return;
  }
  const select = event.target.closest('[data-session-step]');
  const action = event.target.closest('[data-session-action]');
  const navigation = event.target.closest('[data-session-navigate]');
  if (navigation) {
    navigate(navigation.dataset.sessionNavigate);
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
    if (action.dataset.sessionAction === 'load') {
      openRecordingPicker(selection => {
        try { selectRecording(state, selectedId, selection); feedback = 'Recording metadata selected only. Choose an explicit simulated outcome; nothing was executed or accepted automatically.'; }
        catch (error) { feedback = error.message; }
        renderSession();
      });
      return;
    }
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
  if (event.target.closest('[data-load-experiment-template], [data-prepare-experiment], [data-launch-experiment]')) {
    const progress = sessionProgress(state);
    const context = executionContext(state);
    const { step } = selectedStepContext(state);
    try {
      if (event.target.closest('[data-load-experiment-template]')) {
        const id = panel.querySelector('#experiment-template-select').value;
        const owner = executionIdentity(state).owner;
        const record = progress.steps[step.id];
        if (id && sessionStepView(state, step).experiment.workingModified) {
          pendingTemplateLoad = { step, record, id, owner };
          templateConfirmation.showModal();
          return;
        }
        loadExperimentTemplate(state, step, record, id, owner);
      }
      else if (event.target.closest('[data-prepare-experiment]')) prepareExperimentRepeat(state, step, progress.steps[step.id]);
      else {
        const view = sessionStepView(state, step);
        actOnSessionStep(state, step.id, view.actions.includes('repeat') ? 'repeat' : 'run');
        executionContext(state).experimentMonitor.identity = executionIdentity(state);
        navigate('experiment');
      }
      feedback = 'Demonstration configuration updated in page memory only.';
    } catch (error) { feedback = error.message; }
    renderSession();
  }
});
panel.addEventListener('change', event => {
  const id = event.target.dataset.sessionExperimentDevice;
  if (!id) return;
  const progress = sessionProgress(state);
  const context = executionContext(state);
  const { step } = selectedStepContext(state);
  const view = sessionStepView(state, step);
  const participants = view.experiment.configuration.participants.filter(value => value !== id);
  if (event.target.checked) participants.push(id);
  const scroll = panel.scrollTop;
  const additionalOpen = panel.querySelector('.experiment-additional-devices')?.open;
  try { updateExperiment(state, step, progress.steps[step.id], { participants }); feedback = 'Experiment participation updated; Session inclusion is unchanged.'; }
  catch (error) { feedback = error.message; }
  renderSession();
  panel.scrollTop = scroll;
  if (panel.querySelector('.experiment-additional-devices')) panel.querySelector('.experiment-additional-devices').open = additionalOpen;
  panel.querySelector(`[data-session-experiment-device="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
});
document.addEventListener('gui-section-changed', event => {
  if (event.detail === 'session') { feedback = ''; renderSession(); }
});
renderSession();
