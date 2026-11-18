// Shared presenters own markup; this entry binds them to the existing backend.
import { state, renderSetup } from './protocol-setup.js';
import { devices, clone, preparedProtocol, preparedFreeOperation } from './protocol-demo.mjs';
import { deviceExamples, experimentView, experimentIssues } from './experiment-demo.mjs';
import { applyControllerSnapshot } from './session-context.mjs';
import { selectedStepContext } from './session-demo.mjs';
import { renderSession } from './session-view.js';
import { renderParameters } from './parameters-view.js';
import { renderExperiment } from './scientific-views.js';
import { navigate, configurationStringEditor, setConfigurationString, readConfigurationString } from './gui-presentation.js';
import { localCalendarDate } from './calendar-date.mjs';
import { confirmStop } from './stop-confirmation.mjs';
import { serviceActions, updateServices, startServicesRefresh, showBlockedServiceStop } from './services-view.js';
import { configurationIdentity, configurationNumber, parseConfigurationJSON, stringifyConfiguration } from './configuration-values.mjs';
import { activities as outcomes, recordActivity, updateActivity, recordLocalActivity, recordActivityTransition } from './activity-history.mjs';
import { deviceParameterFields } from './parameter-constraints.mjs';
import { installArtifactDestinations, refreshArtifactDestinations, syncArtifactDestinations, invalidateArtifactDestinations, selectedArtifactDestination } from './artifact-destinations.js';

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
  invalidateArtifactDestinations();
  // Replace projections so replies admitted before this loss cannot promote them.
  liveServices = liveServices.map(service => ({...service, current: false, diagnosticsCurrent: false, pending: false, attempt: null}));
  updateServices(liveServices, 'Controller confirmation unavailable; current service availability is unknown.');
}

$('.topbar').insertAdjacentHTML('beforeend', '<div class="connection-tools"><span id="connection-state" role="status">Connecting</span><button id="view-only" type="button">View Only</button><button id="take-over" type="button">Take Over</button></div>');
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
storageBody.insertAdjacentHTML('beforeend', '<label>Error evidence location<input id="error-evidence-location"></label><details><summary>Additional Session configuration</summary><label>Framework configuration fields (JSON)<textarea id="session-framework-fields" rows="7" spellcheck="false" placeholder="Explicit protocol_plan, synchronization_configuration and applicable storage/acquisition settings"></textarea></label></details>');
const sessionName = configurationStringEditor($('.session-identity-grid input[type="text"]'));
const sessionDate = $('.session-identity-grid input[type="date"]');
const sessionNumber = $('.session-identity-grid input[type="number"]');
const sessionNotes = configurationStringEditor($('[aria-labelledby="notes-title"] textarea'));
const errorLocation = configurationStringEditor($('#error-evidence-location'));
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
($('.device-card .setup-disclosure-body') || $('.device-card')).insertAdjacentHTML('afterbegin', '<div class="inventory-controls"><label>Configured AcquisitionNode<select id="inventory-node"></select></label><button id="load-inventory" type="button">Refresh inventory</button><span id="inventory-status" role="status">Inventory unconfirmed</span></div>');
$('.readiness-card').insertAdjacentHTML('beforeend', '<details><summary>Accepted Session configuration</summary><pre id="accepted-configuration">No accepted configuration confirmed</pre></details>');
$('#load-inventory').className = 'dialog-button';
$('#inventory-status').className = 'prototype-caption';
$('#device-validation-maximum').disabled = true;
$('#device-validation-maximum').closest('label').title = 'Device Validation integration unavailable';

function canControl(except = null) {
  return confirmed && current()?.control?.controlling && !busy && !outcomes.some(o => o !== except && o.controllerCommand && ['pending', 'uncertain'].includes(o.status));
}
function controls() {
  const status = current()?.status;
  const launch = outcomes.findLast(entry => entry.operation === 'launch_session');
  if (!status?.session_id && launch) $('.setup-demo-note').textContent = 'Session launch not confirmed. See Activity History in Services.';
  document.documentElement.dataset.controlMode = !confirmed ? 'unconfirmed' : current()?.control?.controlling ? 'controlling' : 'view-only';
  $('.launch-session-demo').disabled = !canControl() || Boolean(status?.session_id);
  $('.launch-session-demo span').textContent = !confirmed ? 'Controller connection unconfirmed' : status?.session_id ? 'Session accepted' : current()?.control?.controlling ? 'Request Controller launch' : 'View Only';
  for (const control of [sessionName, sessionDate, sessionNumber, sessionNotes, errorLocation, $('#session-framework-fields')]) {
    control.readOnly = Boolean(status?.session_id);
    if (control.nextElementSibling?.hasAttribute('data-string-mode')) control.nextElementSibling.disabled = control.readOnly;
  }
  for (const button of document.querySelectorAll('[data-launch-experiment], [data-stop-experiment], [data-reconcile-expiry], [data-stop-session], [data-start-session], [data-release-session]')) {
    if (!canControl()) button.disabled = true;
    if (button.hasAttribute('data-start-session')) button.disabled = !canControl() || status?.session_state !== 'initialized';
    if (button.hasAttribute('data-stop-session')) button.disabled = !canControl() || !status?.session_id;
    if (button.hasAttribute('data-release-session')) button.disabled = !canControl() || !['completed', 'failed', 'aborted'].includes(status?.session_state);
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
  updateServices(liveServices);
  syncArtifactDestinations();
}
state.actions.syncControls = controls;
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
    recordActivityTransition('connection_status', 'succeeded');
    if (snapshot.control?.controlling && (!previous?.control?.controlling || previous.instance_id !== snapshot.instance_id))
      document.dispatchEvent(new Event('gui-control-acquired'));
    const previousServices = liveServices;
    const changedOwner = previous?.instance_id !== snapshot.instance_id;
    if (changedOwner) invalidateArtifactDestinations();
    if (changedOwner || !wasConfirmed) refreshArtifactDestinations();
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
      for (const key of ['experimenter', 'project', 'animal']) {
        if (typeof metadata[key] !== 'string' || !metadata[key]) continue;
        const select = $(`#${key}-select`);
        let option = [...select.options].find(item => item.textContent === metadata[key]);
        if (!option) { option = new Option(metadata[key], metadata[key]); select.add(option, select.lastElementChild); }
        select.value = option.value; select.dataset.previousValue = option.value;
      }
      setConfigurationString(errorLocation, config.error_evidence_location ?? '');
      $('#session-framework-fields').value = JSON.stringify(config, null, 2);
      setConfigurationString(sessionNotes, metadata.notes ?? '');
    }
    if (previous?.instance_id === snapshot.instance_id && previous?.status?.session_id
        && !snapshot.status?.session_id && snapshot.configuration === null) {
      sessionDate.value = localCalendarDate(); sessionDate.dispatchEvent(new Event('input'));
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
    let completedNavigation = null;
    for (const entry of outcomes.filter(o => o.controllerCommand && o.request_id && o.instance_id && ['pending', 'uncertain'].includes(o.status))) {
      const result = requireResult(await request('read_operation_outcome', {target_request_id: entry.request_id, instance_id: entry.instance_id}));
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
        ? {source: 'controller', status: 'uncertain', request_id: error.request_id, instance_id: error.instance_id, error: error.message}
        : {source: 'submission', status: 'failed', error: error.message, controllerCommand: false});
      return entry;
    }
    // Rendering a received result must not turn that result into a synthetic failure.
    updateActivity(entry, {source: reply.result ? 'controller' : 'submission',
      instance_id: reply.instance_id || reply.submitted_instance_id,
      request_id: reply.result?.request_id || reply.submitted_request_id,
      status: reply.result?.status || reply.status, result: reply.result || reply,
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
state.actions.launchSession = localAction('launch_session', async entry => {
  let config;
  try { config = parseConfigurationJSON($('#session-framework-fields').value); }
  catch (error) { throw new Error(error instanceof SyntaxError ? 'Additional Session configuration: enter valid JSON framework configuration.' : `Additional Session configuration: ${error.message}`); }
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('Additional Session configuration must be an object.');
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
  await command('launch_session', {selections, config_parameters: config, scientific_outputs: []}, null, entry);
  if (current()?.status.session_id) navigate('session');
});
state.actions.startSession = () => command('start_launched_session');
state.actions.stopSession = () => { const sid = current()?.status.session_id; confirmStop('Session', () => command('normal_stop_session', {}, sid), 'Request Normal Stop and preservation. Completion requires Controller confirmation.'); };
document.addEventListener('click', event => {
  const button = event.target.closest('[data-live-session-kill]');
  if (!button || button.disabled || !canControl()) return;
  const sid = current()?.status.session_id;
  confirmStop('Session Kill', () => command('kill_session', {operator_authorized: true}, sid),
    'Explicitly authorize forced Session closeout. Partial preservation and cleanup obligations may remain. This does not Kill a service.',
    {title: 'Authorize Kill Session?', confirm: 'Authorize Kill Session', cancel: 'Cancel'});
});
state.actions.releaseSession = () => { const sid = current()?.status.session_id; confirmStop('Session release', () => command('release_session', {}, sid), 'Release only after Controller confirms terminal preservation and cleanup.', {title: 'Release Session?', confirm: 'Release Session', cancel: 'Cancel'}); };
state.actions.startExperiment = localAction('start_launched_experiment', async entry => {
  const {step, record} = selectedStepContext(state), configuration = experimentView(state, step, record).configuration;
  const issues = experimentIssues(state, step, configuration);
  if (issues.length) throw new Error(issues.join(' '));
  const participating_devices = Object.create(null), device_configurations = Object.create(null);
  for (const id of configuration.participants) {
    const device = devices.find(item => item.id === id);
    if (!device?.available) throw new Error('Participating inventory is unconfirmed.');
    (participating_devices[device.nodeId] ??= []).push(device.deviceId);
    const parameters = Object.create(null);
    for (const field of deviceExamples[id]?.fields || []) if (Object.hasOwn(configuration.values, field.id)) parameters[field.name] = configuration.values[field.id];
    if (Object.keys(parameters).length) (device_configurations[device.nodeId] ??= Object.create(null))[device.deviceId] = parameters;
  }
  state.submittedExperiment = {stepId: step.id, experimentId: configuration.experimentId};
  await command('start_launched_experiment', {experiment_id: configuration.experimentId, configuration: {duration_s: configuration.durationSeconds, participating_devices, device_configurations, recording_budgets: configuration.recordingBudgets, preservation_budget_bytes: configuration.preservationBudget}, scientific_outputs: configuration.outputs}, current()?.status?.session_id || null, entry);
  if (current()?.status.active_experiment_id) navigate('experiment');
});
state.actions.stopExperiment = () => { const sid = current()?.status.session_id, id = current()?.status.active_experiment_id; confirmStop('Experiment', () => command('stop_launched_experiment', {experiment_id: id}, sid), 'Request early Stop and preservation; the Session remains active.'); };
state.actions.reconcileExpiry = () => command('reconcile_launched_experiment_expiry', {experiment_id: current()?.status.active_experiment_id});
$('#take-over').onclick = () => command('take_browser_control', {}, null);
$('#view-only').onclick = () => command('view_only', {}, null);
$('#load-inventory').onclick = async () => {
  const node = $('#inventory-node').value;
  const entry = recordActivity('get_node_inventory');
  if (inventoryRequest || !confirmed || busy || !node) { actionRefusal(entry, 'Inventory refresh is unavailable or already pending. No request was sent.'); return; }
  const connection = socket, instance = current()?.instance_id;
  inventoryRequest = node;
  $('#inventory-status').textContent = `${node}: Refreshing inventory; confirmation pending`;
  $('#inventory-status').setAttribute('aria-busy', 'true');
  controls();
  try {
    const inventory = requireResult(await request('get_node_inventory', {node_id: node}));
    if (connection !== socket || socket.readyState !== WebSocket.OPEN || instance !== current()?.instance_id) throw new Error('Inventory belongs to an unconfirmed connection or Controller instance');
    state.inventory[node] = clone(inventory);
    devices.splice(0, devices.length, ...devices.filter(device => device.nodeId !== node), ...inventory.devices.map(declaration => ({id: configurationIdentity(node, declaration.device_id), nodeId: node, deviceId: declaration.device_id, declaration: clone(declaration), name: declaration.device_id, detail: node, capabilities: declaration.declared_capabilities || [], available: declaration.enabled === true})));
    for (const device of devices.filter(item => item.nodeId === node)) deviceExamples[device.id] = {acquisition: Boolean(device.declaration.scientific_products?.length), fields: deviceParameterFields(node, device.deviceId, inventory.session_parameter_definitions?.[device.deviceId] || {})};
    if (current()) applyControllerSnapshot(state, current());
    $('#inventory-status').textContent = `${node}: inventory confirmed; readiness remains Controller-owned`;
    updateActivity(entry, {status: 'succeeded'});
  } catch (error) { updateActivity(entry, {status: 'unknown', error: error.message}); for (const device of devices.filter(item => item.nodeId === node)) device.available = false; $('#inventory-status').textContent = `${node}: unconfirmed · ${error.message}`; }
  finally {
    inventoryRequest = null;
    $('#inventory-status').removeAttribute('aria-busy');
    renderSetup(); renderSession(); controls();
  }
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
