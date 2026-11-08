// Shared presenters own markup; this entry binds them to the existing backend.
import { state, renderSetup } from './protocol-setup.js';
import { devices, clone } from './protocol-demo.mjs';
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

const $ = selector => document.querySelector(selector);
let socket, browserId, confirmed = false, busy = false, refreshing = false, lastRender = '';
let inventoryRequest = null;
let liveServices = [];
let timingPending = false;
const waiting = new Map();
let outcomes = [];
try { const stored = JSON.parse(sessionStorage.getItem('miceball-pending') || '[]');
  if (Array.isArray(stored)) outcomes = stored.filter(o => o && typeof o.request_id === 'string' && typeof o.instance_id === 'string');
} catch (_) {}
const current = () => state.controllerSnapshot;
const save = () => sessionStorage.setItem('miceball-pending', JSON.stringify(outcomes));
const ownershipOperation = entry => ['take_browser_control', 'view_only'].includes(entry.operation);
serviceActions.controlHistory = () => outcomes.filter(ownershipOperation);
function invalidateServiceConfirmation() {
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
const storageLocation = configurationStringEditor(storageCard.querySelector('input'));
const errorLocation = configurationStringEditor($('#error-evidence-location'));
($('.device-card .setup-disclosure-body') || $('.device-card')).insertAdjacentHTML('afterbegin', '<div class="inventory-controls"><label>Configured AcquisitionNode<select id="inventory-node"></select></label><button id="load-inventory" type="button">Refresh inventory</button><span id="inventory-status" role="status">Inventory unconfirmed</span></div>');
$('.readiness-card').insertAdjacentHTML('beforeend', '<details><summary>Accepted Session configuration</summary><pre id="accepted-configuration">No accepted configuration confirmed</pre></details>');
$('#load-inventory').className = 'dialog-button';
$('#inventory-status').className = 'prototype-caption';
$('#device-validation-maximum').disabled = true;
$('#device-validation-maximum').closest('label').title = 'Device Validation integration unavailable';

function canControl() {
  return confirmed && current()?.control?.controlling && !busy && !outcomes.some(o => ['pending', 'uncertain'].includes(o.status));
}
function controls() {
  const status = current()?.status;
  document.documentElement.dataset.controlMode = !confirmed ? 'unconfirmed' : current()?.control?.controlling ? 'controlling' : 'view-only';
  $('.launch-session-demo').disabled = !canControl() || Boolean(status?.session_id);
  $('.launch-session-demo span').textContent = !confirmed ? 'Controller connection unconfirmed' : status?.session_id ? 'Session accepted' : current()?.control?.controlling ? 'Request Controller launch' : 'View Only';
  for (const control of [sessionName, sessionDate, sessionNumber, sessionNotes, storageLocation, errorLocation, $('#session-framework-fields')]) {
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
  let display = $('#operation-results');
  if (!display) { display = document.createElement('div'); display.id = 'operation-results'; display.className = 'session-feedback'; display.setAttribute('role', 'status'); $('#panel-session').append(display); }
  const outcomeNodes = entries => entries.map(entry => {
    const details = document.createElement('details'), summary = document.createElement('summary'), text = document.createElement('p');
    summary.textContent = `${entry.operation} · ${entry.status}`;
    text.textContent = `${entry.request_id || 'Request identity unavailable'} · ${entry.result?.error || 'No automatic replay. Completion follows Controller readback.'}`;
    details.append(summary, text);
    return details;
  });
  display.replaceChildren(...outcomeNodes(outcomes.filter(entry => !ownershipOperation(entry))));
  updateServices(liveServices);
}
state.actions.syncControls = controls;
function request(operation, parameters = {}, session_id = null) {
  if (socket?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Backend disconnected; outcome unconfirmed'));
  const id = crypto.randomUUID(), request_id = `${browserId}-${id}`, instance_id = current()?.instance_id;
  const data = stringifyConfiguration({id, operation, session_id, parameters});
  return new Promise((resolve, reject) => {
    const uncertain = reason => Object.assign(new Error(reason), {request_id, instance_id});
    const timer = setTimeout(() => { waiting.delete(id); reject(uncertain('Response timeout; outcome unconfirmed')); }, 30000);
    waiting.set(id, {resolve: message => resolve({...message, submitted_request_id: request_id, submitted_instance_id: instance_id}), reject, timer, uncertain});
    socket.send(data);
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
    applyControllerSnapshot(state, snapshot); confirmed = true;
    const previousServices = liveServices;
    const changedOwner = previous?.instance_id !== snapshot.instance_id;
    liveServices = (snapshot.configured_services || []).map(participant => {
      const id = configurationIdentity(participant.component_type, participant.component_id);
      const prior = previousServices.find(s => s.id === id);
      if (prior) return changedOwner ? {...prior, current: false, diagnosticsCurrent: false, pending: false, attempt: null} : prior;
      return {id, participant,
        name: ({controller: 'Controller', acquisition_node: 'AcquisitionNode', ingestor: 'Ingestor', storage_manager: 'StorageManager', synchronization_manager: 'Synchronization Manager'})[participant.component_type],
        computer: participant.component_id, readiness: 'Unknown', current: false, confirmed: null};
    });
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
      setConfigurationString(storageLocation, config.storage_location ?? '');
      setConfigurationString(errorLocation, config.error_evidence_location ?? '');
      $('#session-framework-fields').value = JSON.stringify(config, null, 2);
      setConfigurationString(sessionNotes, metadata.notes ?? '');
    }
    if (previous?.instance_id === snapshot.instance_id && previous?.status?.session_id
        && !snapshot.status?.session_id && snapshot.configuration === null) {
      sessionDate.value = localCalendarDate(); sessionDate.dispatchEvent(new Event('input'));
    }
    for (const operation of snapshot.pending_operations) if (!outcomes.some(o => o.request_id === operation.request_id && o.instance_id === snapshot.instance_id)) outcomes.push({operation: operation.operation, request_id: operation.request_id, instance_id: snapshot.instance_id, status: 'pending'});
    $('#connection-state').textContent = `${snapshot.controller_id} · ${snapshot.control.controlling ? 'Controlling' : 'View Only'}`;
    $('.setup-demo-note').textContent = snapshot.status.session_id ? 'Accepted Session configuration is fixed. Catalog and unsent application edits cannot alter it.' : 'Unsent local preparation · Controller validates launch and preservation.';
    $('#accepted-configuration').textContent = JSON.stringify(snapshot.configuration, null, 2);
    const choice = $('#inventory-node');
    if (JSON.stringify([...choice.options].map(o => o.value)) !== JSON.stringify(snapshot.configured_nodes)) choice.replaceChildren(...snapshot.configured_nodes.map(id => new Option(id, id)));
    let completedNavigation = null;
    for (const entry of outcomes.filter(o => ['pending', 'uncertain'].includes(o.status))) {
      const result = requireResult(await request('read_operation_outcome', {target_request_id: entry.request_id, instance_id: entry.instance_id}));
      entry.status = result.status; entry.result = result.result;
      if (entry.status === 'succeeded' && entry.instance_id === snapshot.instance_id) {
        if (entry.operation === 'launch_session' && snapshot.status.session_id) completedNavigation = 'session';
        if (entry.operation === 'start_launched_experiment' && snapshot.status.active_experiment_id) completedNavigation = 'experiment';
      }
    }
    save();
    updateServices(liveServices);
    $('#live-closeout-status').textContent = JSON.stringify({closeout: snapshot.closeout || 'Unconfirmed', timing_interpretations: snapshot.timing || []}, null, 2);
    const signature = JSON.stringify([snapshot.instance_id, snapshot.control, snapshot.status, snapshot.configuration, snapshot.experiments]);
    if (signature !== lastRender) { lastRender = signature; renderSetup(); renderSession(); renderExperiment(); if (!$('#panel-parameters').hidden) renderParameters(); }
    if (completedNavigation) navigate(completedNavigation);
  } catch (error) { confirmed = false; invalidateServiceConfirmation(); $('#connection-state').textContent = `Unconfirmed · ${error.message}`; }
  finally { refreshing = false; controls(); }
}
async function command(operation, parameters = {}, session_id = current()?.status?.session_id || null) {
  if (!confirmed || busy || (!current()?.control.controlling && !['view_only', 'take_browser_control'].includes(operation))) return;
  if (!['view_only', 'take_browser_control'].includes(operation) && !canControl()) return;
  busy = true; controls();
  try {
    const reply = await request(operation, parameters, session_id);
    const entry = {operation, instance_id: reply.instance_id || reply.submitted_instance_id, request_id: reply.result?.request_id || reply.submitted_request_id, status: reply.result?.status || reply.status, result: reply.result || reply};
    outcomes.push(entry); save();
    return entry;
  } catch (error) {
    if (error.request_id && error.instance_id) {
      const entry = {operation, status: 'uncertain', request_id: error.request_id, instance_id: error.instance_id};
      outcomes.push(entry); save();
      return entry;
    }
    $('#connection-state').textContent = `Unconfirmed · ${error.message}`;
  } finally { busy = false; await refresh(); controls(); }
}
const localAction = action => async () => { try { await action(); } catch (error) { $('.setup-demo-note').textContent = error.message; } };
state.actions.launchSession = localAction(async () => {
  const config = parseConfigurationJSON($('#session-framework-fields').value);
  config.storage_location = readConfigurationString(storageLocation);
  config.error_evidence_location = readConfigurationString(errorLocation);
  config.session_parameters = {...config.session_parameters};
  for (const key of ['experimenter', 'project', 'animal']) {
    const select = $(`#${key}-select`);
    if (select.value.startsWith('__new_')) throw new Error(`Finish the local ${key} entry.`);
    if (select.value) config.session_parameters[key] = select.selectedOptions[0].textContent;
  }
  if (sessionNumber.validity.badInput) throw new Error('Invalid Session number. Enter a finite value representable by this GUI.');
  Object.assign(config.session_parameters, {name: readConfigurationString(sessionName), date: sessionDate.value, number: sessionNumber.value ? configurationNumber(sessionNumber.value) : null, notes: readConfigurationString(sessionNotes)});
  state.submittedProcedure = clone(state.protocols.find(protocol => protocol.id === state.protocolId) || null);
  if (state.submittedProcedure) state.submittedProcedure.included = clone(state.included);
  config.protocol_reference = state.submittedProcedure?.name || null;
  const selections = Object.create(null);
  for (const id of state.selectedDevices) {
    const device = devices.find(item => item.id === id);
    if (!device?.available) throw new Error('Selected inventory is unconfirmed.');
    (selections[device.nodeId] ??= []).push(clone(device.declaration));
  }
  await command('launch_session', {selections, config_parameters: config, scientific_outputs: []}, null);
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
state.actions.startExperiment = localAction(async () => {
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
  await command('start_launched_experiment', {experiment_id: configuration.experimentId, configuration: {duration_s: configuration.durationSeconds, participating_devices, device_configurations, recording_budgets: configuration.recordingBudgets, preservation_budget_bytes: configuration.preservationBudget}, scientific_outputs: configuration.outputs});
  if (current()?.status.active_experiment_id) navigate('experiment');
});
state.actions.stopExperiment = () => { const sid = current()?.status.session_id, id = current()?.status.active_experiment_id; confirmStop('Experiment', () => command('stop_launched_experiment', {experiment_id: id}, sid), 'Request early Stop and preservation; the Session remains active.'); };
state.actions.reconcileExpiry = () => command('reconcile_launched_experiment_expiry', {experiment_id: current()?.status.active_experiment_id});
$('#take-over').onclick = () => command('take_browser_control', {}, null);
$('#view-only').onclick = () => command('view_only', {}, null);
$('#load-inventory').onclick = async () => {
  const node = $('#inventory-node').value;
  if (inventoryRequest || !confirmed || busy || !node) return;
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
    for (const device of devices.filter(item => item.nodeId === node)) deviceExamples[device.id] = {acquisition: Boolean(device.declaration.scientific_products?.length), fields: Object.entries(inventory.session_parameter_definitions?.[device.deviceId] || {}).map(([name, definition]) => ({id: configurationIdentity(node, device.deviceId, name), name, label: name, type: definition.type === 'boolean' ? 'checkbox' : ['integer', 'number'].includes(definition.type) ? 'number' : 'text', integer: definition.type === 'integer', min: definition.minimum ?? definition.exclusive_minimum, max: definition.maximum, nullable: definition.nullable}))};
    if (current()) applyControllerSnapshot(state, current());
    $('#inventory-status').textContent = `${node}: inventory confirmed; readiness remains Controller-owned`;
  } catch (error) { for (const device of devices.filter(item => item.nodeId === node)) device.available = false; $('#inventory-status').textContent = `${node}: unconfirmed · ${error.message}`; }
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
      confirmed = false; invalidateServiceConfirmation(); controls(); $('#connection-state').textContent = `Unconfirmed: ${error.message}`;
      for (const pending of waiting.values()) { clearTimeout(pending.timer); pending.reject(pending.uncertain(error.message)); }
      waiting.clear(); return;
    }
    if (message.type === 'connected') { browserId = message.browser_id; refresh(); return; }
    const pending = waiting.get(message.id);
    if (pending) { clearTimeout(pending.timer); waiting.delete(message.id); pending.resolve(message); }
  };
  socket.onclose = () => { confirmed = false; invalidateServiceConfirmation(); for (const device of devices) device.available = false; renderSetup(); controls(); $('#connection-state').textContent = 'Backend disconnected · last-known state'; for (const pending of waiting.values()) { clearTimeout(pending.timer); pending.reject(pending.uncertain('Connection lost; outcome uncertain')); } waiting.clear(); setTimeout(connect, 2000); };
}
$('.readiness-card').insertAdjacentHTML('beforeend', '<details><summary>Authoritative timing and closeout</summary><pre id="live-timing-status">Unconfirmed</pre><pre id="live-closeout-status">Unconfirmed</pre></details>');
serviceActions.canControl = canControl;
serviceActions.frameworkOutcome = () => outcomes.findLast(entry => entry.operation === 'shutdown_framework');
serviceActions.refresh = async id => {
  if (!confirmed) return;
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
  if (!canControl()) return;
  const parameters = {administrator_id, authorized: true};
  if (recovery) Object.assign(parameters, recovery);
  if (service) {
    parameters.participant = service.participant;
    if (!recovery && operation !== 'stop_service') {
      if (service.attempt?.outcome !== 'blocked') return;
      parameters.stop_attempt_id = service.attempt.stop_attempt_id;
    }
    service.attempt = null;
    service.lastOperation = {operation, status: 'pending'};
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
