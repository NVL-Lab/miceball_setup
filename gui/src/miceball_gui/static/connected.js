// Shared presenters own markup; this entry binds them to the existing backend.
import { state, renderSetup } from './protocol-setup.js';
import { devices, clone, preparedProtocol, preparedFreeOperation, coverage } from './protocol-demo.mjs';
import { syncOwnershipPresentation } from './ownership-presentation.js';
import { deviceExamples, experimentView, experimentIssues, experimentEstimateKey, experimentStorageEstimate } from './experiment-demo.mjs';
import { resolveParameterContext } from './parameter-context.mjs';
import { applyControllerSnapshot } from './session-context.mjs';
import { selectedStepContext } from './session-demo.mjs';
import { renderSession } from './session-view.js';
import { renderParameters, renderStorageEstimate } from './parameters-view.js';
import { renderExperiment } from './scientific-views.js';
import { navigate, configurationStringEditor, setConfigurationString, readConfigurationString, renderAcceptedCatalogIdentity } from './gui-presentation.js';
import { catalogClient } from './catalog-client.mjs';
import { localCalendarDate } from './calendar-date.mjs';
import { confirmStop } from './stop-confirmation.mjs';
import { serviceActions, updateServices, startServicesRefresh, showBlockedServiceStop } from './services-view.js';
import { configurationIdentity, configurationNumber, configurationEqual, parseConfigurationJSON, stringifyConfiguration } from './configuration-values.mjs';
import { activityPresentation } from './activity-presentation.mjs';
import { activities as outcomes, recordActivity, updateActivity, recordLocalActivity, recordActivityTransition } from './activity-history.mjs';
import { deviceParameterFields } from './parameter-constraints.mjs';
import { installArtifactDestinations, refreshArtifactDestinations, syncArtifactDestinations, invalidateArtifactDestinations, selectedArtifactDestination } from './artifact-destinations.js';
import { installConnectedStorage, syncConnectedStorage, invalidateConnectedStorage, refreshConnectedStorage } from './connected-storage.js';

const $ = selector => document.querySelector(selector);
let socket, browserId, confirmed = false, busy = false, refreshing = false, lastRender = '';
let inventoryRequest = null;
let liveServices = [];
let timingPending = false;
const waiting = new Map();
const current = () => state.controllerSnapshot;
serviceActions.activityHistory = () => outcomes;
function actionRefusal(entry, reason) {
  updateActivity(entry, {source: 'local', status: 'rejected', error: reason, controllerCommand: false});
  $('.setup-demo-note').textContent = 'Action not sent. See Activity History in Services.';
  return entry;
}
function noteConnectionLoss(reason) {
  recordActivityTransition('connection_status', 'unknown', reason);
}
state.actions.recordActivity = recordLocalActivity;
serviceActions.recordActivity = state.actions.recordActivity;
function invalidateServiceConfirmation() {
  state.expectedSize = null;
  invalidateConnectedStorage();
  invalidateArtifactDestinations();
  for (const inventory of Object.values(state.inventory)) { delete inventory.configured_parameters; delete inventory.administrative_configuration; }
  // Replace projections so replies admitted before this loss cannot promote them.
  liveServices = liveServices.map(service => ({...service, current: false, diagnosticsCurrent: false, pending: false, attempt: null}));
  updateServices(liveServices, 'Controller confirmation unavailable; current service availability is unknown.');
  if (!$('#panel-parameters').hidden) renderParameters();
}

$('.topbar').insertAdjacentHTML('beforeend', '<div class="connection-tools"><span id="connection-state" role="status">Connecting</span><button id="view-only" type="button">View Only</button><button id="take-over" type="button">Take Over</button></div>');
$('.topbar__eyebrow').textContent = 'Connected Framework';
$('.setup-demo-note').textContent = 'Controller connection unconfirmed. Local preparation is not acceptance or persistence.';
const storageCard = $('[aria-labelledby="storage-title"]');
const storageBody = storageCard.querySelector('.setup-disclosure-body') || storageCard;
storageCard.querySelector('input').readOnly = false;
storageCard.querySelector('input').value = '';
storageCard.querySelector('button').disabled = true;
$('.storage-path code').textContent = 'Assigned by the configured storage owners';
for (const value of $('.storage-stats').querySelectorAll('dd')) value.textContent = 'Unavailable';
$('#launch-demo-note').textContent = 'Requests Controller acceptance, reservation and durable preservation. Launch does not start an Experiment.';
for (const button of document.querySelectorAll('#view-only, #take-over')) button.className = 'dialog-button';
storageBody.insertAdjacentHTML('beforeend', '<label>Error evidence location<input id="error-evidence-location"></label>');
const sessionName = configurationStringEditor($('.session-identity-grid input[type="text"]'), $('.session-identity-grid input[type="text"]').value, true);
const sessionDate = $('.session-identity-grid input[type="date"]');
const sessionNumber = $('.session-identity-grid input[type="number"]');
const sessionNotes = configurationStringEditor($('[aria-labelledby="notes-title"] textarea'));
const errorLocation = configurationStringEditor($('#error-evidence-location'), '', true);
installArtifactDestinations({snapshot: current, canControl,
  command: (operation, parameters) => command(operation, parameters, null),
  read: async () => {
    if (!confirmed) throw new Error('Controller connection is unconfirmed.');
    const connection = socket, instance = current()?.instance_id;
    const result = requireResult(await request('list_artifact_destinations'));
    if (!confirmed || connection !== socket || socket.readyState !== WebSocket.OPEN || instance !== current()?.instance_id)
      throw new Error('Destination information belongs to an unconfirmed connection.');
    return result;
  }});
installConnectedStorage({snapshot: current, canControl,
  read: async (operation, parameters, sid) => {
    if (!confirmed) throw new Error('Controller connection is unconfirmed.');
    const connection = socket, instance = current()?.instance_id;
    const result = requireResult(await request(operation, parameters, sid));
    if (!confirmed || connection !== socket || socket.readyState !== WebSocket.OPEN || instance !== current()?.instance_id)
      throw new Error('Historical readback belongs to an unconfirmed connection.');
    return result;
  },
  collect: async (sid, parameters) => {
    const connection = socket;
    const entry = recordActivity('collect_saved_session_artifacts_remote');
    Object.assign(entry, {session_id: sid, evidence_id: parameters.evidence_id,
      deletion_requested: Boolean(parameters.deletion), deletion_operation_id: parameters.deletion?.operation_id});
    await command('collect_saved_session_artifacts_remote', parameters, sid, entry);
    await waitForPendingOutcome(entry, connection);
    return entry;
  }, refreshOutcomes: refresh});
($('.device-card .setup-disclosure-body') || $('.device-card')).insertAdjacentHTML('afterbegin', '<div class="inventory-controls"><label>Configured AcquisitionNode<select id="inventory-node"></select></label><button id="load-inventory" type="button">Refresh inventory</button><span id="inventory-status" role="status">Inventory unconfirmed</span></div>');
$('.readiness-card').insertAdjacentHTML('beforeend', '<details><summary>Accepted Session configuration</summary><pre id="accepted-configuration">No accepted configuration confirmed</pre></details>');
$('#load-inventory').className = 'dialog-button';
$('#inventory-status').className = 'prototype-caption';

function controlBlocker(except = null) {
  if (!confirmed) return 'Controller connection unconfirmed';
  if (!current()?.control?.controlling) return 'View Only; acquire control to launch';
  if (busy) return 'Another request is in progress; waiting for its response';
  const pending = outcomes.find(o => o !== except && (o.continuationPending || o.controllerCommand && ['pending', 'uncertain'].includes(o.status)
    && !(o.operation === 'update_device_configuration' && o.status === 'uncertain' && o.configurationReconciled)));
  return pending ? pending.continuationPending ? pending.operation === 'normal_stop_session'
    ? 'Session Stop/release sequence is still pending' : pending.operation === 'release_session'
      ? 'Session release/readback is still pending' : 'Session launch/start sequence is still pending'
    : activityPresentation(pending).message : '';
}
function canControl(except = null) {
  return !controlBlocker(except);
}
function controls() {
  queueMicrotask(() => state.actions.refreshExpectedSize?.());
  const status = current()?.status;
  const launch = outcomes.findLast(entry => entry.operation === 'launch_session');
  if (!status?.session_id && launch) $('.setup-demo-note').textContent = 'Session launch not confirmed. See Activity History in Services.';
  document.documentElement.dataset.controlMode = !confirmed ? 'unconfirmed' : current()?.control?.controlling ? 'controlling' : 'view-only';
  const launchBlocker = controlBlocker() || (status?.session_id ? 'Session already accepted; use the Session workspace' : '');
  $('.launch-session-demo').disabled = Boolean(launchBlocker);
  $('.launch-session-demo span').textContent = launchBlocker || 'Request Controller launch and start';
  for (const control of [sessionName, sessionDate, sessionNumber, sessionNotes, errorLocation]) {
    control.readOnly = Boolean(status?.session_id);
    if (control.nextElementSibling?.hasAttribute('data-string-mode')) control.nextElementSibling.disabled = control.readOnly;
  }
  for (const button of document.querySelectorAll('[data-launch-experiment], [data-stop-experiment], [data-reconcile-expiry], [data-stop-session], [data-start-session], [data-release-session]')) {
    if (!canControl()) button.disabled = true;
    if (button.hasAttribute('data-start-session')) button.disabled = !canControl() || status?.session_state !== 'initialized';
    if (button.hasAttribute('data-stop-session')) button.disabled = !canControl() || !['running', 'stopping', 'failed'].includes(status?.session_state);
    if (button.hasAttribute('data-release-session')) {
      button.hidden = !status?.session_id || !['completed', 'failed', 'aborted'].includes(status?.session_state);
      button.disabled = !canControl() || button.hidden;
    }
    if (button.hasAttribute('data-stop-experiment') || button.hasAttribute('data-reconcile-expiry')) button.disabled = !canControl() || !status?.active_experiment_id;
    if (button.hasAttribute('data-launch-experiment')) {
      const {step, record} = selectedStepContext(state);
      button.disabled = !canControl() || status?.session_state !== 'running' || Boolean(status?.active_experiment_id)
        || !step || experimentIssues(state, step, experimentView(state, step, record).configuration).length > 0;
    }
  }
  for (const button of document.querySelectorAll('[data-live-session-kill]')) button.disabled = !canControl() || current()?.status?.last_command?.command !== 'normal_stop_session' || current()?.status?.last_command?.succeeded !== false;
  $('#take-over').disabled = !confirmed || busy;
  $('#view-only').disabled = !confirmed || busy;
  $('#load-inventory').disabled = Boolean(inventoryRequest) || !confirmed || busy || !$('#inventory-node').value;
  $('#inventory-node').disabled = Boolean(inventoryRequest);
  for (const input of document.querySelectorAll('#session-device-list input')) input.disabled = Boolean(status?.session_id) || !devices.find(device => device.id === input.dataset.device)?.available;
  const closeoutFeedback = document.querySelector('[data-session-closeout-feedback]');
  if (closeoutFeedback) {
    const release = outcomes.findLast(entry => entry.operation === 'release_session' && entry.session_id === status?.session_id);
    closeoutFeedback.textContent = status?.session_state === 'completed'
      ? `Session completed; release ${release ? release.status === 'failed' || release.status === 'rejected' ? 'blocked' : 'unconfirmed' : 'not yet confirmed'}.${release ? ` ${release.error || release.feedback_error || activityPresentation(release).message}` : ''}`
      : '';
  }
  updateServices(liveServices);
  syncArtifactDestinations();
  syncConnectedStorage();
  syncOwnershipPresentation();
  state.actions.renderSetupReadiness();
}
state.actions.renderSetupReadiness = () => {
  const rows = [];
  // Text nodes below keep configuration identities and errors out of markup.
  const details = [];
  const row = (label, detail, missing = false) => {
    rows.push(`<li><span class="${missing ? 'missing-dot' : ''}">${missing ? '!' : '·'}</span><div>${label}</div><strong></strong></li>`);
    details.push(detail);
  };
  if (current()?.status?.session_id) {
    row(confirmed ? 'Accepted Session' : 'Last confirmed Session', confirmed ? current().status.session_state || 'State unconfirmed' : 'Current state unconfirmed; reconnect to check.', !confirmed);
    row('Next action', confirmed ? 'Continue in Session; its device pool is fixed.' : 'Restore the Controller connection before submitting operations.', !confirmed);
  } else {
    row('Control', controlBlocker() || 'Ready to submit preparation', Boolean(controlBlocker()));
    const selected = state.selectedDevices.map(id => devices.find(device => device.id === id));
    row('Session devices', !selected.length ? 'Select the devices needed for this Session.'
      : selected.some(device => !device?.available) ? 'Refresh inventory for unavailable selected devices.'
      : `${selected.length} selected · inventory confirmed`, selected.some(device => !device?.available));
    const missing = coverage(state).required.filter(item => !item.providers.length).map(item => item.capability);
    row('Required capabilities', missing.length ? `Select devices providing: ${missing.join(', ')}` : 'Selected devices cover the included steps', Boolean(missing.length));
    row('Session settings', catalogClient.snapshot?.synchronization_configuration ? 'Saved synchronization settings available' : 'Backend synchronization settings unavailable', !catalogClient.snapshot?.synchronization_configuration);
    try { selectedArtifactDestination(); row('Storage destination', 'Selected; capacity is checked for each Experiment'); }
    catch (error) { row('Storage destination', error.message, true); }
    row('Admission', 'Session is not accepted yet. Submit preparation for Controller checks.');
  }
  const list = $('.readiness-card ul'); list.innerHTML = rows.join('');
  [...list.querySelectorAll('strong')].forEach((element, index) => { element.textContent = details[index]; });
};
state.actions.syncControls = controls;
state.actions.canControl = canControl;
function request(operation, parameters = {}, session_id = null, entry = null) {
  if (socket?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Backend disconnected; outcome unconfirmed'));
  const id = crypto.randomUUID(), request_id = `${browserId}-${id}`, instance_id = current()?.instance_id;
  const data = stringifyConfiguration({id, operation, session_id, parameters});
  if (entry) updateActivity(entry, {source: 'submission'});
  return new Promise((resolve, reject) => {
    const uncertain = reason => Object.assign(new Error(reason), {request_id, instance_id});
    const timer = setTimeout(() => { waiting.delete(id); reject(uncertain('Response timeout; outcome unconfirmed')); }, 30000);
    waiting.set(id, {resolve: message => resolve({...message, submitted_request_id: request_id, submitted_instance_id: instance_id}), reject, timer, uncertain});
    try { socket.send(data); }
    catch (error) { clearTimeout(timer); waiting.delete(id); reject(error); return; }
    if (entry) Object.assign(entry, {request_id, instance_id, source: 'controller', controllerCommand: true});
  });
}
function requireResult(reply) {
  if (reply.result?.status !== 'succeeded') throw new Error(reply.result?.error || reply.error || reply.result?.status || reply.status);
  return reply.result.outcome.details;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const snapshot = requireResult(await request('read_controller_state'));
    const previous = current();
    const wasConfirmed = confirmed;
    applyControllerSnapshot(state, snapshot); confirmed = true;
    if (previous?.status?.session_id !== snapshot.status?.session_id) state.expectedSize = null;
    recordActivityTransition('connection_status', 'succeeded');
    if (snapshot.control?.controlling && (!previous?.control?.controlling || previous.instance_id !== snapshot.instance_id))
      document.dispatchEvent(new Event('gui-control-acquired'));
    const previousServices = liveServices;
    const changedOwner = previous?.instance_id !== snapshot.instance_id;
    if (changedOwner) invalidateServiceConfirmation();
    if (changedOwner || !wasConfirmed) refreshArtifactDestinations();
    if ((changedOwner || !wasConfirmed) && !$('#panel-storage').hidden) refreshConnectedStorage();
    liveServices = (snapshot.configured_services || []).map(participant => {
      const id = configurationIdentity(participant.component_type, participant.component_id);
      const prior = previousServices.find(s => s.id === id);
      if (prior) return changedOwner ? {...prior, current: false, diagnosticsCurrent: false, pending: false, attempt: null} : prior;
      return {id, participant,
        name: ({controller: 'Controller', acquisition_node: 'AcquisitionNode', ingestor: 'Ingestor', storage_manager: 'StorageManager', synchronization_manager: 'Synchronization Manager'})[participant.component_type],
        computer: participant.component_id, readiness: 'Unknown', current: false, confirmed: null};
    });
    updateServices(liveServices, undefined, Array.isArray(snapshot.configured_services));
    if (changedOwner) updateServices(liveServices, 'Controller changed; previous readiness feedback and confirmations are invalidated.');
    if ((!previousServices.length || changedOwner) && liveServices.length) serviceActions.refresh();
    if (snapshot.configuration && (previous?.status?.session_id !== snapshot.status.session_id || previous?.instance_id !== snapshot.instance_id)) {
      const config = snapshot.configuration, metadata = config.session_parameters || {};
      setConfigurationString(sessionName, metadata.name ?? '');
      sessionDate.value = metadata.date ?? '';
      sessionNumber.value = metadata.number ?? '';
      sessionDate.dispatchEvent(new Event('input'));
      renderAcceptedCatalogIdentity(metadata);
      setConfigurationString(errorLocation, config.error_evidence_location ?? '');
      setConfigurationString(sessionNotes, metadata.notes ?? '');
    }
    if (previous?.instance_id === snapshot.instance_id && previous?.status?.session_id
        && !snapshot.status?.session_id && snapshot.configuration === null) {
      sessionDate.value = localCalendarDate(); sessionDate.dispatchEvent(new Event('input'));
    }
    if (!snapshot.status?.session_id || !snapshot.configuration) {
      const historical = document.querySelectorAll('[data-accepted-identity]');
      for (const option of historical) delete option.dataset.acceptedIdentity;
      if (historical.length && catalogClient.snapshot) document.dispatchEvent(new Event('gui-catalog-changed'));
    }
    for (const operation of snapshot.pending_operations) if (!outcomes.some(o => o.request_id === operation.request_id && o.instance_id === snapshot.instance_id)) {
      const entry = recordActivity(operation.operation, 'controller');
      Object.assign(entry, {request_id: operation.request_id, instance_id: snapshot.instance_id, controllerCommand: true});
    }
    $('#connection-state').textContent = `${snapshot.controller_id} · ${snapshot.control.controlling ? 'Controlling' : 'View Only'}`;
    $('.setup-demo-note').textContent = snapshot.status.session_id ? 'Accepted Session · configuration fixed.' : 'Unsent local preparation.';
    $('#accepted-configuration').textContent = JSON.stringify(snapshot.configuration, null, 2);
    const choice = $('#inventory-node');
    if (JSON.stringify([...choice.options].map(o => o.value)) !== JSON.stringify(snapshot.configured_nodes)) choice.replaceChildren(...snapshot.configured_nodes.map(id => new Option(id, id)));
    // Apply confirmed ownership before any awaited reconciliation/inventory work.
    controls();
    let completedNavigation = null;
    for (const entry of outcomes.filter(o => o.controllerCommand && o.request_id && o.instance_id && ['pending', 'uncertain'].includes(o.status))) {
      const result = requireResult(await request('read_operation_outcome', {target_request_id: entry.request_id, instance_id: entry.instance_id}));
      if (entry.operation === 'collect_saved_session_artifacts_remote') {
        const recovered = result.result;
        if (result.instance_id !== entry.instance_id || !recovered
            || recovered.request_id !== entry.request_id || recovered.operation !== entry.operation
            || recovered.session_id !== entry.session_id) continue;
        if (result.status !== recovered.status) continue;
        if (recovered.status === 'succeeded'
            && recovered.outcome?.details?.collection_outcome?.collection_evidence?.evidence_id !== entry.evidence_id) continue;
        if (entry.deletion_requested && recovered.outcome?.details?.deletion
            && recovered.outcome.details.deletion.details?.operation_id !== entry.deletion_operation_id) continue;
        if (entry.deletion_requested && recovered.status === 'succeeded' && !recovered.outcome?.details?.deletion) continue;
      }
      if (entry.operation === 'update_device_configuration' && entry.status === 'uncertain' && result.status === 'unknown') continue;
      updateActivity(entry, {status: result.status, result: result.result, error: result.result?.error || (result.status === 'unknown' ? 'No matching outcome is available from the current Controller.' : entry.error)});
      if (entry.status === 'succeeded' && ['launch_session', 'start_launched_experiment'].includes(entry.operation)) entry.navigationPending = true;
    }
    // A completed outcome may arrive between two state reads. Wait for matching
    // authoritative state instead of losing the navigation on that interleaving.
    for (const entry of outcomes.filter(entry => entry.navigationPending)) {
      if (entry.status === 'succeeded' && entry.instance_id === snapshot.instance_id) {
        if (entry.operation === 'launch_session' && entry.result?.outcome?.details?.session_id === snapshot.status.session_id && snapshot.status.session_id) completedNavigation = 'session';
        if (entry.operation === 'start_launched_experiment' && snapshot.status.active_experiment_id) completedNavigation = 'experiment';
        if (completedNavigation) entry.navigationPending = false;
      }
    }
    updateServices(liveServices);
    $('#live-closeout-status').textContent = JSON.stringify({closeout: snapshot.closeout || 'Unconfirmed', timing_interpretations: snapshot.timing || []}, null, 2);
    const signature = JSON.stringify([snapshot.instance_id, snapshot.control, snapshot.status, snapshot.configuration, snapshot.experiments]);
    if (signature !== lastRender) { lastRender = signature; renderSetup(); renderSession(); renderExperiment(); if (!$('#panel-parameters').hidden) renderParameters(); }
    if (completedNavigation) navigate(completedNavigation);
    if (previous?.status?.session_id !== snapshot.status.session_id || changedOwner || !wasConfirmed) {
      for (const node of Object.keys(state.inventory)) await refreshInventory(node);
    }
  } catch (error) { noteConnectionLoss(error.message); confirmed = false; invalidateServiceConfirmation(); $('#connection-state').textContent = `Unconfirmed · ${error.message}`; }
  finally { refreshing = false; controls(); }
}
async function command(operation, parameters = {}, session_id = current()?.status?.session_id || null, entry = null) {
  entry ||= recordActivity(operation);
  if (!confirmed) return actionRefusal(entry, 'Controller connection is unconfirmed. No request was sent.');
  if (busy) return actionRefusal(entry, 'Another request is in progress. No request was sent.');
  if (!current()?.control.controlling && !['view_only', 'take_browser_control'].includes(operation))
    return actionRefusal(entry, 'View Only does not permit this operation. No request was sent.');
  if (!['view_only', 'take_browser_control'].includes(operation) && !canControl(entry))
    return actionRefusal(entry, 'An earlier operation is pending or unconfirmed. No request was sent.');
  busy = true; controls();
  try {
    let reply;
    try { reply = await request(operation, parameters, session_id, entry); }
    catch (error) {
      updateActivity(entry, error.request_id && error.instance_id
        ? {source: 'controller', status: 'uncertain', responseStatus: 'uncertain', request_id: error.request_id, instance_id: error.instance_id, error: error.message}
        : {source: 'submission', status: 'failed', responseStatus: 'failed', error: error.message, controllerCommand: false});
      return entry;
    }
    // Rendering a received result must not turn that result into a synthetic failure.
    updateActivity(entry, {source: reply.result ? 'controller' : 'submission',
      instance_id: reply.instance_id || reply.submitted_instance_id,
      request_id: reply.result?.request_id || reply.submitted_request_id,
      status: reply.result?.status || reply.status, result: reply.result || reply,
      responseStatus: reply.result?.status || reply.status,
      error: reply.result?.error || reply.error || ''});
  } finally { busy = false; await refresh(); controls(); }
  return entry;
}
const localAction = (operation, action) => async () => {
  const entry = recordActivity(operation);
  try { await action(entry); }
  catch (error) {
    if (entry.controllerCommand) {
      entry.feedback_error = error.message;
      $('.setup-demo-note').textContent = 'The display could not be refreshed. The received outcome remains retained; check Session status and Activity History.';
      return;
    }
    updateActivity(entry, {source: 'local', status: 'failed', error: error.message, controllerCommand: false});
    $('.setup-demo-note').textContent = 'Preparation failed. See Activity History in Services.';
  }
};
async function waitForPendingOutcome(entry, connection) {
  if (entry.responseStatus !== 'pending' || entry.status !== 'pending' || connection.readyState !== WebSocket.OPEN) return;
  await new Promise(resolve => {
    const finish = () => { document.removeEventListener('gui-activity-changed', changed); connection.removeEventListener('close', finish); resolve(); };
    const changed = () => { if (entry.status !== 'pending') finish(); };
    document.addEventListener('gui-activity-changed', changed);
    connection.addEventListener('close', finish, {once: true});
    changed();
  });
}
state.actions.launchSession = localAction('launch_session', async entry => {
  if (!canControl(entry) || current()?.status?.session_id) return actionRefusal(entry, 'Session launch is unavailable or already pending. No request was sent.');
  const config = {protocol_plan: {}, session_parameters: {}};
  if (!catalogClient.snapshot?.synchronization_configuration) throw new Error('Backend synchronization settings are unavailable.');
  config.synchronization_configuration = clone(catalogClient.snapshot.synchronization_configuration);
  config.storage_location = selectedArtifactDestination();
  config.error_evidence_location = readConfigurationString(errorLocation);
  config.session_parameters = {...config.session_parameters};
  for (const key of ['experimenter', 'project', 'animal']) {
    const select = $(`#${key}-select`);
    if (select.value.startsWith('__new_')) throw new Error(`Finish the local ${key} entry.`);
    if (select.value) {
      config.session_parameters[key] = select.selectedOptions[0].textContent;
      config.session_parameters[`catalog_${key}_id`] = select.value;
    }
  }
  if (sessionNumber.validity.badInput) throw new Error('Invalid Session number. Enter a finite value representable by this GUI.');
  const animal = catalogClient.snapshot?.catalog.animals.find(item => item.id === $('#animal-select').value);
  if (animal) config.session_parameters.catalog_animal_details = clone(animal);
  Object.assign(config.session_parameters, {name: readConfigurationString(sessionName), date: sessionDate.value, number: sessionNumber.value ? configurationNumber(sessionNumber.value) : null, notes: readConfigurationString(sessionNotes)});
  state.submittedProcedure = preparedProtocol(state);
  state.submittedOperation = preparedFreeOperation(state);
  if (state.submittedProcedure) {
    state.submittedProcedure.included = clone(state.included);
    state.submittedProcedure.templateId = state.templateId;
  }
  config.protocol_reference = state.submittedProcedure?.name || null;
  const selections = Object.create(null);
  for (const id of state.selectedDevices) {
    const device = devices.find(item => item.id === id);
    if (!device?.available) throw new Error('Selected inventory is unconfirmed.');
    (selections[device.nodeId] ??= []).push(clone(device.declaration));
  }
  const connection = socket, instance = current().instance_id, generation = current().control.generation;
  entry.continuationPending = true;
  try {
    await command('launch_session', {selections, config_parameters: config, scientific_outputs: []}, null, entry);
    if (!['succeeded', 'pending'].includes(entry.responseStatus)) return;
    // Only this still-connected user action may continue a definitively completed launch.
    // Existing outcome observation supplies completion; reconnect never resumes this chain.
    await waitForPendingOutcome(entry, connection);
    if (entry.status !== 'succeeded' || connection !== socket || connection.readyState !== WebSocket.OPEN) return;
    const sessionId = entry.result?.outcome?.details?.session_id;
    const fresh = requireResult(await request('read_controller_state'));
    if (!sessionId || entry.instance_id !== instance || fresh.instance_id !== instance
        || !confirmed || connection !== socket || connection.readyState !== WebSocket.OPEN
        || !fresh.control?.controlling || fresh.control.generation !== generation
        || fresh.status?.session_id !== sessionId || fresh.status.session_state !== 'initialized') return;
    entry.continuationPending = false;
    await command('start_launched_session', {}, sessionId);
    if (current()?.status.session_id === sessionId) navigate('session');
  } finally { entry.continuationPending = false; controls(); }
});
state.actions.startSession = () => command('start_launched_session');
async function releaseSessionBinding(sid) {
  const connection = socket, instance = current()?.instance_id;
  const entry = recordActivity('release_session');
  entry.session_id = sid;
  entry.continuationPending = true;
  try {
    await command('release_session', {}, sid, entry);
    await waitForPendingOutcome(entry, connection);
    if (entry.status !== 'succeeded' || entry.instance_id !== instance || connection !== socket
        || connection.readyState !== WebSocket.OPEN) return;
    const fresh = requireResult(await request('read_controller_state'));
    if (fresh.instance_id !== instance || fresh.status?.session_id || fresh.configuration !== null)
      throw new Error('Released Session state is unconfirmed; inspect current Controller state.');
    await refresh();
  } catch (error) { updateActivity(entry, {feedback_error: error.message}); }
  finally { entry.continuationPending = false; controls(); }
}
state.actions.stopSession = () => {
  const sid = current()?.status.session_id, connection = socket;
  const instance = current()?.instance_id, generation = current()?.control?.generation;
  confirmStop('Session', localAction('normal_stop_session', async entry => {
    if (!canControl(entry) || current()?.status.session_id !== sid || current()?.instance_id !== instance
        || current()?.control?.generation !== generation || connection !== socket) return actionRefusal(entry, 'Session or control changed. No Stop was sent.');
    entry.session_id = sid;
    entry.continuationPending = true;
    try {
      await command('normal_stop_session', {}, sid, entry);
      await waitForPendingOutcome(entry, connection);
      if (entry.status !== 'succeeded' || entry.responseStatus === 'uncertain' || entry.instance_id !== instance
          || connection !== socket || connection.readyState !== WebSocket.OPEN) return;
      const fresh = requireResult(await request('read_controller_state'));
      if (!confirmed || connection !== socket || connection.readyState !== WebSocket.OPEN
          || current()?.instance_id !== instance || !current()?.control?.controlling
          || current()?.control?.generation !== generation || current()?.status?.session_id !== sid
          || fresh.instance_id !== instance || !fresh.control?.controlling || fresh.control.generation !== generation
          || fresh.status?.session_id !== sid || fresh.status.session_state !== 'completed'
          || entry.result?.outcome?.details?.session_id !== sid) return;
      entry.continuationPending = false;
      await releaseSessionBinding(sid);
    } finally { entry.continuationPending = false; controls(); }
  }), 'Request Normal Stop and preservation, then release this Session only after Controller confirms success. Release is independently checked by Controller.');
};
document.addEventListener('click', event => {
  const button = event.target.closest('[data-live-session-kill]');
  if (!button || button.disabled || !canControl()) return;
  const sid = current()?.status.session_id;
  confirmStop('Session Kill', () => command('kill_session', {operator_authorized: true}, sid),
    'Explicitly authorize forced Session closeout. Partial preservation and cleanup obligations may remain. This does not Kill a service.',
    {title: 'Authorize Kill Session?', confirm: 'Authorize Kill Session', cancel: 'Cancel'});
});
state.actions.releaseSession = () => {
  const sid = current()?.status.session_id, connection = socket;
  const instance = current()?.instance_id, generation = current()?.control?.generation;
  confirmStop('Session release', () => {
    if (current()?.status.session_id === sid && ['completed', 'failed', 'aborted'].includes(current()?.status.session_state)
        && connection === socket && current()?.instance_id === instance
        && current()?.control?.generation === generation && canControl()) releaseSessionBinding(sid);
  }, 'Retry only Session release. Controller checks preservation and cleanup; Normal Stop will not be repeated.',
  {title: 'Retry Session Release?', confirm: 'Retry Release', cancel: 'Cancel'});
};
function frameworkExperimentConfiguration(configuration) {
  const participating_devices = Object.create(null), device_configurations = Object.create(null);
  for (const id of configuration.participants) {
    const device = devices.find(item => item.id === id);
    if (!device?.available) throw new Error('Participating inventory is unconfirmed.');
    (participating_devices[device.nodeId] ??= []).push(device.deviceId);
    const parameters = Object.create(null);
    for (const field of deviceExamples[id]?.fields || []) if (Object.hasOwn(configuration.values, field.id)) parameters[field.name] = configuration.values[field.id];
    if (Object.keys(parameters).length) (device_configurations[device.nodeId] ??= Object.create(null))[device.deviceId] = parameters;
  }
  return {duration_s: configuration.durationSeconds, participating_devices, device_configurations,
    recording_budgets: configuration.recordingBudgets || null, preservation_budget_bytes: configuration.preservationBudget ?? null};
}
let estimateRequest = null;
state.actions.refreshExpectedSize = async () => {
  const context = resolveParameterContext(state);
  if (!context || context.readOnly || !confirmed) return;
  const configuration = context.configuration, key = experimentEstimateKey(configuration);
  const session = current()?.status?.session_id || null, instance = current()?.instance_id, connection = socket;
  let location = null, locationError = null;
  try { location = current()?.configuration?.storage_location || selectedArtifactDestination(); }
  catch (error) { locationError = error.message; }
  const prior = experimentStorageEstimate(state, configuration);
  if (prior && prior.session === session && prior.instance === instance && prior.location === location) return;
  state.expectedSize = null;
  if (estimateRequest) return;
  const attempt = {configuration, key, session, instance, location, pending: true, result: null};
  state.expectedSize = estimateRequest = attempt;
  const feedback = document.querySelector('[data-expected-size]');
  if (feedback) feedback.textContent = 'Expected size: Calculating…';
  controls();
  try {
    if (locationError) throw new Error(locationError);
    if (!Number.isFinite(configuration.durationSeconds) || configuration.durationSeconds <= 0
        || !configuration.participants.length) throw new Error('Set duration and participating devices to estimate storage.');
    const config = frameworkExperimentConfiguration(configuration);
    config.recording_budgets = null; config.preservation_budget_bytes = null;
    const parameters = {configuration: config, scientific_outputs: configuration.outputs || [], storage_location: location};
    const reply = await request('estimate_experiment_storage', parameters, session);
    const result = requireResult(reply);
    if (connection !== socket || !confirmed || instance !== current()?.instance_id
        || session !== (current()?.status?.session_id || null) || state.expectedSize !== attempt
        || key !== experimentEstimateKey(configuration) || resolveParameterContext(state)?.configuration !== configuration) return;
    if (reply.instance_id !== instance || result.session_id !== session || !configurationEqual(result.configuration, config)
        || !configurationEqual(result.scientific_outputs, parameters.scientific_outputs)
        || result.storage_location !== location) throw new Error('Estimation confirmation does not match preparation.');
    attempt.result = result;
  } catch (error) { attempt.error = error.message; }
  finally {
    attempt.pending = false; estimateRequest = null;
    if (state.expectedSize === attempt) {
      const context = resolveParameterContext(state);
      if (!$('#panel-parameters').hidden && !context?.readOnly && context?.configuration === configuration)
        renderStorageEstimate(configuration);
      controls();
    }
    else state.actions.refreshExpectedSize();
  }
};
state.actions.startExperiment = localAction('start_launched_experiment', async entry => {
  const {step, record} = selectedStepContext(state), configuration = experimentView(state, step, record).configuration;
  const issues = experimentIssues(state, step, configuration);
  if (issues.length) throw new Error(issues.join(' '));
  state.submittedExperiment = {stepId: step.id, experimentId: configuration.experimentId};
  await command('start_launched_experiment', {experiment_id: configuration.experimentId,
    configuration: frameworkExperimentConfiguration(configuration), scientific_outputs: configuration.outputs}, current()?.status?.session_id || null, entry);
  if (current()?.status.active_experiment_id) navigate('experiment');
});
document.addEventListener('gui-destinations-changed', () => state.actions.refreshExpectedSize());
document.addEventListener('change', event => {
  if (event.target.id === 'artifact-destination') state.actions.refreshExpectedSize();
});
state.actions.stopExperiment = () => { const sid = current()?.status.session_id, id = current()?.status.active_experiment_id; confirmStop('Experiment', () => command('stop_launched_experiment', {experiment_id: id}, sid), 'Request early Stop and preservation; the Session remains active.'); };
state.actions.reconcileExpiry = () => command('reconcile_launched_experiment_expiry', {experiment_id: current()?.status.active_experiment_id});
$('#take-over').onclick = () => command('take_browser_control', {}, null);
$('#view-only').onclick = () => command('view_only', {}, null);
async function refreshInventory(node) {
  const entry = recordActivity('get_node_inventory');
  if (inventoryRequest || !confirmed || busy || !node) { actionRefusal(entry, 'Inventory refresh is unavailable or already pending. No request was sent.'); return; }
  const connection = socket, instance = current()?.instance_id, session = current()?.status?.session_id || null;
  inventoryRequest = node;
  $('#inventory-status').textContent = `${node}: Refreshing inventory; confirmation pending`;
  $('#inventory-status').setAttribute('aria-busy', 'true');
  controls();
  try {
    const inventory = requireResult(await request('get_node_inventory', {node_id: node}));
    if (connection !== socket || socket.readyState !== WebSocket.OPEN || instance !== current()?.instance_id
        || session !== (current()?.status?.session_id || null)) throw new Error('Inventory belongs to an unconfirmed connection, Controller or Session');
    state.inventory[node] = clone(inventory);
    state.expectedSize = null;
    if (inventory.administrative_configuration?.available) {
      for (const entry of outcomes.filter(entry => entry.operation === 'update_device_configuration'
          && entry.status === 'uncertain' && entry.configurationNode === node && entry.instance_id === instance))
        entry.configurationReconciled = true;
    }
    devices.splice(0, devices.length, ...devices.filter(device => device.nodeId !== node), ...inventory.devices.map(declaration => ({id: configurationIdentity(node, declaration.device_id), nodeId: node, deviceId: declaration.device_id, declaration: clone(declaration), name: declaration.device_id, detail: node, capabilities: declaration.declared_capabilities || [], available: declaration.enabled === true})));
    for (const device of devices.filter(item => item.nodeId === node)) deviceExamples[device.id] = {acquisition: Boolean(device.declaration.scientific_products?.length), fields: deviceParameterFields(node, device.deviceId, inventory.session_parameter_definitions?.[device.deviceId] || {})};
    if (current()) applyControllerSnapshot(state, current());
    $('#inventory-status').textContent = `${node}: inventory confirmed; readiness remains Controller-owned`;
    updateActivity(entry, {status: 'succeeded'});
  } catch (error) { updateActivity(entry, {status: 'unknown', error: error.message}); if (state.inventory[node]) { delete state.inventory[node].configured_parameters; delete state.inventory[node].administrative_configuration; } for (const device of devices.filter(item => item.nodeId === node)) device.available = false; $('#inventory-status').textContent = `${node}: unconfirmed · ${error.message}`; }
  finally {
    inventoryRequest = null;
    $('#inventory-status').removeAttribute('aria-busy');
    renderSetup(); renderSession(); controls();
    if (!$('#panel-parameters').hidden) renderParameters();
  }
  // A Session transition can occur while this read is pending. Its refresh was
  // serialized out above; now read the new scope rather than retaining the old one.
  if (confirmed && connection === socket && instance === current()?.instance_id
      && session !== (current()?.status?.session_id || null)) await refreshInventory(node);
}
$('#load-inventory').onclick = () => refreshInventory($('#inventory-node').value);
state.actions.refreshInventory = refreshInventory;
state.actions.updateDeviceConfiguration = async (node, device, parameters, revision, administrator) => {
  const entry = recordActivity('update_device_configuration');
  entry.configurationNode = node;
  await command('update_device_configuration', {node_id: node, device_id: device, parameters,
    expected_revision: revision, administrator_id: administrator, authorized: true}, null, entry);
  await refreshInventory(node);
  return entry;
};
function connect() {
  confirmed = false; controls(); socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  socket.onmessage = event => {
    let message;
    try { message = parseConfigurationJSON(event.data); }
    catch (error) {
      noteConnectionLoss(error.message);
      confirmed = false; invalidateServiceConfirmation(); controls(); $('#connection-state').textContent = `Unconfirmed: ${error.message}`;
      for (const pending of waiting.values()) { clearTimeout(pending.timer); pending.reject(pending.uncertain(error.message)); }
      waiting.clear(); return;
    }
    if (message.type === 'connected') { browserId = message.browser_id; refresh(); return; }
    const pending = waiting.get(message.id);
    if (pending) { clearTimeout(pending.timer); waiting.delete(message.id); pending.resolve(message); }
  };
  socket.onclose = () => { noteConnectionLoss('Backend disconnected.'); confirmed = false; invalidateServiceConfirmation(); for (const device of devices) device.available = false; renderSetup(); controls(); $('#connection-state').textContent = 'Backend disconnected · last-known state'; for (const pending of waiting.values()) { clearTimeout(pending.timer); pending.reject(pending.uncertain('Connection lost; outcome uncertain')); } waiting.clear(); setTimeout(connect, 2000); };
}
$('.readiness-card').insertAdjacentHTML('beforeend', '<details><summary>Authoritative timing and closeout</summary><pre id="live-timing-status">Unconfirmed</pre><pre id="live-closeout-status">Unconfirmed</pre></details>');
serviceActions.canControl = canControl;
serviceActions.refresh = async (id, explicit = false) => {
  const entry = explicit ? recordActivity('check_readiness') : null;
  if (!confirmed) { if (entry) actionRefusal(entry, 'Controller connection is unconfirmed. No check was sent.'); return; }
  if (entry && !liveServices.some(service => (!id || service.id === id) && !service.pending)) {
    actionRefusal(entry, 'No configured service is available for a new check, or a check is already pending. No additional request was sent.'); return;
  }
  const connection = socket, instance = current()?.instance_id;
  await Promise.all(liveServices.filter(s => (!id || s.id === id) && !s.pending).map(async service => {
    let notice;
    service.pending = true; updateServices(liveServices, 'Checking readiness; confirmation pending');
    try {
      const result = requireResult(await request('read_service_status', {participant: service.participant}));
      if (!confirmed || connection !== socket || socket.readyState !== WebSocket.OPEN || instance !== current()?.instance_id || !liveServices.includes(service)) return;
      service.current = result.current === true;
      service.details = result.details;
      service.diagnosticsCurrent = typeof result.details?.operational_instance_id === 'string'
        && result.details.operational_instance_id.length > 0;
      service.attempt = service.current ? result.details.maintenance_attempt : null;
      if (service.current) { service.readiness = result.report.ready ? 'Ready' : 'Not ready'; service.confirmed = new Date().toISOString(); service.information = result.report.reason; }
      else service.information = result.details?.readiness_error || result.reason;
      notice = `${service.name}: readiness check completed; ${service.current ? service.readiness : 'availability unknown'}. ${service.information || ''}`;
    } catch (error) {
      if (connection !== socket || instance !== current()?.instance_id || !liveServices.includes(service)) return;
      service.current = false; service.diagnosticsCurrent = false; service.attempt = null;
      service.information = `Availability unknown: ${error.message}`;
      notice = `${service.name}: readiness check unconfirmed. ${service.information}`;
    }
    finally { service.pending = false; updateServices(liveServices, notice); }
  }));
  if (entry) updateActivity(entry, {status: liveServices.filter(service => !id || service.id === id).every(service => service.current) ? 'succeeded' : 'unknown', error: 'Availability remains unknown for services without a current confirmed report.'});
  const sid = current()?.status?.session_id;
  if (!id && sid && !timingPending && liveServices.some(s => s.participant.component_type === 'synchronization_manager')) {
    timingPending = true;
    try {
      const timing = requireResult(await request('read_synchronization_status', {}, sid));
      if (connection === socket && socket.readyState === WebSocket.OPEN && instance === current()?.instance_id && sid === current()?.status?.session_id)
        $('#live-timing-status').textContent = JSON.stringify(timing, null, 2);
    } catch (error) { $('#live-timing-status').textContent = `Current timing unavailable: ${error.message}`; }
    finally { timingPending = false; }
  }
};
serviceActions.maintain = async (operation, service, administrator_id, recovery = null) => {
  if (!canControl()) { actionRefusal(recordActivity(operation), 'Current control and confirmed operation context are required. No request was sent.'); return; }
  const parameters = {administrator_id, authorized: true};
  if (recovery) Object.assign(parameters, recovery);
  if (service) {
    parameters.participant = service.participant;
    if (!recovery && operation !== 'stop_service') {
      if (service.attempt?.outcome !== 'blocked') { actionRefusal(recordActivity(operation), 'A current blocked Stop attempt is required. No request was sent.'); return; }
      parameters.stop_attempt_id = service.attempt.stop_attempt_id;
    }
    service.attempt = null;
    service.lastOperation = null;
  }
  updateServices(liveServices, 'Operation submitted; owner confirmation pending. No automatic retry or force escalation.');
  const entry = await command(operation, parameters, null);
  if (service) service.lastOperation = entry;
  if (service) await serviceActions.refresh(service.id);
  updateServices(liveServices, service ? undefined : '');
  const blocked = entry.result?.outcome?.details;
  if (operation === 'stop_service' && blocked?.outcome === 'blocked'
      && service?.attempt?.outcome === 'blocked'
      && service.attempt.stop_attempt_id === blocked.attempt?.stop_attempt_id && canControl())
    showBlockedServiceStop(service);
};
startServicesRefresh();
connect();
setInterval(() => { if (socket?.readyState === WebSocket.OPEN) refresh(); }, 2000);
